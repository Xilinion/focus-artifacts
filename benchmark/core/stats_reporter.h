#pragma once

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <numeric>
#include <vector>
#include <fstream>
#include <unordered_map>
#include <unistd.h>
#include "benchmark_structs.h"

namespace ycsbc {

struct IOStats {
   long long read_bytes  = 0;
   long long write_bytes = 0;
};

static IOStats getIOStats() {
   IOStats ioStats;
   pid_t pid = getpid();
   std::string ioFilePath = "/proc/" + std::to_string(pid) + "/io";

   std::ifstream ioFile(ioFilePath);
   if (!ioFile.is_open()) {
      std::cerr << "Failed to open " << ioFilePath << std::endl;
      return ioStats;
   }

   std::string line;
   while (std::getline(ioFile, line)) {
      if (line.find("read_bytes:") == 0) {
         ioStats.read_bytes = std::stoll(line.substr(line.find(":") + 1));
      } else if (line.find("write_bytes:") == 0) {
         ioStats.write_bytes = std::stoll(line.substr(line.find(":") + 1));
      }
   }

   ioFile.close();
   return ioStats;
}

template<typename T>
void PrintDistribution(std::vector<T> &data, std::ostream &out = std::cout)
{
   if (data.empty()) {
      return;
   }

   out << "Min: " << data.front() << std::endl;
   out << "Max: " << data.back() << std::endl;
   out << "Avg: "
       << std::accumulate(data.begin(), data.end(), 0.0) / data.size()
       << std::endl;
   out << "P50: " << data[data.size() / 2] << std::endl;
   out << "P90: " << data[data.size() * 9 / 10] << std::endl;
   out << "P95: " << data[data.size() * 95 / 100] << std::endl;
   out << "P99: " << data[data.size() * 99 / 100] << std::endl;
   out << "P99.9: " << data[data.size() * 999 / 1000] << std::endl;
}

template<typename T>
void PrintHistogram(std::vector<T> &data, std::ostream &out = std::cout)
{
   if (data.empty()) {
      return;
   }
   
   std::unordered_map<T, size_t> histo;
   for (auto value : data) {
       histo[value]++;
   }

   for (auto value_cnt : histo) {
      out << value_cnt.first << ": " << value_cnt.second << std::endl;
   }
}


static void PrintYCSBStats(const std::vector<YCSBOutput> &outputs,
                          uint64_t total_txn_count,
                          double duration,
                          bool is_long_txn_enabled = false)
{
   std::cout << "# Number of client threads:\t" << outputs.size() << std::endl;
   
   uint64_t total_commit_cnt = 0;
   uint64_t total_abort_cnt = 0;

   for (size_t i = 0; i < outputs.size(); ++i) {
      std::cout << "[Client " << i << "] commit_cnt: "
                << outputs[i].commit_cnt + outputs[i].long_txn_commit_cnt
                << ", abort_cnt: "
                << outputs[i].abort_cnt + outputs[i].long_txn_abort_cnt
                << std::endl;
      total_commit_cnt += outputs[i].commit_cnt + outputs[i].long_txn_commit_cnt;
      total_abort_cnt += outputs[i].abort_cnt + outputs[i].long_txn_abort_cnt;
   }

   std::cout << "# Transaction count:\t" << total_txn_count << std::endl;
   std::cout << "# Committed Transaction count:\t" << total_commit_cnt << std::endl;
   std::cout << "# Aborted Transaction count:\t"
             << total_txn_count - total_commit_cnt << std::endl;
   std::cout << "# Transaction throughput (KTPS)\t";
   std::cout << total_commit_cnt / duration / 1000 << std::endl;
   std::cout << "Run duration (sec):\t" << duration << std::endl;
   std::cout << "# Abort count:\t" << total_abort_cnt << '\n';
   std::cout << "Abort rate:\t"
             << (double)total_abort_cnt / (total_abort_cnt + total_commit_cnt)
             << "\n";

   std::vector<double> total_commit_txn_latencies;
   std::vector<double> total_abort_txn_latencies;
   std::vector<unsigned long> total_abort_cnt_per_txn;

   for (const auto &output : outputs) {
      total_commit_txn_latencies.insert(
         total_commit_txn_latencies.end(),
         output.commit_txn_latencies.begin(),
         output.commit_txn_latencies.end());
      total_abort_txn_latencies.insert(
         total_abort_txn_latencies.end(),
         output.abort_txn_latencies.begin(),
         output.abort_txn_latencies.end());
      total_abort_cnt_per_txn.insert(
         total_abort_cnt_per_txn.end(),
         output.abort_cnt_per_txn.begin(),
         output.abort_cnt_per_txn.end());

      if (is_long_txn_enabled) {
         total_commit_txn_latencies.insert(
            total_commit_txn_latencies.end(),
            output.long_txn_commit_txn_latencies.begin(),
            output.long_txn_commit_txn_latencies.end());
         total_abort_txn_latencies.insert(
            total_abort_txn_latencies.end(),
            output.long_txn_abort_txn_latencies.begin(),
            output.long_txn_abort_txn_latencies.end());
         total_abort_cnt_per_txn.insert(
            total_abort_cnt_per_txn.end(),
            output.long_txn_abort_cnt_per_txn.begin(),
            output.long_txn_abort_cnt_per_txn.end());
      }
   }

   std::sort(total_commit_txn_latencies.begin(), total_commit_txn_latencies.end());
   std::sort(total_abort_txn_latencies.begin(), total_abort_txn_latencies.end());
   std::sort(total_abort_cnt_per_txn.begin(), total_abort_cnt_per_txn.end());

   std::cout << "# Commit Latencies (us)" << std::endl;
   PrintDistribution<double>(total_commit_txn_latencies);
   std::cout << "# Abort Latencies (us)" << std::endl;
   PrintDistribution<double>(total_abort_txn_latencies);
   std::cout << "# Abort count per transaction" << std::endl;
   PrintDistribution<unsigned long>(total_abort_cnt_per_txn);
   std::cout << "# Print retries histogram" << std::endl;
   PrintHistogram<unsigned long>(total_abort_cnt_per_txn);

   if (is_long_txn_enabled) {
      std::cout << "# Long Transaction Stats" << std::endl;
      uint64_t total_long_txn_cnt = 0;
      uint64_t total_long_commit_cnt = 0;
      uint64_t total_long_abort_cnt = 0;

      std::vector<double> total_long_commit_txn_latencies;
      std::vector<double> total_long_abort_txn_latencies;

      for (const auto &output : outputs) {
         total_long_txn_cnt += output.long_txn_cnt;
         total_long_commit_cnt += output.long_txn_commit_cnt;
         total_long_abort_cnt += output.long_txn_abort_cnt;

         total_long_commit_txn_latencies.insert(
            total_long_commit_txn_latencies.end(),
            output.long_txn_commit_txn_latencies.begin(),
            output.long_txn_commit_txn_latencies.end());
         total_long_abort_txn_latencies.insert(
            total_long_abort_txn_latencies.end(),
            output.long_txn_abort_txn_latencies.begin(),
            output.long_txn_abort_txn_latencies.end());
      }

      std::cout << "# Long Transaction count:\t" << total_long_txn_cnt << std::endl;
      std::cout << "# Committed Long Transaction count:\t" << total_long_commit_cnt << std::endl;
      std::cout << "# Aborted Long Transaction count:\t"
                << total_long_txn_cnt - total_long_commit_cnt << std::endl;
      std::cout << "# Long Transaction abort rate:\t\t"
                << (double)total_long_abort_cnt / (total_long_abort_cnt + total_long_commit_cnt)
                << std::endl;
      std::cout << "# Long Transaction abort portion (%):\t"
                << (double)total_long_abort_cnt / total_abort_cnt * 100
                << std::endl;

      std::sort(total_long_commit_txn_latencies.begin(), total_long_commit_txn_latencies.end());
      std::sort(total_long_abort_txn_latencies.begin(), total_long_abort_txn_latencies.end());

      std::cout << "# Long Transaction Commit Latencies (us)" << std::endl;
      PrintDistribution<double>(total_long_commit_txn_latencies);
      std::cout << "# Long Transaction Abort Latencies (us)" << std::endl;
      PrintDistribution<double>(total_long_abort_txn_latencies);
   }
}

static void PrintTPCCStats(const std::vector<TPCCOutput> &outputs,
                          double duration)
{
   std::cout << "# Number of client threads:\t" << outputs.size() << std::endl;
   
   uint64_t total_committed_cnt = 0;
   uint64_t total_aborted_cnt = 0;
   uint64_t total_aborted_cnt_payment = 0;
   uint64_t total_aborted_cnt_new_order = 0;
   uint64_t total_attempts_payment = 0;
   uint64_t total_attempts_new_order = 0;

   for (size_t i = 0; i < outputs.size(); ++i) {
      std::cout << "[Client " << i << "] commit_cnt: " << outputs[i].commit_cnt
                << ", abort_cnt: " << outputs[i].abort_cnt << std::endl;
      total_committed_cnt += outputs[i].commit_cnt;
      total_aborted_cnt += outputs[i].abort_cnt;
      total_aborted_cnt_payment += outputs[i].abort_cnt_payment;
      total_aborted_cnt_new_order += outputs[i].abort_cnt_new_order;
      total_attempts_payment += outputs[i].attempts_payment;
      total_attempts_new_order += outputs[i].attempts_new_order;
   }

   std::cout << "# Transaction throughput (KTPS)\t";
   std::cout << total_committed_cnt / duration / 1000 << std::endl;
   std::cout << "Run duration (sec):\t" << duration << std::endl;

   std::cout << "# Abort count:\t" << total_aborted_cnt << '\n';
   std::cout << "Abort rate:\t"
             << (double)total_aborted_cnt / (total_aborted_cnt + total_committed_cnt)
             << "\n";

   if (total_aborted_cnt > 0) {
      std::cout << "# (Payment) Abort rate(%):\t"
                << total_aborted_cnt_payment * 100.0 / total_aborted_cnt
                << '\n';
      std::cout << "# (NewOrder) Abort rate(%):\t"
                << total_aborted_cnt_new_order * 100.0 / total_aborted_cnt
                << '\n';
   } else {
      std::cout << "# (Payment) Abort rate(%):\t0\n";
      std::cout << "# (NewOrder) Abort rate(%):\t0\n";
   }

   std::cout << "# (Payment) Failure rate(%):\t"
             << total_aborted_cnt_payment * 100.0 / total_attempts_payment
             << '\n';
   std::cout << "# (NewOrder) Failure rate(%):\t"
             << total_aborted_cnt_new_order * 100.0 / total_attempts_new_order
             << '\n';

   std::cout << "# (Payment) Total attempts:\t" << total_attempts_payment
             << '\n';
   std::cout << "# (NewOrder) Total attempts:\t" << total_attempts_new_order
             << '\n';

   std::vector<double> total_commit_txn_latencies;
   std::vector<double> total_abort_txn_latencies;

   for (const auto &output : outputs) {
      total_commit_txn_latencies.insert(
         total_commit_txn_latencies.end(),
         output.commit_txn_latencies.begin(),
         output.commit_txn_latencies.end());
      total_abort_txn_latencies.insert(
         total_abort_txn_latencies.end(),
         output.abort_txn_latencies.begin(),
         output.abort_txn_latencies.end());
   }

   std::sort(total_commit_txn_latencies.begin(), total_commit_txn_latencies.end());
   std::sort(total_abort_txn_latencies.begin(), total_abort_txn_latencies.end());

   std::cout << "# Commit Latencies (us)" << std::endl;
   PrintDistribution<double>(total_commit_txn_latencies);
   std::cout << "# Abort Latencies (us)" << std::endl;
   PrintDistribution<double>(total_abort_txn_latencies);
}

static void PrintIOStats(const IOStats &begin_stats,
                        const IOStats &end_stats,
                        double duration,
                        const char *phase = "")
{
   long long read_bytes = end_stats.read_bytes - begin_stats.read_bytes;
   long long write_bytes = end_stats.write_bytes - begin_stats.write_bytes;
   std::cout << "[" << phase << " phase IO stats]\t read_bytes: " << read_bytes
             << ", write_bytes: " << write_bytes << " (Throughput (B/s): "
             << (read_bytes + write_bytes) / duration << ")" << std::endl;
}

} // namespace ycsbc 
