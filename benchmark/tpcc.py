#!/usr/bin/python3

import os
import sys
import getopt
from exp_system import *

def printHelp():
    print("Usage:", sys.argv[0], "-s [system] -w [workload] -t [threads] -d [dbfile] -b -c [cache_size_mb] -r [run_seconds] -h", file=sys.stderr)
    print("\t-s,--system [system]: Choose one of the followings --",
          available_systems, file=sys.stderr)
    print("\t-w,--workload [workload]: Specify a spec file in workloads", file=sys.stderr)
    print("\t-t,--threads [threads]: The number of threads (default: 1)", file=sys.stderr)
    print("\t-d,--dbfile [dbfile]: Choose the dbfile for SplinterDB (default: /dev/md0)", file=sys.stderr)
    print("\t-b,--bgthreads: Enable background threads", file=sys.stderr)
    print("\t-c,--cachesize: Set the cache size in MB (default: 4096)", file=sys.stderr)
    print("\t-r,--run_seconds: Set the run time in seconds (default: 0, which means disabled)", file=sys.stderr)
    print("\t-h,--help: Print this help message", file=sys.stderr)
    exit(1)


def get_device_size_bytes(device: str) -> int:
    import subprocess
    output = subprocess.run(
        ["lsblk", device, "--output", "SIZE", "--bytes", "--noheadings", "--nodeps"],
        capture_output=True,
        check=True,
    )
    size = int(output.stdout.decode())
    return size


def main(argc, argv):
    enable_bgthreads = False
    cache_size_mb = 256
    run_seconds = 0

    opts, _ = getopt.getopt(sys.argv[1:], 's:w:t:d:bc:r:h', 
                            ['system=', 'workload=', 'threads=', 'dbfile=', 'bgthreads', 'cachesize=', 'run_seconds=', 'help'])
    system = None
    conf = None
    dev_name = '/dev/md0'

    for opt, arg in opts:
        if opt in ('-s', '--system'):
            system = arg
            if system not in available_systems:
                printHelp()
        elif opt in ('-w', '--workload'):
            conf = arg
            spec_file = 'workloads/' + conf + '.spec'
            if not os.path.isfile(spec_file):
                print(f'Workload {conf} does not exist.', file=sys.stderr)
                exit(1)
        elif opt in ('-t', '--threads'):
            threads = int(arg)
        elif opt in ('-d', '--dbfile'):
            dev_name = arg
            if not os.path.exists(dev_name):
                print(f'Dbfile {dev_name} does not exist.', file=sys.stderr)
                exit(1)
        elif opt in ('-b', '--bgthreads'):
            enable_bgthreads = True
        elif opt in ('-c', '--cachesize'):
            cache_size_mb = int(arg)
        elif opt in ('-r', '--run_seconds'):
            run_seconds = float(arg)
        elif opt in ('-h', '--help'):
            printHelp()

    if not system:
        print("Invalid system", file=sys.stderr)
        printHelp()

    if not conf or not os.path.isfile(spec_file):
        print("Invalid workload", file=sys.stderr)
        printHelp()

    splinterdb_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), '../splinterdb')
    if not os.path.exists(splinterdb_dir):
        print(f'{splinterdb_dir} does not exist.', file=sys.stderr)
        exit(1)
    ExpSystem.build(system, splinterdb_dir, spl_threads=threads+2, backup=False)

    db = 'splinterdb' if system == 'splinterdb' else 'transactional_splinterdb'
    
    max_total_threads = 36

    # This is the maximum number of threads that run YCSB clients.
    max_num_threads = min(os.cpu_count(), max_total_threads)

    if enable_bgthreads:
        assert False, "not used"
        num_normal_bg_threads = threads
        num_memtable_bg_threads = (threads + 9) // 10

        total_num_threads = threads + num_normal_bg_threads + num_memtable_bg_threads
        if total_num_threads > max_total_threads:
            num_normal_bg_threads = max(0, num_normal_bg_threads - (total_num_threads - max_total_threads))
        
        total_num_threads = threads + num_normal_bg_threads + num_memtable_bg_threads
        if total_num_threads > max_total_threads:
            num_memtable_bg_threads = max(0, num_memtable_bg_threads - (total_num_threads - max_total_threads))
    else:
        num_normal_bg_threads = 0
        num_memtable_bg_threads = 0

    cmd = f'LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so \
        ./ycsbc -db {db} -threads {threads} -benchmark_seconds {run_seconds} -client txn -benchmark tpcc \
        -W {spec_file} \
        -p splinterdb.filename {dev_name} \
        -p splinterdb.cache_size_mb {cache_size_mb} \
        -p splinterdb.num_normal_bg_threads {num_normal_bg_threads} \
        -p splinterdb.num_memtable_bg_threads {num_memtable_bg_threads} \
        -p splinterdb.io_contexts_per_process 64'

    if dev_name.startswith('/dev/'):
        cmd += f' -p splinterdb.disk_size_gb {(get_device_size_bytes(dev_name) // (1024**3))}'

    backofftime = {
        '/dev/nvme0n1': {
            120: {
                'tpcc-wh4': {
                    'sto-disk': 4000,
                    'sto-disk-cache': 4000,
                    'tictoc-disk': 4000,
                    'tictoc-disk-cache': 4000,
                    'mvcc-disk': 8000,
                    'mvcc-disk-cache': 5000,
                },
            }
        },
        '/dev/sda4': {
            120: {
                'tpcc-wh4': {
                    '2pl-no-wait': 2850,
                    'occ-serial': 2200,
                    'sto-memory': 4000,
                    'sto-counter-lazy': 4000,
                    'sto-sketch': 4000,
                    'sto-disk': 6000,
                    'sto-disk-cache': 5300,
                    'tictoc-memory': 5500,
                    'tictoc-counter-lazy': 5500,
                    'tictoc-sketch': 5500,
                    'tictoc-disk': 6500,
                    'tictoc-disk-cache': 5300,
                    'mvcc-memory': 4000,
                    'mvcc-couter-lazy': 4000,
                    'mvcc-sketch': 4000,
                    'mvcc-disk': 70000,
                    'mvcc-disk-cache': 5000,
                },
                'tpcc-wh8': {
                    '2pl-no-wait': 3200,
                    'occ-serial': 2100,
                    'sto-memory': 6500,
                    'sto-counter-lazy': 6500,
                    'sto-sketch': 6500,
                    'sto-disk': 7000,
                    'sto-disk-cache': 6500,
                    'tictoc-memory': 7500,
                    'tictoc-counter-lazy': 7500,
                    'tictoc-sketch': 7500,
                    'tictoc-disk': 8500,
                    'tictoc-disk-cache': 7500,
                    'mvcc-memory': 6000,
                    'mvcc-couter-lazy': 6000,
                    'mvcc-sketch': 6000,
                    'mvcc-disk': 140000,
                    'mvcc-disk-cache': 7000,
                },
                'tpcc-wh16': {
                    '2pl-no-wait': 3200,
                    'occ-serial': 2100,
                    'sto-memory': 6500,
                    'sto-counter-lazy': 6500,
                    'sto-sketch': 6500,
                    'sto-disk': 7000,
                    'sto-disk-cache': 6500,
                    'tictoc-memory': 7500,
                    'tictoc-counter-lazy': 7500,
                    'tictoc-sketch': 7500,
                    'tictoc-disk': 8500,
                    'tictoc-disk-cache': 7500,
                    'mvcc-memory': 6000,
                    'mvcc-couter-lazy': 6000,
                    'mvcc-sketch': 6000,
                    'mvcc-disk': 140000,
                    'mvcc-disk-cache': 7000,
                },
                'tpcc-wh32': {
                    '2pl-no-wait': 3200,
                    'occ-serial': 2100,
                    'sto-memory': 6500,
                    'sto-counter-lazy': 6500,
                    'sto-sketch': 6500,
                    'sto-disk': 7000,
                    'sto-disk-cache': 6500,
                    'tictoc-memory': 7500,
                    'tictoc-counter-lazy': 7500,
                    'tictoc-sketch': 7500,
                    'tictoc-disk': 8500,
                    'tictoc-disk-cache': 7500,
                    'mvcc-memory': 6000,
                    'mvcc-couter-lazy': 6000,
                    'mvcc-sketch': 6000,
                    'mvcc-disk': 140000,
                    'mvcc-disk-cache': 7000,
                },
            }
        }
    }
    try:
        abort_penalty_us = backofftime[dev_name][threads][conf][system]
    except KeyError:
        abort_penalty_us = 2000
    cmd += f' -w abort_penalty_us {abort_penalty_us}'

    print(cmd)
    os.system(cmd)
    
if __name__ == '__main__':
    main(len(sys.argv), sys.argv)
