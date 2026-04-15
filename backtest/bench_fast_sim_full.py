"""Benchmark: full cycle including cache rebuild for different weights

Measures the time for the complete grid search workflow:
1. Different weight combos each need a cache rebuild
2. Each weight combo runs many entry/exit/slots combos

Usage:
    python backtest/bench_fast_sim_full.py
"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

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
    print(f'{len(dates)} trading days, prices {prices.shape}')

    # Weight combos to test (simulating a small grid search)
    weight_combos = [
        (0.15, 0.25, 0.40, 0.20, 0.7),
        (0.20, 0.20, 0.40, 0.20, 0.7),
        (0.10, 0.25, 0.45, 0.20, 0.7),
        (0.15, 0.20, 0.45, 0.20, 0.5),
        (0.20, 0.25, 0.35, 0.20, 0.8),
    ]

    entry_exit_slots = [
        (3, 10.0, 5), (5, 10.0, 5), (7, 10.0, 5),
        (5, 7.0, 5), (5, 15.0, 5), (5, 10.0, 3),
        (5, 10.0, 7), (3, 7.0, 3), (7, 15.0, 7),
        (10, 20.0, 10),
    ]

    n_sims = len(weight_combos) * len(entry_exit_slots)
    print(f'\n{len(weight_combos)} weight combos x {len(entry_exit_slots)} rules = {n_sims} total sims')

    # ============================================================
    # CachedSimulator (old)
    # ============================================================
    print('\n=== CachedSimulator (old) ===')
    csim = CachedSimulator(all_rankings, dates, prices, bench)

    t0 = time.perf_counter()
    for v, q, g, m, gr in weight_combos:
        for ep, xp, sl in entry_exit_slots:
            csim.run_fast(v, q, g, m, gr, entry_param=ep, exit_param=xp, max_slots=sl)
    t_old = time.perf_counter() - t0
    print(f'  {n_sims} sims in {t_old:.2f}s = {t_old/n_sims*1000:.1f}ms/sim (incl. cache rebuilds)')

    # ============================================================
    # FastSimulator (new)
    # ============================================================
    print('\n=== FastSimulator (new) ===')
    fsim = FastSimulator(all_rankings, dates, prices, bench)

    t0 = time.perf_counter()
    for v, q, g, m, gr in weight_combos:
        for ep, xp, sl in entry_exit_slots:
            fsim.run_fast(v, q, g, m, gr, entry_param=ep, exit_param=xp, max_slots=sl)
    t_new = time.perf_counter() - t0
    print(f'  {n_sims} sims in {t_new:.2f}s = {t_new/n_sims*1000:.1f}ms/sim (incl. cache rebuilds)')

    # ============================================================
    # FastSimulator + FromCache (optimal path)
    # ============================================================
    print('\n=== FastSimulator + FromCache (optimal) ===')
    fsim2 = FastSimulator(all_rankings, dates, prices, bench)

    t0 = time.perf_counter()
    for v, q, g, m, gr in weight_combos:
        fsim2._ensure_cache(v, q, g, m, gr)
        runner = FastSimulatorFromCache(
            fsim2._cached_pipelines, fsim2._price_arr,
            fsim2._bench_arr, fsim2._date_row_indices, len(dates))
        for ep, xp, sl in entry_exit_slots:
            runner.run(entry_param=ep, exit_param=xp, max_slots=sl)
    t_opt = time.perf_counter() - t0
    print(f'  {n_sims} sims in {t_opt:.2f}s = {t_opt/n_sims*1000:.1f}ms/sim (incl. cache rebuilds)')

    # ============================================================
    # Summary
    # ============================================================
    print('\n=== Summary ===')
    print(f'  CachedSimulator:    {t_old:.2f}s total = {t_old/n_sims*1000:.1f}ms/sim')
    print(f'  FastSimulator:      {t_new:.2f}s total = {t_new/n_sims*1000:.1f}ms/sim ({t_old/t_new:.1f}x)')
    print(f'  Fast+FromCache:     {t_opt:.2f}s total = {t_opt/n_sims*1000:.1f}ms/sim ({t_old/t_opt:.1f}x)')
    print()
    print(f'  Grid search projection (1000 weight combos x 100 rules = 100K sims):')
    cache_build_time = (t_opt - len(weight_combos) * len(entry_exit_slots) * 0.020) / len(weight_combos)
    sim_time = 0.020  # ~20ms per sim
    proj_old = t_old / n_sims * 100000
    proj_new = (cache_build_time * 1000 + sim_time * 100000)
    print(f'    CachedSimulator:  {proj_old/60:.0f} min')
    print(f'    Fast+FromCache:   {proj_new/60:.0f} min')


if __name__ == '__main__':
    main()
