#!/usr/bin/env python3

import os
import sys
import json
import glob
import argparse
import warnings

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

SYSTEMS_ORDER = [
    'tictoc-memory',
    'tictoc-disk',
    'tictoc-memory-trace',
    'tictoc-disk-trace',
    'tictoc-memory-ext',
    'tictoc-disk-ext',
]
WORKLOADS = ['read_high', 'write_high', 'read_med', 'write_med']
TRACE_SYSTEMS = ['tictoc-memory-trace', 'tictoc-disk-trace']


def load_stats(results_dir):
    rows = []
    for path in glob.glob(os.path.join(results_dir, '*/stats.json')):
        with open(path) as f:
            rows.append(json.load(f))
    return pd.DataFrame(rows)


def load_trace_data(trace_dir, expid):
    exp_dir = os.path.join(trace_dir, expid)
    if not os.path.isdir(exp_dir):
        return None, None

    write_frames, abort_frames = [], []
    for path in glob.glob(os.path.join(exp_dir, 'writes_*.tsv')):
        try:
            df = pd.read_csv(path, sep='\t', header=None,
                             names=['txn_seq', 'key_hash', 'new_wts', 'ats_at_write'])
            write_frames.append(df)
        except Exception:
            pass
    for path in glob.glob(os.path.join(exp_dir, 'aborts_*.tsv')):
        try:
            df = pd.read_csv(path, sep='\t', header=None,
                             names=['txn_seq', 'key_hash', 'local_wts', 'current_wts',
                                    'commit_ts', 'ats_at_abort', 'is_hard'])
            abort_frames.append(df)
        except Exception:
            pass

    writes = pd.concat(write_frames, ignore_index=True) if write_frames else pd.DataFrame(
        columns=['txn_seq', 'key_hash', 'new_wts', 'ats_at_write'])
    aborts = pd.concat(abort_frames, ignore_index=True) if abort_frames else pd.DataFrame(
        columns=['txn_seq', 'key_hash', 'local_wts', 'current_wts',
                 'commit_ts', 'ats_at_abort', 'is_hard'])
    return writes, aborts


def classify_aborts(writes, aborts):
    if aborts.empty:
        return {'hard_txns': 0, 'soft_necessary_txns': 0,
                'soft_unnecessary_txns': 0, 'total_abort_txns': 0}

    hard_txns = set(aborts.loc[aborts['is_hard'] == 1, 'txn_seq'])

    soft = aborts[aborts['is_hard'] == 0]
    necessary_soft_txns = set()

    if not soft.empty and not writes.empty:
        # Pre-group writes by key_hash → numpy arrays for vectorized comparison.
        writes_by_key = {}
        for kh, grp in writes.groupby('key_hash', sort=False):
            writes_by_key[kh] = (grp['new_wts'].values, grp['ats_at_write'].values)

        # Per key_hash group of soft aborts, vectorize inner check.
        for kh, grp in soft.groupby('key_hash', sort=False):
            if kh not in writes_by_key:
                continue
            w_nwts, w_ats = writes_by_key[kh]
            for row in grp.itertuples(index=False):
                mask = ((row.local_wts < w_nwts) &
                        (w_nwts <= row.commit_ts) &
                        (w_ats < row.ats_at_abort))
                if mask.any():
                    necessary_soft_txns.add(row.txn_seq)

    all_abort_txns = set(aborts['txn_seq'])
    soft_only_txns = all_abort_txns - hard_txns
    unnecessary = soft_only_txns - necessary_soft_txns
    necessary_soft = soft_only_txns - unnecessary

    return {
        'hard_txns': len(hard_txns),
        'soft_necessary_txns': len(necessary_soft),
        'soft_unnecessary_txns': len(unnecessary),
        'total_abort_txns': len(all_abort_txns),
    }


def plot_goodput(df, workload, output_dir):
    subset = df[df['workload'] == workload].copy()
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(SYSTEMS_ORDER))
    vals = [subset.loc[subset['system'] == s, 'goodput'].values[0]
            if s in subset['system'].values else 0.0
            for s in SYSTEMS_ORDER]
    ax.bar(x, vals, width=0.6, color='steelblue', edgecolor='black', linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(SYSTEMS_ORDER, rotation=20, ha='right', fontsize=9)
    ax.set_ylabel('Goodput (txn/s)')
    ax.set_title(f'Goodput — {workload}')
    ax.yaxis.grid(True, alpha=0.4)
    ax.set_axisbelow(True)
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, f'goodput_{workload}.pdf'))
    plt.close(fig)
    pd.DataFrame({'system': SYSTEMS_ORDER, 'goodput': vals}).to_csv(
        os.path.join(output_dir, f'goodput_{workload}.csv'), index=False)


def plot_abort_rate(df, workload, output_dir):
    subset = df[df['workload'] == workload].copy()
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(SYSTEMS_ORDER))
    vals = [subset.loc[subset['system'] == s, 'abort_rate'].values[0]
            if s in subset['system'].values else 0.0
            for s in SYSTEMS_ORDER]
    ax.bar(x, vals, width=0.6, color='tomato', edgecolor='black', linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(SYSTEMS_ORDER, rotation=20, ha='right', fontsize=9)
    ax.set_ylabel('Abort rate (%)')
    ax.set_title(f'Abort rate — {workload}')
    ax.yaxis.grid(True, alpha=0.4)
    ax.set_axisbelow(True)
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, f'abort_rate_{workload}.pdf'))
    plt.close(fig)
    pd.DataFrame({'system': SYSTEMS_ORDER, 'abort_rate': vals}).to_csv(
        os.path.join(output_dir, f'abort_rate_{workload}.csv'), index=False)


def plot_abort_breakdown(breakdown, workload, output_dir):
    systems = TRACE_SYSTEMS
    hard = [breakdown.get((s, workload), {}).get('hard_txns', 0) for s in systems]
    soft_nec = [breakdown.get((s, workload), {}).get('soft_necessary_txns', 0) for s in systems]
    soft_unnec = [breakdown.get((s, workload), {}).get('soft_unnecessary_txns', 0) for s in systems]

    totals = [h + n + u for h, n, u in zip(hard, soft_nec, soft_unnec)]
    hard_pct = [100 * h / t if t > 0 else 0 for h, t in zip(hard, totals)]
    nec_pct = [100 * n / t if t > 0 else 0 for n, t in zip(soft_nec, totals)]
    unnec_pct = [100 * u / t if t > 0 else 0 for u, t in zip(soft_unnec, totals)]

    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.arange(len(systems))
    ax.bar(x, hard_pct, label='Hard', color='#e74c3c', edgecolor='black', linewidth=0.5)
    ax.bar(x, nec_pct, bottom=hard_pct, label='Soft-necessary', color='#f39c12',
           edgecolor='black', linewidth=0.5)
    bot2 = [h + n for h, n in zip(hard_pct, nec_pct)]
    ax.bar(x, unnec_pct, bottom=bot2, label='Soft-unnecessary', color='#2ecc71',
           edgecolor='black', linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(systems, rotation=15, ha='right', fontsize=9)
    ax.set_ylabel('Proportion (%)')
    ax.set_ylim(0, 100)
    ax.set_title(f'Abort breakdown — {workload}')
    ax.legend(fontsize=8)
    ax.yaxis.grid(True, alpha=0.4)
    ax.set_axisbelow(True)
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, f'abort_breakdown_{workload}.pdf'))
    plt.close(fig)
    rows = [{'system': s, 'hard_pct': h, 'soft_necessary_pct': n, 'soft_unnecessary_pct': u}
            for s, h, n, u in zip(systems, hard_pct, nec_pct, unnec_pct)]
    pd.DataFrame(rows).to_csv(os.path.join(output_dir, f'abort_breakdown_{workload}.csv'),
                              index=False)


def write_summary(df, breakdown, output_dir):
    lines = []
    for wl in WORKLOADS:
        lines.append(f'=== {wl} ===')
        subset = df[df['workload'] == wl]
        for s in SYSTEMS_ORDER:
            row = subset[subset['system'] == s]
            if row.empty:
                lines.append(f'  {s}: N/A')
                continue
            g = row['goodput'].values[0]
            a = row['abort_rate'].values[0]
            lines.append(f'  {s}: goodput={g:.1f} abort_rate={a:.2f}%')
        for s in TRACE_SYSTEMS:
            bd = breakdown.get((s, wl), {})
            total = bd.get('total_abort_txns', 0)
            unnec = bd.get('soft_unnecessary_txns', 0)
            if total > 0:
                pct = 100 * unnec / total
                lines.append(f'  {s} unnecessary aborts: {unnec}/{total} = {pct:.1f}%')
        lines.append('')
    path = os.path.join(output_dir, 'summary.txt')
    with open(path, 'w') as f:
        f.write('\n'.join(lines))
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--results-dir', required=True)
    parser.add_argument('--trace-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print('Loading stats...')
    df = load_stats(args.results_dir)
    if df.empty:
        print('ERROR: no stats.json files found', file=sys.stderr)
        sys.exit(1)
    print(f'  {len(df)} experiments loaded')

    breakdown = {}
    print('Loading trace data...')
    for s in TRACE_SYSTEMS:
        for wl in WORKLOADS:
            expid = f'{s}_{wl}_run1'
            writes, aborts = load_trace_data(args.trace_dir, expid)
            if writes is None:
                print(f'  {expid}: no trace dir, skipping')
                continue
            print(f'  {expid}: {len(writes)} writes, {len(aborts)} abort entries')
            breakdown[(s, wl)] = classify_aborts(writes, aborts)
            bd = breakdown[(s, wl)]
            print(f'    hard={bd["hard_txns"]} soft_nec={bd["soft_necessary_txns"]} '
                  f'soft_unnec={bd["soft_unnecessary_txns"]} total={bd["total_abort_txns"]}')

    print('Generating goodput figures...')
    for wl in WORKLOADS:
        plot_goodput(df, wl, args.output_dir)

    print('Generating abort rate figures...')
    for wl in WORKLOADS:
        plot_abort_rate(df, wl, args.output_dir)

    print('Generating abort breakdown figures...')
    for wl in WORKLOADS:
        plot_abort_breakdown(breakdown, wl, args.output_dir)

    summary_path = write_summary(df, breakdown, args.output_dir)
    print(f'Summary written to {summary_path}')
    with open(summary_path) as f:
        print(f.read())


if __name__ == '__main__':
    main()
