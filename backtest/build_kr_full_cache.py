"""전체 유니버스 K_ratio 캐시 빌더 — 날짜 범위 분할
Usage: python build_kr_full_cache.py <start_idx> <end_idx>
"""
import sys, io, os, glob, json, time, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')

import pandas as pd
import numpy as np
from scipy.stats import linregress

START = int(sys.argv[1])
END = int(sys.argv[2])
CACHE = r'C:\dev\data_cache'

prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)

mc_files = sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet')))
mc_paths = {}
for f in mc_files:
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        mc_paths[d] = f

all_rankings = {}
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        all_rankings[d] = True  # just need dates
dates = sorted(all_rankings.keys())

def k_ratio(s):
    if len(s) < 20: return 0
    log_cum = np.log(s / s.iloc[0])
    x = np.arange(len(log_cum))
    try:
        slope, _, _, _, stderr = linregress(x, log_cum.values)
        return slope / stderr if stderr > 0 else 0
    except: return 0

def get_universe(date_str):
    avail = sorted([d for d in mc_paths if d <= date_str], reverse=True)
    if not avail: return []
    try:
        df = pd.read_parquet(mc_paths[avail[0]])
        return list(df.index)
    except: return []

t0 = time.time()
result = {}
chunk_dates = dates[START:END]
print(f'K_ratio 캐시: {START}~{END} ({len(chunk_dates)}일)', flush=True)

for idx, date in enumerate(chunk_dates):
    dt = pd.Timestamp(date)
    if dt not in prices.index:
        continue
    universe = get_universe(date)
    kr_map = {}
    for tk in universe:
        if tk not in prices.columns: continue
        s = prices[tk].loc[:dt].dropna()
        if len(s) >= 126:
            kr_map[tk] = k_ratio(s.iloc[-126:])
    result[date] = kr_map
    if idx % 50 == 0:
        print(f'  {START+idx}/{END} ({time.time()-t0:.0f}초)', flush=True)

out_path = f'C:\\dev\\backtest\\kr_full_cache_{START}_{END}.pkl'
with open(out_path, 'wb') as f:
    pickle.dump(result, f)
print(f'저장: {out_path} ({len(result)}일, {time.time()-t0:.0f}초)')
