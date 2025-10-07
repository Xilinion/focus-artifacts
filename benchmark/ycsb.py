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
    cache_size_mb = 4096
    run_seconds = 0
    ycsbc_options = ''

    opts, _ = getopt.getopt(sys.argv[1:], 's:w:t:d:bc:r:o:gh', 
                            ['system=', 'workload=', 'threads=', 'dbfile=', 'bgthreads', 'cachesize=', 'run_seconds=', 'ycsbc_options=', 'gdb', 'help'])
    system = None
    conf = None
    dev_name = '/dev/md0'
    gdb_cmd = ''

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
        elif opt in ('-o', '--ycsbc_options'):
            ycsbc_options = arg
        elif opt in ('-g', '--gdb'):
            gdb_cmd = 'gdb -ex=r --args'
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
    if conf == "long_txn":
        ExpSystem.build_for_long_txn(system, splinterdb_dir, spl_threads=threads+2, backup=False)
    else:
        ExpSystem.build(system, splinterdb_dir, spl_threads=threads+2, backup=False)

    db = 'splinterdb' if system == 'splinterdb' else 'transactional_splinterdb'
    
    max_total_threads = 36

    # This is the maximum number of threads that run YCSB clients.
    cpu_count = os.cpu_count() or 1
    max_num_threads = min(cpu_count, max_total_threads)

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
        {gdb_cmd} ./ycsbc -db {db} -threads {threads} -benchmark_seconds {run_seconds} -client txn \
        -L {spec_file} -W {spec_file} \
        -p splinterdb.filename {dev_name} \
        -p splinterdb.cache_size_mb {cache_size_mb} \
        -p splinterdb.num_normal_bg_threads {num_normal_bg_threads} \
        -p splinterdb.num_memtable_bg_threads {num_memtable_bg_threads} \
        -p splinterdb.disable_upsert 1 \
        -p splinterdb.io_contexts_per_process 128'
        
    if dev_name.startswith('/dev/'):
        cmd += f' -p splinterdb.disk_size_gb {get_device_size_bytes(dev_name) // (1024**3)}'
    # cmd += ' -p splinterdb.cache_use_stats 1 -p splinterdb.use_stats 1'

    cmd += ' -p splinterdb.use_log 0'

    backofftime = {
        '/dev/md127': {
            60: {
                'read': {
                    'default': 20000,
                    'tictoc-disk': 20000,
                    'tictoc-disk-cache': 20000,
                    'mvcc-disk': 1500000
                },
                'write': {
                    'default': 5000,
                    'sto-disk': 10000,
                    'sto-disk-cache': 10000,
                    'tictoc-disk': 20000,
                    'tictoc-disk-cache': 20000,
                    'mvcc-disk': 1500000
                },
                'mixed': {
                    'default': 5000,
                    'mvcc-disk': 630000
                }
            }
        },
        '/dev/nvme0n1': {
            120: {
                'read': {
                    'default': 3000,
                    'sto-disk': 4000,
                    'sto-disk-cache': 4000,
                    'tictoc-disk': 8000,
                    'tictoc-disk-cache': 8000,
                    'mvcc-disk': 230000,
                    'mvcc-disk-cache': 6000
                },
                'write': {
                    'default': 2000,
                    'sto-disk': 4000,
                    'sto-disk-cache': 4000,
                    'tictoc-disk': 16000,
                    'tictoc-disk-cache': 16000,
                    'mvcc-disk': 110000,
                    'mvcc-disk-cache': 4500
                },
                'mixed': {
                    'default': 2000,
                    'sto-disk': 4000,
                    'sto-disk-cache': 4000,
                    'tictoc-disk': 8000,
                    'tictoc-disk-cache': 8000,
                    'mvcc-disk': 420000,
                    'mvcc-disk-cache': 8000
                },
                'long': {
                    'mvcc-disk': 4000
                }
            }
        },
        '/dev/sda4': {
            120: {
                'read': {
                    'default': 28000,
                    '2pl-no-wait': 5000,
                    'occ-serial': 5200,
                    'sto-memory': 9000,
                    'sto-counter-lazy': 9000,
                    'sto-sketch': 9000,
                    'sto-disk': 10000,
                    'sto-disk-cache': 10000,
                    'tictoc-memory': 28000,
                    'tictoc-counter-lazy': 28000,
                    'tictoc-sketch': 28000,
                    'tictoc-disk': 36000,
                    'tictoc-disk-cache': 36000,
                    'mvcc-memory': 9000,
                    'mvcc-counter-lazy': 9000,
                    'mvcc-sketch': 9000,
                    'mvcc-disk': 2000000,
                    'mvcc-disk-cache': 2000000,
                },
                'write': {
                    'default': 3000,
                    'sto-disk': 4000,
                    'sto-disk-cache': 4000,
                    'tictoc-disk': 16000,   
                    'tictoc-disk-cache': 16000,
                    'mvcc-memory': 8000,
                    'mvcc-counter-lazy': 8000,
                    'mvcc-sketch': 8000,
                    'mvcc-disk': 1000000,
                    'mvcc-disk-cache': 6000
                },
                'mixed': {
                    'default': 40000,
                    '2pl-no-wait': 5000,
                    'occ-serial': 1000,
                    'sto-memory': 20000,
                    'sto-counter-lazy': 20000,
                    'sto-sketch': 20000,
                    'sto-disk': 24000,
                    'sto-disk-cache': 24000,
                    'tictoc-memory': 40000,
                    'tictoc-counter-lazy': 40000,
                    'tictoc-sketch': 40000,
                    'tictoc-disk': 60000,
                    'tictoc-disk-cache': 60000,
                    'mvcc-memory': 20000,
                    'mvcc-couter-lazy': 20000,
                    'mvcc-sketch': 20000,
                    'mvcc-disk': 7000000,
                    'mvcc-disk-cache': 80000
                },
                'long': {
                    'default': 3000,
                    'tictoc-memory': 4000,
                    'tictoc-counter-lazy': 4000,
                    'tictoc-sketch': 4000,
                    'tictoc-disk': 20000,
                    'tictoc-disk-cache': 20000,
                    'sto-memory': 6000,
                    'sto-counter-lazy': 6000,
                    'sto-sketch': 6000,
                    'sto-disk': 10000,
                    'sto-disk-cache': 10000,
                    'mvcc-memory': 16000,
                    'mvcc-counter-lazy': 16000,
                    'mvcc-sketch': 16000,
                    'mvcc-disk': 76000,
                    'mvcc-disk-cache': 26000,
                }
            }
        },
        '/dev/ram0': {
            60: {
                'read': {
                    'default': 3000,
                    'sto-disk': 4000,
                    'sto-disk-cache': 4000,
                    'tictoc-disk': 5000,
                    'tictoc-disk-cache': 5000,
                    'mvcc-disk': 320000
                },
                'write': {
                    'default': 2000,
                    'sto-disk': 3000,
                    'sto-disk-cache': 3000,
                    'tictoc-disk': 4000,
                    'tictoc-disk-cache': 4000,
                    'mvcc-disk': 320000
                },
                'mixed': {
                    'default': 2000,
                    'sto-disk': 2000,
                    'sto-disk-cache': 2000,
                    'tictoc-disk': 3000,
                    'tictoc-disk-cache': 3000,
                    'mvcc-disk': 200000
                }
            },
            120: {
                'read': {
                    'default': 1000,
                    'sto-disk': 4000,
                    'sto-disk-cache': 4000,
                    'tictoc-disk': 5000,
                    'tictoc-disk-cache': 5000,
                    'mvcc-disk': 320000
                },
                'write': {
                    'default': 1000,
                    'sto-disk': 2000,
                    'sto-disk-cache': 2000,
                    'tictoc-disk': 2000,
                    'tictoc-disk-cache': 2000,
                    'mvcc-disk': 320000
                },
                'mixed': {
                    'default': 2000,
                    'sto-disk': 2000,
                    'sto-disk-cache': 2000,
                    'tictoc-disk': 2000,
                    'tictoc-disk-cache': 2000,
                    'mvcc-disk': 200000
                }
            }
        }
    }

    try:
        # No support long_txn now
        if conf and 'read' in conf:
            conf_type = 'read'
        elif conf and 'write' in conf:
            conf_type = 'write'
        elif conf and 'mixed' in conf:
            conf_type = 'mixed'
        elif conf and 'long' in conf:
            conf_type = 'long'
        else:
            raise "Invalid configuration"

        if system in backofftime[dev_name][threads][conf_type]:
            backoff = backofftime[dev_name][threads][conf_type][system]
        else:
            backoff = backofftime[dev_name][threads][conf_type]['default']

        if 'mintxnabortpaneltyus' not in ycsbc_options:
            cmd += f' -w mintxnabortpaneltyus {backoff}'
    except:
        pass

    # run load phase
    # os.system(f'LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so ./ycsbc -db {db} -threads {threads} -L {spec_file} -p splinterdb.filename {dev_name} -p splinterdb.cache_size_mb {cache_size_mb}')
    if ycsbc_options:
        cmd += f' {ycsbc_options}'
    print(cmd)
    os.system(cmd)
    
if __name__ == '__main__':
    main(len(sys.argv), sys.argv)
