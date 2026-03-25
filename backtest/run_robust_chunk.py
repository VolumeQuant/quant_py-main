"""Robust 최적화 chunk — 인자로 weight 범위 받음

Usage:
    python backtest/run_robust_chunk.py 0 77 1
    (weight index 0~76, chunk_id 1)
"""
import sys
import os
import json
import glob
import time
from pathlib import Path
from itertools import product

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from production_simulator import ProductionSimulator

PROJECT = Path(__file__).parent.parent
CACHE_DIR = PROJECT / 'data_cache'

start_idx = int(sys.argv[1])
end_idx = int(sys.argv[2])
chunk_id = sys.argv[3]

# 데이터 로드
prices = pd.read_parquet(sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                                 key=lambda f: f.stem.split('_')[2])[0])
prices = prices.replace(0, np.nan)
bench = pd.read_parquet(CACHE_DIR / 'index_benchmarks.parquet') \
    if (CACHE_DIR / 'index_benchmarks.parquet').exists() else pd.DataFrame()

year_sims = {}
for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
    data = {}
    for f in sorted(glob.glob(str(PROJECT / f'state/bt_{year}/ranking_*.json'))):
        date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            data[date] = json.load(fh).get('rankings', [])
    dates = sorted(data.keys())
    year_sims[year] = (data, dates)

all_data = {}
for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
    all_data.update(year_sims[year][0])
all_dates = sorted(all_data.keys())

# Weight grid
all_weights = []
for v in range(10, 41, 5):
    for q in range(10, 41, 5):
        for g in range(10, 41, 5):
            m = 100 - v - q - g
            if 10 <= m <= 40:
                all_weights.append((v, q, g, m))
g_ratios = [0.3, 0.4, 0.5, 0.6, 0.7]

# 전체 조합에서 chunk 범위
all_combos = list(product(all_weights, g_ratios))
my_combos = all_combos[start_idx:end_idx]

results = []
done = 0
t0 = time.time()

for (v, q, g, m), g_rev in my_combos:
    sim_all = ProductionSimulator(all_data, all_dates, prices, bench)
    r_all = sim_all.run(v/100, q/100, g/100, m/100, g_rev=g_rev,
                        strategy='rank', entry_param=5, exit_param=15,
                        max_slots=7, top_n=20, stop_loss=-0.10)

    yearly = {}
    for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
        data, dates = year_sims[year]
        sim_y = ProductionSimulator(data, dates, prices, bench)
        r_y = sim_y.run(v/100, q/100, g/100, m/100, g_rev=g_rev,
                        strategy='rank', entry_param=5, exit_param=15,
                        max_slots=7, top_n=20, stop_loss=-0.10)
        yearly[year] = r_y

    all_positive = bool(all(yearly[y]['sharpe'] >= 0 for y in yearly))
    bear_mdd_ok = bool(yearly['2022']['mdd'] < 45)
    min_sharpe = float(min(yearly[y]['sharpe'] for y in yearly))

    results.append({
        'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev,
        **r_all,
        'min_year_sharpe': round(min_sharpe, 3),
        'bear_2022_sharpe': yearly['2022']['sharpe'],
        'bear_2022_mdd': yearly['2022']['mdd'],
        'all_positive': all_positive,
        'bear_mdd_ok': bear_mdd_ok,
        'y2020': yearly['2020']['sharpe'],
        'y2021': yearly['2021']['sharpe'],
        'y2022': yearly['2022']['sharpe'],
        'y2023': yearly['2023']['sharpe'],
        'y2024': yearly['2024']['sharpe'],
        'y2025': yearly['2025']['sharpe'],
    })
    done += 1
    if done % 50 == 0:
        print(f'chunk{chunk_id}: [{done}/{len(my_combos)}] {time.time()-t0:.0f}s', flush=True)

out = PROJECT / f'backtest_results/robust_chunk{chunk_id}.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False)
print(f'chunk{chunk_id}: {len(results)} done {time.time()-t0:.0f}s')
