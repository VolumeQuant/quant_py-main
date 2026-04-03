"""Parallel grid search using TurboSimulator — Windows-safe

Solves the multiprocessing.Pool pickle crash by having each worker
process load data independently (one-time cost per process).

Strategy:
  1. Main process: generate all (weight_combo, entry_exit_slots) task batches
  2. Workers: each loads data once, then runs all assigned weight combos
  3. Communication: tasks are lightweight tuples (no large data in pickle)

Usage:
    python backtest/parallel_grid_search.py
    python backtest/parallel_grid_search.py --workers 4
"""
import sys
import json
import time
import os
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

CACHE_DIR = PROJECT_ROOT / 'data_cache'


def _load_data_once():
    """Load all data. Called once per worker process."""
    import pandas as pd
    from full_grid_search import load_data
    from turbo_simulator import TurboSimulator

    all_rankings, dates = load_data(['2020', '2021', '2022', '2023', '2024', '2025'])

    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                          key=lambda f: f.stem.split('_')[2])
    prices = pd.read_parquet(ohlcv_files[0]).replace(0, np.nan)

    bench_file = CACHE_DIR / 'index_benchmarks.parquet'
    bench = pd.read_parquet(bench_file) if bench_file.exists() else pd.DataFrame()

    tsim = TurboSimulator(all_rankings, dates, prices, bench)
    return tsim


# Worker-local cache: each process loads data once
_worker_sim = None


def _init_worker():
    """Initialize worker process with pre-loaded data."""
    global _worker_sim
    _worker_sim = _load_data_once()


def _run_weight_batch(args):
    """Worker function: run all entry/exit/slots combos for one weight combo.

    Args is a lightweight tuple: ((v, q, g, m, g_rev), entry_exit_slots_list)
    No large data needs to be pickled.
    """
    global _worker_sim
    if _worker_sim is None:
        _init_worker()

    (v, q, g, m, g_rev), entry_exit_slots = args
    tsim = _worker_sim

    from turbo_simulator import TurboRunner

    # Build cache for this weight combo
    tsim._ensure_cache(v / 100, q / 100, g / 100, m / 100, g_rev)
    runner = TurboRunner(tsim)

    results = []
    for entry_p, exit_p, slots in entry_exit_slots:
        r = runner.run(entry_param=entry_p, exit_param=exit_p, max_slots=slots)
        results.append({
            'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev,
            'entry': entry_p, 'exit': exit_p, 'slots': slots,
            **r
        })
    return results


def generate_weight_grid(step=5, min_w=0, max_w=80):
    combos = []
    for v in range(min_w, max_w + 1, step):
        for q in range(min_w, max_w + 1, step):
            for g in range(min_w, max_w + 1, step):
                m = 100 - v - q - g
                if min_w <= m <= max_w:
                    combos.append((v, q, g, m))
    return combos


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=0,
                        help='Number of worker processes (0=auto)')
    parser.add_argument('--step', type=int, default=5,
                        help='Weight grid step size')
    args = parser.parse_args()

    t_start = time.time()

    # Determine number of workers
    n_cores = os.cpu_count() or 4
    if args.workers > 0:
        n_workers = args.workers
    else:
        # Auto: use 3-4 workers to balance memory vs speed
        # Each worker loads ~500MB of data
        n_workers = min(4, n_cores)

    print(f'=== Parallel Grid Search (TurboSimulator) ===')
    print(f'Workers: {n_workers} (CPU cores: {n_cores})')
    print()

    # Generate search space
    weights = generate_weight_grid(step=args.step)
    g_ratios = [0.0, 0.2, 0.4, 0.6, 0.7, 0.8, 1.0]

    entry_list = [1, 3, 5, 7, 10, 15]
    exit_list = [5, 7, 10, 15, 20]
    slots_list = [1, 3, 5, 7, 10, 15]
    entry_exit_slots = [(e, x, s) for e in entry_list for x in exit_list
                        for s in slots_list if x > e]

    weight_g_combos = [(v, q, g, m, gr) for (v, q, g, m) in weights for gr in g_ratios]
    n_weight = len(weight_g_combos)
    n_rules = len(entry_exit_slots)
    total = n_weight * n_rules

    print(f'Weight combos: {len(weights)} x G ratios {len(g_ratios)} = {n_weight}')
    print(f'Entry/exit/slots rules: {n_rules}')
    print(f'Total simulations: {total:,}')
    print()

    # Build tasks (lightweight — no data, just parameter tuples)
    tasks = [(wg, entry_exit_slots) for wg in weight_g_combos]

    # Run in parallel
    all_results = []
    done = 0

    print(f'Starting {n_workers} workers (each will load data independently)...')

    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_init_worker,
    ) as executor:
        # Submit all tasks
        futures = {executor.submit(_run_weight_batch, task): task for task in tasks}

        for future in as_completed(futures):
            try:
                batch_results = future.result()
                all_results.extend(batch_results)
            except Exception as e:
                task = futures[future]
                print(f'  ERROR: {task[0]} — {e}')

            done += 1
            if done % 100 == 0 or done == n_weight:
                elapsed = time.time() - t_start
                rate = done / elapsed if elapsed > 0 else 1
                remain = (n_weight - done) / rate / 60 if rate > 0 else 0
                print(f'  [{done}/{n_weight}] {done/n_weight*100:.0f}% | '
                      f'{elapsed/60:.0f}min elapsed | ~{remain:.0f}min remaining',
                      flush=True)

    # Sort and report
    all_results.sort(key=lambda x: -x['sharpe'])

    total_elapsed = time.time() - t_start
    print(f'\n{"="*70}')
    print(f'Completed: {total:,} simulations in {total_elapsed/60:.1f} minutes')
    print(f'Speed: {total/total_elapsed:.0f} sims/sec')
    print()

    print(f'Top 20:')
    print(f'{"#":>3} {"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Grev":>4} {"Ent":>3}{"Ext":>4} {"Slt":>3} | '
          f'{"CAGR":>6} {"Shrp":>5} {"Sort":>5} {"MDD":>5} {"Alpha":>6} {"H":>3}')
    print('-' * 70)
    for i, r in enumerate(all_results[:20]):
        print(f'{i+1:3d} {r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["g_rev"]:4.1f} '
              f'{r["entry"]:3d}{r["exit"]:4.0f} {r["slots"]:3d} | '
              f'{r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["sortino"]:5.3f} {r["mdd"]:4.1f}% '
              f'{r["alpha"]:+5.1f}% {r["avg_holdings"]:3.1f}')

    # Save
    results_dir = PROJECT_ROOT / 'backtest_results'
    results_dir.mkdir(exist_ok=True)
    out_file = results_dir / 'turbo_grid_results.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(all_results[:1000], f, ensure_ascii=False, indent=2)
    print(f'\nResults saved: {out_file}')

    return all_results


if __name__ == '__main__':
    main()
