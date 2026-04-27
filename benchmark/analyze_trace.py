#!/usr/bin/env python3
"""
TicToc abort trace analyzer.

Abort TSV: txn_seq, key_hash, loc_wts, cur_wts, commit_ts, ats_val, is_hard
Write TSV: txn_seq, key_hash, commit_ts, ats_val  (commit_ts here is the new_wts)

Categorization:
  A soft abort (is_hard=0) entry is NECESSARY if there exists a write w such that:
    w.key_hash == a.key_hash
    AND a.loc_wts < w.new_wts <= a.commit_ts
    AND w.ats_at_write < a.ats_at_abort
  Otherwise it is UNNECESSARY.

A transaction (txn_seq, thread) is:
  HARD if any entry is hard.
  SOFT-NECESSARY if no entry is hard AND at least one soft entry is necessary.
  UNNECESSARY if all entries are soft AND none is necessary.
"""

import glob
import sys
import os
from collections import defaultdict

TRACE_DIR = "trace_output"

def load_aborts():
    rows = []
    for f in sorted(glob.glob(f"{TRACE_DIR}/aborts_*.tsv")):
        thr = int(f.split("aborts_")[1].split(".tsv")[0])
        with open(f) as fh:
            for line in fh:
                p = line.rstrip().split('\t')
                if len(p) != 7:
                    continue
                rows.append((
                    thr,
                    int(p[0]),   # txn_seq
                    int(p[1]),   # key_hash
                    int(p[2]),   # loc_wts
                    int(p[3]),   # cur_wts
                    int(p[4]),   # commit_ts
                    int(p[5]),   # ats_at_abort
                    int(p[6]),   # is_hard
                ))
    return rows

def load_writes():
    # Returns dict: key_hash -> sorted list of (new_wts, ats_at_write)
    by_key = defaultdict(list)
    for f in sorted(glob.glob(f"{TRACE_DIR}/writes_*.tsv")):
        with open(f) as fh:
            for line in fh:
                p = line.rstrip().split('\t')
                if len(p) != 4:
                    continue
                key_hash    = int(p[1])
                new_wts     = int(p[2])  # commit_ts = the new wts applied
                ats_at_write = int(p[3])
                by_key[key_hash].append((new_wts, ats_at_write))
    # Sort each list by new_wts for bisect use
    for kh in by_key:
        by_key[kh].sort()
    return by_key

def has_intermediate_write(writes_by_key, key_hash, loc_wts, commit_ts, ats_at_abort):
    """Return True if there is a write w with loc_wts < w.new_wts <= commit_ts and w.ats < ats_at_abort."""
    wlist = writes_by_key.get(key_hash)
    if not wlist:
        return False
    # Binary search: find first new_wts > loc_wts
    lo, hi = 0, len(wlist)
    while lo < hi:
        mid = (lo + hi) // 2
        if wlist[mid][0] <= loc_wts:
            lo = mid + 1
        else:
            hi = mid
    # lo is first index with new_wts > loc_wts
    while lo < len(wlist):
        new_wts, ats_w = wlist[lo]
        if new_wts > commit_ts:
            break
        if ats_w < ats_at_abort:
            return True
        lo += 1
    return False

def analyze(aborts, writes_by_key, label="memory"):
    # Group abort entries by (thr, txn_seq)
    txn_entries = defaultdict(list)
    for row in aborts:
        thr, txn_seq = row[0], row[1]
        txn_entries[(thr, txn_seq)].append(row)

    # Classify each abort entry
    entry_hard         = 0
    entry_soft_nec     = 0
    entry_soft_unnec   = 0

    # Classify each transaction
    txn_hard           = 0
    txn_soft_nec       = 0
    txn_soft_unnec     = 0

    for (thr, txn_seq), entries in txn_entries.items():
        has_hard      = any(e[7] for e in entries)
        has_soft_nec  = False
        n_hard        = sum(1 for e in entries if e[7])
        n_soft_nec    = 0
        n_soft_unnec  = 0

        for e in entries:
            thr, txn_seq, key_hash, loc_wts, cur_wts, commit_ts, ats_at_abort, is_hard = e
            if is_hard:
                entry_hard += 1
            else:
                # Soft: check for intermediate write
                if has_intermediate_write(writes_by_key, key_hash, loc_wts, commit_ts, ats_at_abort):
                    entry_soft_nec += 1
                    has_soft_nec    = True
                    n_soft_nec += 1
                else:
                    entry_soft_unnec += 1
                    n_soft_unnec += 1

        if has_hard:
            txn_hard += 1
        elif has_soft_nec:
            txn_soft_nec += 1
        else:
            txn_soft_unnec += 1

    total_entries = len(aborts)
    total_txns    = len(txn_entries)

    out = []
    out.append(f"=== TicToc Abort Analysis [{label}] ===")
    out.append(f"Total abort transactions         : {total_txns:>10,}")
    out.append(f"  Hard-abort txns                : {txn_hard:>10,}  ({100*txn_hard/total_txns:.1f}%)")
    out.append(f"  Soft-necessary txns            : {txn_soft_nec:>10,}  ({100*txn_soft_nec/total_txns:.1f}%)")
    out.append(f"  Soft-unnecessary txns          : {txn_soft_unnec:>10,}  ({100*txn_soft_unnec/total_txns:.1f}%)")
    out.append("")
    out.append(f"Total abort-read entries logged  : {total_entries:>10,}")
    out.append(f"  Hard entries                   : {entry_hard:>10,}  ({100*entry_hard/total_entries:.1f}%)")
    out.append(f"  Soft-necessary entries         : {entry_soft_nec:>10,}  ({100*entry_soft_nec/total_entries:.1f}%)")
    out.append(f"  Soft-unnecessary entries       : {entry_soft_unnec:>10,}  ({100*entry_soft_unnec/total_entries:.1f}%)")
    out.append("")
    out.append(f"Avoidable fraction (txn level)   : {100*txn_soft_unnec/total_txns:.1f}%")
    out.append(f"Avoidable fraction (entry level) : {100*entry_soft_unnec/total_entries:.1f}%")

    text = "\n".join(out)
    print(text)

    summary_path = os.path.join(TRACE_DIR, f"summary_{label}.txt")
    with open(summary_path, "w") as f:
        f.write(text + "\n")
    print(f"\nSummary written to {summary_path}")

    return {
        'total_txns': total_txns,
        'txn_hard': txn_hard,
        'txn_soft_nec': txn_soft_nec,
        'txn_soft_unnec': txn_soft_unnec,
        'total_entries': total_entries,
        'entry_hard': entry_hard,
        'entry_soft_nec': entry_soft_nec,
        'entry_soft_unnec': entry_soft_unnec,
    }


if __name__ == '__main__':
    label = "memory"
    for i, arg in enumerate(sys.argv):
        if arg == "--variant" and i+1 < len(sys.argv):
            label = sys.argv[i+1]
        if arg == "--output-dir" and i+1 < len(sys.argv):
            TRACE_DIR = sys.argv[i+1]

    print("Loading abort traces...", end=' ', flush=True)
    aborts = load_aborts()
    print(f"{len(aborts):,} entries")

    print("Loading write traces...", end=' ', flush=True)
    writes_by_key = load_writes()
    print(f"keys with writes: {len(writes_by_key):,}")
    print()

    analyze(aborts, writes_by_key, label=label)
