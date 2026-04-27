#pragma once

#include "splinterdb/data.h"
#include "platform.h"
#include "data_internal.h"
#include "splinterdb/transaction.h"
#include "util.h"
#include "experimental_mode.h"
#include "splinterdb_internal.h"
#include "FPSketch/iceberg_table.h"
#include "transaction_stats.h"
#include "poison.h"

#include <stdint.h>

// --- History-buffer infrastructure ------------------------------------------
// An iceberg-managed histcache stores a per-key tictoc_hist_entry.
// On each committed write we record commit_ts (the NEW wts) under the entry's
// mutex.  At soft-abort validation we check whether any recorded new_wts falls
// strictly inside (local_wts, commit_ts].  If none does, the abort is
// unnecessary and we skip it.
//
// The tictoc_hist_entry pointer is stored in the low 64 bits of the 128-bit
// iceberg ValueType.  The inserting thread allocates and stores atomically;
// concurrent threads spin-wait (< ~100 ns) until the pointer is non-null.
// iceberg's post_remove callback frees the entry when refcount hits 0.

#define EXT_HIST_MAX_WRITES MAX_THREADS

typedef struct {
   txn_timestamp  wts_list[EXT_HIST_MAX_WRITES]; // new wts values from writes
   int            count;
   platform_mutex lock;
} tictoc_hist_entry;

// Store/retrieve tictoc_hist_entry* in low 64 bits of iceberg ValueType.
// ValueType = unsigned __int128 (128 bits); low 64 bits on little-endian x86.
static inline void
hist_value_set_ptr(ValueType *val, tictoc_hist_entry *ptr)
{
   __atomic_store_n(
      (uint64_t *)val, (uint64_t)(uintptr_t)ptr, __ATOMIC_RELEASE);
}

static inline tictoc_hist_entry *
hist_value_get_ptr(const ValueType *val)
{
   return (tictoc_hist_entry *)(uintptr_t)__atomic_load_n(
      (const uint64_t *)val, __ATOMIC_ACQUIRE);
}

// Called by iceberg when refcount hits 0 and the entry is evicted.
static void
hist_post_remove(slice key, ValueType *val, void *aux)
{
   tictoc_hist_entry *he = hist_value_get_ptr(val);
   if (he) {
      platform_mutex_destroy(&he->lock);
      platform_free(0, he);
   }
}

// ---------------------------------------------------------------------------

typedef struct transactional_splinterdb_config {
   splinterdb_config           kvsb_cfg;
   transaction_isolation_level isol_level;
   iceberg_config              iceberght_config;
   iceberg_config              histcache_config;
   bool                        is_upsert_disabled;
} transactional_splinterdb_config;

typedef struct transactional_splinterdb {
   splinterdb                      *kvsb;
   transactional_splinterdb_config *tcfg;
   iceberg_table                   *tscache;
   iceberg_table                   *histcache;

#if USE_TRANSACTION_STATS
   transaction_stats txn_stats;
#endif
} transactional_splinterdb;


typedef struct {
   txn_timestamp lock_bit : 1;
   txn_timestamp wts : 63;
   txn_timestamp delta : 64;
} timestamp_set __attribute__((aligned(sizeof(txn_timestamp))));

static inline bool
timestamp_set_is_equal(const timestamp_set *s1, const timestamp_set *s2)
{
   return memcmp((const void *)s1, (const void *)s2, sizeof(timestamp_set))
          == 0;
}

static inline txn_timestamp
timestamp_set_get_rts(timestamp_set *ts)
{
   return ts->wts + ts->delta;
}

static inline bool
timestamp_set_compare_and_swap(timestamp_set *ts,
                               timestamp_set *v1,
                               timestamp_set *v2)
{
   return __atomic_compare_exchange((volatile txn_timestamp *)ts,
                                    (txn_timestamp *)v1,
                                    (txn_timestamp *)v2,
                                    TRUE,
                                    __ATOMIC_RELAXED,
                                    __ATOMIC_RELAXED);
}

static inline void
timestamp_set_load(timestamp_set *ts, timestamp_set *v)
{
   __atomic_load(
      (volatile txn_timestamp *)ts, (txn_timestamp *)v, __ATOMIC_RELAXED);
}

typedef struct rw_entry {
   slice              key;
   message            msg;
   txn_timestamp      wts;
   txn_timestamp      rts;
   timestamp_set     *tuple_ts;
   bool               is_read;
   tictoc_hist_entry *hist_entry; // points into histcache; NULL if not inserted
} rw_entry;

static inline bool
rw_entry_iceberg_insert(transactional_splinterdb *txn_kvsb, rw_entry *entry)
{
   if (entry->tuple_ts) {
      return FALSE;
   }

   timestamp_set ts = {0};
   entry->tuple_ts  = &ts;
   return iceberg_insert_and_get_without_increasing_refcount(
      txn_kvsb->tscache,
      &entry->key,
      (ValueType **)&entry->tuple_ts,
      platform_get_tid());
}

static inline void
rw_entry_iceberg_remove(transactional_splinterdb *txn_kvsb, rw_entry *entry)
{
   if (!entry->tuple_ts) {
      return;
   }
   entry->tuple_ts = NULL;
}

// Insert into histcache with refcount; allocate tictoc_hist_entry if new.
static inline void
rw_entry_histcache_insert(transactional_splinterdb *txn_kvsb, rw_entry *entry)
{
   if (entry->hist_entry) {
      return; // already holds a reference
   }

   ValueType  initial_val = 0;
   ValueType *val_ptr     = &initial_val;
   bool is_new = iceberg_insert_and_get(
      txn_kvsb->histcache, &entry->key, &val_ptr, platform_get_tid());

   if (is_new) {
      tictoc_hist_entry *he = TYPED_ZALLOC(0, he);
      platform_mutex_init(&he->lock, 0, 0);
      hist_value_set_ptr(val_ptr, he);
   } else {
      // Spin until the inserting thread sets the pointer (~< 100 ns).
      while (hist_value_get_ptr(val_ptr) == NULL) {
         __asm__ volatile("pause" ::: "memory");
      }
   }

   entry->hist_entry = hist_value_get_ptr(val_ptr);
}

// Decrement histcache refcount; iceberg evicts (calling hist_post_remove) at 0.
static inline void
rw_entry_histcache_remove(transactional_splinterdb *txn_kvsb, rw_entry *entry)
{
   if (!entry->hist_entry) {
      return;
   }
   entry->hist_entry = NULL;
   iceberg_remove(txn_kvsb->histcache, entry->key, platform_get_tid());
}

static rw_entry *
rw_entry_create()
{
   rw_entry *new_entry;
   new_entry = TYPED_ZALLOC(0, new_entry);
   platform_assert(new_entry != NULL);
   new_entry->tuple_ts  = NULL;
   new_entry->hist_entry = NULL;
   return new_entry;
}

static inline void
rw_entry_deinit(rw_entry *entry)
{
   if (!message_is_null(entry->msg)) {
      void *ptr = (void *)message_data(entry->msg);
      platform_free(0, ptr);
   }
}

static inline void
rw_entry_set_msg(rw_entry *e, message msg)
{
   char *msg_buf;
   msg_buf = TYPED_ARRAY_ZALLOC(0, msg_buf, message_length(msg));
   memcpy(msg_buf, message_data(msg), message_length(msg));
   e->msg = message_create(message_class(msg),
                           slice_create(message_length(msg), msg_buf));
}

static inline bool
rw_entry_is_read(const rw_entry *entry)
{
   return entry->is_read;
}

static inline bool
rw_entry_is_write(const rw_entry *entry)
{
   return !message_is_null(entry->msg);
}

static inline rw_entry *
rw_entry_get(transactional_splinterdb *txn_kvsb,
             transaction              *txn,
             slice                     user_key,
             const data_config        *cfg,
             const bool                is_read)
{
   bool      need_to_create_new_entry = TRUE;
   rw_entry *entry                    = NULL;
   const key ukey                     = key_create_from_slice(user_key);
   for (int i = 0; i < txn->num_rw_entries; ++i) {
      entry = txn->rw_entries[i];

      if (data_key_compare(cfg, ukey, key_create_from_slice(entry->key)) == 0) {
         need_to_create_new_entry = FALSE;
         break;
      }
   }

   if (need_to_create_new_entry) {
      entry                                  = rw_entry_create();
      entry->key                             = user_key;
      txn->rw_entries[txn->num_rw_entries++] = entry;
   }

   entry->is_read = entry->is_read || is_read;
   return entry;
}

static int
rw_entry_key_compare(const void *elem1, const void *elem2, void *args)
{
   const data_config *cfg = (const data_config *)args;
   rw_entry *e1 = *((rw_entry **)elem1);
   rw_entry *e2 = *((rw_entry **)elem2);
   key akey = key_create_from_slice(e1->key);
   key bkey = key_create_from_slice(e2->key);
   return data_key_compare(cfg, akey, bkey);
}

static inline bool
rw_entry_try_lock(rw_entry *entry)
{
   timestamp_set v1, v2;
   timestamp_set_load(entry->tuple_ts, &v1);
   v2 = v1;
   if (v1.lock_bit) {
      return false;
   }
   v2.lock_bit = 1;
   return timestamp_set_compare_and_swap(entry->tuple_ts, &v1, &v2);
}

static inline void
rw_entry_unlock(rw_entry *entry)
{
   timestamp_set v1, v2;
   do {
      timestamp_set_load(entry->tuple_ts, &v1);
      v2          = v1;
      v2.lock_bit = 0;
   } while (!timestamp_set_compare_and_swap(entry->tuple_ts, &v1, &v2));
}


static void
transactional_splinterdb_config_init(
   transactional_splinterdb_config *txn_splinterdb_cfg,
   const splinterdb_config         *kvsb_cfg)
{
   memcpy(&txn_splinterdb_cfg->kvsb_cfg,
          kvsb_cfg,
          sizeof(txn_splinterdb_cfg->kvsb_cfg));

   iceberg_config_default_init(&txn_splinterdb_cfg->iceberght_config);
   txn_splinterdb_cfg->iceberght_config.log_slots = 28;

   iceberg_config_default_init(&txn_splinterdb_cfg->histcache_config);
   txn_splinterdb_cfg->histcache_config.log_slots  = 28;
   txn_splinterdb_cfg->histcache_config.post_remove = hist_post_remove;

   txn_splinterdb_cfg->isol_level = TRANSACTION_ISOLATION_LEVEL_SERIALIZABLE;
   txn_splinterdb_cfg->is_upsert_disabled = FALSE;
}

static int
transactional_splinterdb_create_or_open(const splinterdb_config   *kvsb_cfg,
                                        transactional_splinterdb **txn_kvsb,
                                        bool open_existing)
{
   check_experimental_mode_is_valid();
   print_current_experimental_modes();

   transactional_splinterdb_config *txn_splinterdb_cfg;
   txn_splinterdb_cfg = TYPED_ZALLOC(0, txn_splinterdb_cfg);
   transactional_splinterdb_config_init(txn_splinterdb_cfg, kvsb_cfg);

   transactional_splinterdb *_txn_kvsb;
   _txn_kvsb       = TYPED_ZALLOC(0, _txn_kvsb);
   _txn_kvsb->tcfg = txn_splinterdb_cfg;

   int rc = splinterdb_create_or_open(
      &txn_splinterdb_cfg->kvsb_cfg, &_txn_kvsb->kvsb, open_existing);
   bool fail_to_create_splinterdb = (rc != 0);
   if (fail_to_create_splinterdb) {
      platform_free(0, _txn_kvsb);
      platform_free(0, txn_splinterdb_cfg);
      return rc;
   }

   iceberg_table *tscache = TYPED_ZALLOC(0, tscache);
   platform_assert(iceberg_init(tscache,
                                &txn_splinterdb_cfg->iceberght_config,
                                kvsb_cfg->data_cfg)
                   == 0);
   _txn_kvsb->tscache = tscache;

   iceberg_table *histcache = TYPED_ZALLOC(0, histcache);
   platform_assert(iceberg_init(histcache,
                                &txn_splinterdb_cfg->histcache_config,
                                kvsb_cfg->data_cfg)
                   == 0);
   _txn_kvsb->histcache = histcache;

   *txn_kvsb = _txn_kvsb;

   return 0;
}

int
transactional_splinterdb_create(const splinterdb_config   *kvsb_cfg,
                                transactional_splinterdb **txn_kvsb)
{
   return transactional_splinterdb_create_or_open(kvsb_cfg, txn_kvsb, FALSE);
}


int
transactional_splinterdb_open(const splinterdb_config   *kvsb_cfg,
                              transactional_splinterdb **txn_kvsb)
{
   return transactional_splinterdb_create_or_open(kvsb_cfg, txn_kvsb, TRUE);
}

void
transactional_splinterdb_close(transactional_splinterdb **txn_kvsb)
{
   transactional_splinterdb *_txn_kvsb = *txn_kvsb;

   iceberg_print_state(_txn_kvsb->tscache);
   iceberg_print_state(_txn_kvsb->histcache);

   splinterdb_close(&_txn_kvsb->kvsb);

   platform_free(0, _txn_kvsb->tscache);
   platform_free(0, _txn_kvsb->histcache);
   platform_free(0, _txn_kvsb->tcfg);
   platform_free(0, _txn_kvsb);

   *txn_kvsb = NULL;
}

void
transactional_splinterdb_register_thread(transactional_splinterdb *kvs)
{
   splinterdb_register_thread(kvs->kvsb);

#if USE_TRANSACTION_STATS
   transaction_stats_init(&kvs->txn_stats, platform_get_tid());
#endif
}

void
transactional_splinterdb_deregister_thread(transactional_splinterdb *kvs)
{
#if USE_TRANSACTION_STATS
   transaction_stats_dump(&kvs->txn_stats, platform_get_tid());
   transaction_stats_deinit(&kvs->txn_stats, platform_get_tid());
#endif

   splinterdb_deregister_thread(kvs->kvsb);
}

int
transactional_splinterdb_begin(transactional_splinterdb *txn_kvsb,
                               transaction              *txn)
{
   platform_assert(txn);
   memset(txn, 0, sizeof(*txn));

#if USE_TRANSACTION_STATS
   transaction_stats_begin(&txn_kvsb->txn_stats, platform_get_tid());
#endif
   return 0;
}

static inline void
transaction_deinit(transactional_splinterdb *txn_kvsb, transaction *txn)
{
   for (int i = 0; i < txn->num_rw_entries; ++i) {
      rw_entry_histcache_remove(txn_kvsb, txn->rw_entries[i]);
      rw_entry_iceberg_remove(txn_kvsb, txn->rw_entries[i]);
      rw_entry_deinit(txn->rw_entries[i]);
      platform_free(0, txn->rw_entries[i]);
   }
}

int
transactional_splinterdb_commit(transactional_splinterdb *txn_kvsb,
                                transaction              *txn)
{

#if USE_TRANSACTION_STATS
   transaction_stats_commit_start(&txn_kvsb->txn_stats, platform_get_tid());
#endif

   txn_timestamp commit_ts = 0;

   int       num_reads                    = 0;
   int       num_writes                   = 0;
   rw_entry *read_set[RW_SET_SIZE_LIMIT]  = {0};
   rw_entry *write_set[RW_SET_SIZE_LIMIT] = {0};

   for (int i = 0; i < txn->num_rw_entries; i++) {
      rw_entry *entry = txn->rw_entries[i];
      if (rw_entry_is_write(entry)) {
         write_set[num_writes++] = entry;
      }

      if (rw_entry_is_read(entry)) {
         read_set[num_reads++] = entry;

         txn_timestamp wts = entry->wts;
         commit_ts         = MAX(commit_ts, wts);
      }
   }

   platform_sort_slow(write_set,
                      num_writes,
                      sizeof(rw_entry *),
                      rw_entry_key_compare,
                      (void *)txn_kvsb->tcfg->kvsb_cfg.data_cfg,
                      NULL);

RETRY_LOCK_WRITE_SET:
{
   for (int lock_num = 0; lock_num < num_writes; ++lock_num) {
      rw_entry *w = write_set[lock_num];
      if (!w->tuple_ts) {
         slice to_be_freed = w->key;
         rw_entry_iceberg_insert(txn_kvsb, w);
         void *ptr = (void *)slice_data(to_be_freed);
         platform_free(0, ptr);
      }
      // Ensure write-only entries have a histcache reference for recording.
      rw_entry_histcache_insert(txn_kvsb, w);

      if (!rw_entry_try_lock(w)) {
         for (int i = 0; i < lock_num; ++i) {
            rw_entry_unlock(write_set[i]);
         }
         platform_sleep_ns(1000);
         goto RETRY_LOCK_WRITE_SET;
      }
   }
}

   for (uint64 i = 0; i < num_writes; ++i) {
      commit_ts =
         MAX(commit_ts, timestamp_set_get_rts(write_set[i]->tuple_ts) + 1);
   }

   bool is_abort = FALSE;
   for (uint64 i = 0; !is_abort && i < num_reads; ++i) {
      rw_entry *r = read_set[i];
      platform_assert(rw_entry_is_read(r));

      if (r->rts < commit_ts) {
         bool          is_success;
         timestamp_set v1, v2;
         do {
            is_success = TRUE;
            timestamp_set_load(r->tuple_ts, &v1);
            v2 = v1;

            if (r->wts != v1.wts) {
               // wts has changed since we read this key
               if (v1.wts <= commit_ts) {
                  // Hard: conflicting write is inside our commit window
                  is_abort = TRUE;
               } else {
                  // Soft: write is beyond our window — check history
                  tictoc_hist_entry *hist = r->hist_entry;
                  if (hist == NULL) {
                     // No history available — conservative abort
                     is_abort = TRUE;
                  } else {
                     bool intermediate = false;
                     platform_mutex_lock(&hist->lock);
                     for (int h = 0; h < hist->count; h++) {
                        if (hist->wts_list[h] > r->wts
                            && hist->wts_list[h] <= commit_ts)
                        {
                           intermediate = true;
                           break;
                        }
                     }
                     platform_mutex_unlock(&hist->lock);
                     if (intermediate) {
                        is_abort = TRUE;
                     }
                     // else: no intermediate write — unnecessary abort avoided
                  }
               }
               break; // wts already changed; skip CAS retry
            }

            txn_timestamp rts = timestamp_set_get_rts(&v1);
            bool is_locked_by_another = rts <= commit_ts
                                        && r->tuple_ts->lock_bit
                                        && !rw_entry_is_write(r);
            if (is_locked_by_another) {
               is_abort = TRUE;
               break;
            }
            if (rts <= commit_ts) {
               txn_timestamp delta = commit_ts - v1.wts;
               txn_timestamp shift = delta - (delta & UINT64_MAX);
               platform_assert(shift == 0);
               v2.wts += shift;
               v2.delta = delta - shift;
               is_success =
                  timestamp_set_compare_and_swap(r->tuple_ts, &v1, &v2);
            }
         } while (!is_success);
      }
   }

   if (!is_abort) {
#if USE_TRANSACTION_STATS
      transaction_stats_write_start(&txn_kvsb->txn_stats, platform_get_tid());
#endif

      int rc = 0;

      for (uint64 i = 0; i < num_writes; ++i) {
         rw_entry *w = write_set[i];
         platform_assert(rw_entry_is_write(w));

#if EXPERIMENTAL_MODE_BYPASS_SPLINTERDB == 1
         if (0) {
#endif
            switch (message_class(w->msg)) {
               case MESSAGE_TYPE_INSERT:
                  rc = splinterdb_insert(
                     txn_kvsb->kvsb, w->key, message_slice(w->msg));
                  break;
               case MESSAGE_TYPE_UPDATE:
                  rc = splinterdb_update(
                     txn_kvsb->kvsb, w->key, message_slice(w->msg));
                  break;
               case MESSAGE_TYPE_DELETE:
                  rc = splinterdb_delete(txn_kvsb->kvsb, w->key);
                  break;
               default:
                  break;
            }

            platform_assert(rc == 0, "Error from SplinterDB: %d\n", rc);
#if EXPERIMENTAL_MODE_BYPASS_SPLINTERDB == 1
         }
#endif

         // Update wts to commit_ts and record this NEW wts in history.
         timestamp_set v1, v2;
         do {
            timestamp_set_load(w->tuple_ts, &v1);
            v2          = v1;
            v2.wts      = commit_ts;
            v2.delta    = 0;
            v2.lock_bit = 0;
         } while (!timestamp_set_compare_and_swap(w->tuple_ts, &v1, &v2));

         // Record new wts so other transactions can detect intermediate writes.
         tictoc_hist_entry *he = w->hist_entry;
         if (he) {
            platform_mutex_lock(&he->lock);
            if (he->count < EXT_HIST_MAX_WRITES) {
               he->wts_list[he->count++] = commit_ts; // NEW wts
            }
            platform_mutex_unlock(&he->lock);
         }
      }
   } else {
      for (uint64 i = 0; i < num_writes; ++i) {
         rw_entry_unlock(write_set[i]);
      }
   }

   transaction_deinit(txn_kvsb, txn);

#if USE_TRANSACTION_STATS
   if (is_abort) {
      transaction_stats_abort_end(&txn_kvsb->txn_stats, platform_get_tid());
   } else {
      transaction_stats_commit_end(&txn_kvsb->txn_stats, platform_get_tid());
   }
#endif

   return (-1 * is_abort);
}

int
transactional_splinterdb_abort(transactional_splinterdb *txn_kvsb,
                               transaction              *txn)
{
   transaction_deinit(txn_kvsb, txn);

   return 0;
}

static int
local_write(transactional_splinterdb *txn_kvsb,
            transaction              *txn,
            slice                     user_key,
            message                   msg)
{
   const data_config *cfg = txn_kvsb->tcfg->kvsb_cfg.data_cfg;
   char *user_key_copy;
   user_key_copy = TYPED_ARRAY_ZALLOC(0, user_key_copy, slice_length(user_key));
   rw_entry *entry = rw_entry_get(
      txn_kvsb, txn, slice_copy_contents(user_key_copy, user_key), cfg, FALSE);

   if (message_is_null(entry->msg)) {
      rw_entry_set_msg(entry, msg);
   } else {
      key       wkey = key_create_from_slice(entry->key);
      const key ukey = key_create_from_slice(user_key);
      if (data_key_compare(cfg, wkey, ukey) == 0) {
         if (message_is_definitive(msg)) {
            void *ptr = (void *)message_data(entry->msg);
            platform_free(0, ptr);
            rw_entry_set_msg(entry, msg);
         } else {
            platform_assert(message_class(entry->msg) != MESSAGE_TYPE_DELETE);

            merge_accumulator new_message;
            merge_accumulator_init_from_message(&new_message, 0, msg);
            data_merge_tuples(cfg, ukey, entry->msg, &new_message);
            void *ptr = (void *)message_data(entry->msg);
            platform_free(0, ptr);
            entry->msg = merge_accumulator_to_message(&new_message);
         }
      }
   }
   return 0;
}

int
transactional_splinterdb_insert(transactional_splinterdb *txn_kvsb,
                                transaction              *txn,
                                slice                     user_key,
                                slice                     value)
{
   if (!txn) {
      return splinterdb_insert(txn_kvsb->kvsb, user_key, value);
   }
   return local_write(
      txn_kvsb, txn, user_key, message_create(MESSAGE_TYPE_INSERT, value));
}

int
transactional_splinterdb_delete(transactional_splinterdb *txn_kvsb,
                                transaction              *txn,
                                slice                     user_key)
{
   return local_write(txn_kvsb, txn, user_key, DELETE_MESSAGE);
}

int
transactional_splinterdb_update(transactional_splinterdb *txn_kvsb,
                                transaction              *txn,
                                slice                     user_key,
                                slice                     delta)
{
   message_type msg_type = txn_kvsb->tcfg->is_upsert_disabled
                              ? MESSAGE_TYPE_INSERT
                              : MESSAGE_TYPE_UPDATE;
   return local_write(txn_kvsb, txn, user_key, message_create(msg_type, delta));
}

int
transactional_splinterdb_lookup(transactional_splinterdb *txn_kvsb,
                                transaction              *txn,
                                slice                     user_key,
                                splinterdb_lookup_result *result)
{
   const data_config *cfg   = txn_kvsb->tcfg->kvsb_cfg.data_cfg;
   rw_entry          *entry = rw_entry_get(txn_kvsb, txn, user_key, cfg, TRUE);

   int rc = 0;

   rw_entry_iceberg_insert(txn_kvsb, entry);
   rw_entry_histcache_insert(txn_kvsb, entry);

   timestamp_set v1;
   do {
      timestamp_set_load(entry->tuple_ts, &v1);
      if (v1.lock_bit) {
         continue;
      }

#if EXPERIMENTAL_MODE_BYPASS_SPLINTERDB == 0
      if (rw_entry_is_write(entry)) {
         _splinterdb_lookup_result *_result =
            (_splinterdb_lookup_result *)result;
         merge_accumulator_resize(&_result->value, message_length(entry->msg));
         memcpy(merge_accumulator_data(&_result->value),
                message_data(entry->msg),
                message_length(entry->msg));
      } else {
         rc = splinterdb_lookup(txn_kvsb->kvsb, entry->key, result);
      }
#endif
   } while (!timestamp_set_compare_and_swap(entry->tuple_ts, &v1, &v1));

   entry->wts = v1.wts;
   entry->rts = timestamp_set_get_rts(&v1);

   return rc;
}
