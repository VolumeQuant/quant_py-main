"""Benchmark: CachedSimulator vs FastSimulator

Verifies correctness (same results) and measures wall-clock speedup.

Usage:
    python backtest/bench_fast_sim.py
"""
import sys
import os
import json
import glob
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

from production_simulator import ProductionSimulator
from full_grid_search import CachedSimulator, load_data
from fast_simulator import FastSimulator, FastSimulatorFromCache

PROJECT = Path(__file__).parent.parent
CACHE_DIR = PROJECT / 'data_cache'


def main():
    print('=== Loading data ===')
    all_rankings, dates = load_data(['2020', '2021', '2022', '2023', '2024', '2025'])
    ohlcv_file = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                        key=lambda f: f.stem.split('_')[2])[0]
    prices = pd.read_parquet(ohlcv_file).replace(0, np.nan)
    bench_file = CACHE_DIR / 'index_benchmarks.parquet'
    bench = pd.read_parquet(bench_file) if bench_file.exists() else pd.DataFrame()

    print(f'{len(dates)} trading days ({dates[0]}~{dates[-1]})')
    print(f'prices: {prices.shape}')
    print()

    # Test parameters
    v_w, q_w, g_w, m_w = 0.15, 0.25, 0.40, 0.20
    g_rev = 0.7
    test_combos = [
        (5, 10.0, 5),
        (3, 10.0, 5),
        (5, 15.0, 7),
        (1, 7.0, 3),
        (7, 10.0, 5),
        (10, 20.0, 10),
        (3, 5.0, 3),
        (5, 10.0, 7),
    ]

    # ============================================================
    # 1. Correctness check: CachedSimulator vs FastSimulator
    # ============================================================
    print('=== Correctness Check ===')
    csim = CachedSimulator(all_rankings, dates, prices, bench)
    fsim = FastSimulator(all_rankings, dates, prices, bench)

    all_match = True
    for entry_p, exit_p, slots in test_combos:
        r_old = csim.run_fast(v_w, q_w, g_w, m_w, g_rev,
                              entry_param=entry_p, exit_param=exit_p, max_slots=slots)
        r_new = fsim.run_fast(v_w, q_w, g_w, m_w, g_rev,
                              entry_param=entry_p, exit_param=exit_p, max_slots=slots)

        match = True
        for key in ['cagr', 'sharpe', 'mdd', 'total', 'avg_holdings']:
            if abs(r_old[key] - r_new[key]) > 0.02:
                print(f'  MISMATCH E{entry_p}/X{exit_p}/S{slots}: {key} old={r_old[key]} new={r_new[key]}')
                match = False
                all_match = False

        status = 'OK' if match else 'FAIL'
        print(f'  E{entry_p}/X{exit_p}/S{slots}: {status}'
              f'  CAGR={r_new["cagr"]:.2f}% Sharpe={r_new["sharpe"]:.3f} MDD={r_new["mdd"]:.2f}%')

    print(f'\nOverall: {"ALL MATCH" if all_match else "SOME MISMATCHES"}\n')

    # ============================================================
    # 2. Benchmark: CachedSimulator
    # ============================================================
    print('=== Benchmark: CachedSimulator ===')
    # Warm up cache
    csim._ensure_cache(v_w, q_w, g_w, m_w, g_rev)

    t0 = time.perf_counter()
    n_runs = len(test_combos)
    for _ in range(5):  # 5 rounds
        for entry_p, exit_p, slots in test_combos:
            csim.run_fast(v_w, q_w, g_w, m_w, g_rev,
                          entry_param=entry_p, exit_param=exit_p, max_slots=slots)
    t_cached = time.perf_counter() - t0
    total_runs_cached = n_runs * 5
    per_run_cached = t_cached / total_runs_cached * 1000
    print(f'  {total_runs_cached} runs in {t_cached:.2f}s = {per_run_cached:.1f}ms/run')

    # ============================================================
    # 3. Benchmark: FastSimulator
    # ============================================================
    print('=== Benchmark: FastSimulator ===')
    # Warm up cache
    fsim._ensure_cache(v_w, q_w, g_w, m_w, g_rev)

    t0 = time.perf_counter()
    for _ in range(5):
        for entry_p, exit_p, slots in test_combos:
            fsim.run_fast(v_w, q_w, g_w, m_w, g_rev,
                          entry_param=entry_p, exit_param=exit_p, max_slots=slots)
    t_fast = time.perf_counter() - t0
    total_runs_fast = n_runs * 5
    per_run_fast = t_fast / total_runs_fast * 1000
    print(f'  {total_runs_fast} runs in {t_fast:.2f}s = {per_run_fast:.1f}ms/run')

    # ============================================================
    # 4. Benchmark: FastSimulatorFromCache (pre-built cache)
    # ============================================================
    print('=== Benchmark: FastSimulatorFromCache ===')
    runner = FastSimulatorFromCache(
        fsim._cached_pipelines, fsim._price_arr,
        fsim._bench_arr, fsim._date_row_indices, len(dates))

    t0 = time.perf_counter()
    for _ in range(5):
        for entry_p, exit_p, slots in test_combos:
            runner.run(entry_param=entry_p, exit_param=exit_p, max_slots=slots)
    t_from_cache = time.perf_counter() - t0
    total_runs_fc = n_runs * 5
    per_run_fc = t_from_cache / total_runs_fc * 1000
    print(f'  {total_runs_fc} runs in {t_from_cache:.2f}s = {per_run_fc:.1f}ms/run')

    # ============================================================
    # 5. Throughput estimate for grid search
    # ============================================================
    print()
    print('=== Speedup Summary ===')
    print(f'  CachedSimulator:       {per_run_cached:7.1f} ms/run')
    print(f'  FastSimulator:         {per_run_fast:7.1f} ms/run ({per_run_cached/per_run_fast:.1f}x faster)')
    print(f'  FastSimulatorFromCache:{per_run_fc:7.1f} ms/run ({per_run_cached/per_run_fc:.1f}x faster)')
    print()
    print(f'  Throughput for 5,000 sims (same weight):')
    print(f'    CachedSimulator:        {per_run_cached * 5000 / 1000:.0f}s')
    print(f'    FastSimulator:          {per_run_fast * 5000 / 1000:.0f}s')
    print(f'    FastSimulatorFromCache: {per_run_fc * 5000 / 1000:.0f}s')


if __name__ == '__main__':
    main()
