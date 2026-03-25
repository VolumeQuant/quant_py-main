"""6M return/vol 모멘텀 raw 캐시 빌더 — 날짜 분할 병렬
Usage: python build_mom_cache.py <start_idx> <end_idx>
"""
import sys, io, os, glob, json, time, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')

import pandas as pd
import numpy as np

START = int(sys.argv[1])
END = int(sys.argv[2])
CACHE = r'C:\dev\data_cache'

prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)

# 전체 종목 리스트 (market_cap에서)
mc_files = sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet')))
all_tickers_by_date = {}
for f in mc_files:
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        try:
            df = pd.read_parquet(f, columns=['시가총액'])
            all_tickers_by_date[d] = list(df.index)
        except:
            continue

# ranking 날짜
all_dates = []
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        all_dates.append(d)
all_dates = sorted(set(all_dates))

chunk = all_dates[START:END]
print(f'모멘텀 캐시: {START}~{END} ({len(chunk)}일)', flush=True)

t0 = time.time()
result = {}
for idx, date in enumerate(chunk):
    dt = pd.Timestamp(date)
    if dt not in prices.index:
        continue
    # 해당일 유니버스
    avail = max((d for d in all_tickers_by_date if d <= date), default=None)
    if not avail:
        continue
    tickers = all_tickers_by_date[avail]

    mom_map = {}
    for tk in tickers:
        if tk not in prices.columns:
            continue
        s = prices[tk].loc[:dt].dropna()
        if len(s) < 126:
            continue
        cur = s.iloc[-1]
        if cur <= 0 or pd.isna(cur):
            continue
        p_6m = s.iloc[-126]
        if p_6m <= 0:
            continue
        ret = cur / p_6m - 1
        vol = s.pct_change().iloc[-126:].std()
        if vol > 0:
            mom_map[tk] = ret / vol

    result[date] = mom_map
    if idx % 50 == 0:
        print(f'  {START+idx}/{END} ({time.time()-t0:.0f}초)', flush=True)

out_path = f'C:\\dev\\backtest\\mom_raw_cache_{START}_{END}.pkl'
with open(out_path, 'wb') as f:
    pickle.dump(result, f)
print(f'저장: {out_path} ({len(result)}일, {time.time()-t0:.0f}초)')
