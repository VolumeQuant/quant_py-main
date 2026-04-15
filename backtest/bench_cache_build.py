"""Profile where cache build time goes: reweight vs compute_status"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

from full_grid_search import load_data
from fast_simulator import FastSimulator

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
    print(f'{len(dates)} trading days')

    v_w, q_w, g_w, m_w, g_rev = 0.15, 0.25, 0.40, 0.20, 0.7

    fsim = FastSimulator(all_rankings, dates, prices, bench)

    # Measure reweight only
    t0 = time.perf_counter()
    n_dates = len(dates)
    reweighted = [None] * n_dates
    for i in range(n_dates):
        reweighted[i] = fsim._vectorized_reweight(dates[i], v_w, q_w, g_w, m_w, g_rev)
    t_rw = time.perf_counter() - t0
    print(f'Reweight:       {t_rw:.3f}s ({t_rw/n_dates*1000:.2f}ms/date)')

    # Measure compute_status only
    t0 = time.perf_counter()
    pipelines = [None] * n_dates
    for i in range(2, n_dates):
        rw0 = reweighted[i]
        rw1 = reweighted[i - 1]
        rw2 = reweighted[i - 2]
        if rw0 is not None:
            pipelines[i] = fsim._vectorized_compute_status(rw0, rw1, rw2, 20)
    t_cs = time.perf_counter() - t0
    print(f'Compute status: {t_cs:.3f}s ({t_cs/n_dates*1000:.2f}ms/date)')

    # Measure full _ensure_cache
    fsim._cached_key = None  # force rebuild
    t0 = time.perf_counter()
    fsim._ensure_cache(v_w, q_w, g_w, m_w, g_rev)
    t_full = time.perf_counter() - t0
    print(f'Full cache:     {t_full:.3f}s')

    # Measure init (pre-extraction)
    t0 = time.perf_counter()
    fsim2 = FastSimulator(all_rankings, dates, prices, bench)
    t_init = time.perf_counter() - t0
    print(f'Init:           {t_init:.3f}s')

    print(f'\nBreakdown: init={t_init:.3f}s, reweight={t_rw:.3f}s, status={t_cs:.3f}s')
    print(f'Cache build per weight combo: {t_rw + t_cs:.3f}s')

    # How many weight combos fit in 1 hour?
    per_combo = t_rw + t_cs
    per_sim = 0.021  # 21ms per sim run
    rules_per_combo = 100
    combos_per_hour = 3600 / (per_combo + rules_per_combo * per_sim)
    print(f'Weight combos/hour (100 rules each): {combos_per_hour:.0f}')
    print(f'Total sims/hour: {combos_per_hour * rules_per_combo:.0f}')


if __name__ == '__main__':
    main()
