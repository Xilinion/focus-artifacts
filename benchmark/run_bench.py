#!/usr/bin/python3

import os
import sys
import json
import argparse
import datetime
import subprocess
import re

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from exp_system import ExpSystem


def get_device_size_bytes(device: str) -> int:
    output = subprocess.run(
        ["lsblk", device, "--output", "SIZE", "--bytes", "--noheadings", "--nodeps"],
        capture_output=True,
        check=True,
    )
    return int(output.stdout.decode())


def build_ycsbc_cmd(system, workload_spec, threads, dbfile, run_seconds,
                    cache_size_mb=4096):
    db = 'splinterdb' if system == 'splinterdb' else 'transactional_splinterdb'
    num_normal_bg_threads = 0
    num_memtable_bg_threads = 0

    cmd = (
        f'LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so'
        f' ./ycsbc -db {db} -threads {threads}'
        f' -benchmark_seconds {run_seconds} -client txn'
        f' -L {workload_spec} -W {workload_spec}'
        f' -p splinterdb.filename {dbfile}'
        f' -p splinterdb.cache_size_mb {cache_size_mb}'
        f' -p splinterdb.num_normal_bg_threads {num_normal_bg_threads}'
        f' -p splinterdb.num_memtable_bg_threads {num_memtable_bg_threads}'
        f' -p splinterdb.disable_upsert 1'
        f' -p splinterdb.io_contexts_per_process 128'
    )
    if dbfile.startswith('/dev/'):
        cmd += f' -p splinterdb.disk_size_gb {get_device_size_bytes(dbfile) // (1024**3)}'
    cmd += ' -p splinterdb.use_log 0'
    return cmd


def parse_ycsbc_output(output: str):
    goodput_ktps = None
    total_commit = 0
    total_abort = 0

    for line in output.splitlines():
        m = re.match(r'# Transaction throughput \(KTPS\)\s+([\d.]+)', line)
        if m:
            goodput_ktps = float(m.group(1))
        m = re.match(r'\[Client \d+\] commit_cnt: (\d+), abort_cnt: (\d+)', line)
        if m:
            total_commit += int(m.group(1))
            total_abort += int(m.group(2))

    goodput = goodput_ktps * 1000 if goodput_ktps is not None else 0.0
    total = total_commit + total_abort
    abort_rate = (total_abort / total * 100) if total > 0 else 0.0
    return goodput, abort_rate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--system', required=True)
    parser.add_argument('--workload', required=True, help='path to .spec file')
    parser.add_argument('--threads', type=int, default=16)
    parser.add_argument('--dbfile', default='/dev/nvme0n1')
    parser.add_argument('--run-seconds', type=float, default=120)
    parser.add_argument('--expid', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--cache-size-mb', type=int, default=4096)
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()

    bench_dir = os.path.dirname(os.path.realpath(__file__))
    splinterdb_dir = os.path.join(bench_dir, '../splinterdb')

    trace_exp_dir = os.path.join(bench_dir, 'trace_output', args.expid)
    os.makedirs(trace_exp_dir, exist_ok=True)
    os.makedirs(args.output_dir, exist_ok=True)

    if not args.skip_build:
        ExpSystem.build(args.system, splinterdb_dir, args.threads, backup=False)

    manifest_path = os.path.join(bench_dir, 'trace_output', 'manifest.jsonl')
    expid_base_m = args.expid.rsplit('_run', 1)[0]
    workload_name_m = (expid_base_m[len(args.system) + 1:]
                       if expid_base_m.startswith(args.system + '_')
                       else os.path.basename(args.workload))
    manifest_entry = {
        'expid': args.expid,
        'system': args.system,
        'workload': workload_name_m,
        'threads': args.threads,
        'run': 1,
        'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
        'dbfile': args.dbfile,
    }
    with open(manifest_path, 'a') as f:
        f.write(json.dumps(manifest_entry) + '\n')

    cmd = build_ycsbc_cmd(
        args.system, args.workload, args.threads,
        args.dbfile, args.run_seconds, args.cache_size_mb,
    )

    env = os.environ.copy()
    env['TICTOC_EXPID'] = args.expid

    os.chdir(bench_dir)
    result = subprocess.run(cmd, shell=True, capture_output=False,
                            text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=env)
    output = result.stdout

    sys.stdout.write(output)
    sys.stdout.flush()

    goodput, abort_rate = parse_ycsbc_output(output)

    # Derive workload shortname from expid: <system>_<workload>_run<N>
    expid_base = args.expid.rsplit('_run', 1)[0]
    if expid_base.startswith(args.system + '_'):
        workload_name = expid_base[len(args.system) + 1:]
    else:
        workload_name = os.path.basename(args.workload)

    stats = {
        'expid': args.expid,
        'system': args.system,
        'workload': workload_name,
        'goodput': goodput,
        'abort_rate': abort_rate,
        'threads': args.threads,
        'run_seconds': args.run_seconds,
    }
    stats_path = os.path.join(args.output_dir, 'stats.json')
    with open(stats_path, 'w') as f:
        json.dump(stats, f, indent=2)

    print(f'expid={args.expid} goodput={goodput:.1f} abort_rate={abort_rate:.2f}%')


if __name__ == '__main__':
    main()
