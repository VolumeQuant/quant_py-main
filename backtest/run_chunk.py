"""Phase 2 chunk 실행기 — 인자로 weight 인덱스와 chunk ID 받음

Usage:
    python backtest/run_chunk.py 0,1,2,3 1 2020,2021,2022,2023
"""
import sys
import json
import glob
import os
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
from production_simulator import ProductionSimulator

PROJECT = r'C:\dev'
CACHE = os.path.join(PROJECT, 'data_cache')

indices = [int(x) for x in sys.argv[1].split(',')]
chunk_id = sys.argv[2]
train_years = sys.argv[3].split(',')

# 데이터 로드
all_rankings = {}
for year in train_years:
    for f in sorted(glob.glob(os.path.join(PROJECT, f'state/bt_{year}/ranking_*.json'))):
        date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[date] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())
prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')),
                                 key=lambda f: f.split('_')[2])[0])
prices = prices.replace(0, np.nan)
bench_file = os.path.join(CACHE, 'index_benchmarks.parquet')
bench = pd.read_parquet(bench_file) if os.path.exists(bench_file) else pd.DataFrame()
sim = ProductionSimulator(all_rankings, dates, prices, bench)

# Top 10 로드
with open(os.path.join(PROJECT, 'backtest_results/final_p1_top10.json'), 'r', encoding='utf-8') as f:
    top10 = json.load(f)
my_weights = [top10[i] for i in indices]

strategies = {
    'score': [(e, x) for e in [64, 66, 68, 70, 72, 74] for x in [58, 60, 62, 64, 66, 68] if e > x],
    'rank': [(e, x) for e in [3, 5, 7, 10] for x in [10, 15, 20, 25, 30] if x > e],
    'hybrid_se': [(e, x) for e in [66, 68, 70, 72] for x in [15, 20, 25, 30]],
    'hybrid_re': [(e, x) for e in [3, 5, 7, 10] for x in [60, 64, 68]],
}
slot_options = [3, 5, 7, 10, 0]
pool_options = [15, 20, 25]

results = []
done = 0
t0 = time.time()

for w in my_weights:
    for sn, params in strategies.items():
        for ep, xp in params:
            for sl in slot_options:
                for pl in pool_options:
                    r = sim.run(w['v'] / 100, w['q'] / 100, w['g'] / 100, w['m'] / 100,
                                g_rev=w['g_rev'], strategy=sn,
                                entry_param=ep, exit_param=xp,
                                max_slots=sl, top_n=pl)
                    results.append({
                        'v': w['v'], 'q': w['q'], 'g': w['g'], 'm': w['m'],
                        'g_rev': w['g_rev'], 'strategy': sn,
                        'entry': ep, 'exit': xp, 'slots': sl, 'pool': pl,
                        **r})
                    done += 1
                    if done % 200 == 0:
                        print(f'chunk{chunk_id}: [{done}] {time.time() - t0:.0f}s', flush=True)

out = os.path.join(PROJECT, f'backtest_results/final_p2_chunk{chunk_id}.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False)
print(f'chunk{chunk_id}: {len(results)} done {time.time() - t0:.0f}s')
