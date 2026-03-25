"""모멘텀 기간별 raw 캐시 빌더 — 6m-1m, 12m-1m, 12m
Usage: python build_mom_multi.py <mode> <start> <end>
"""
import sys, io, os, glob, json, time, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')

import pandas as pd
import numpy as np

MODE = sys.argv[1]  # 6m-1m, 12m-1m, 12m
START = int(sys.argv[2])
END = int(sys.argv[3])
CACHE = r'C:\dev\data_cache'

prices = pd.read_parquet(os.path.join(CACHE, 'all_ohlcv_20190102_20260320.parquet')).replace(0, np.nan)

mc_files = sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet')))
all_tickers_by_date = {}
for f in mc_files:
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        try:
            df = pd.read_parquet(f, columns=['시가총액'])
            all_tickers_by_date[d] = list(df.index)
        except: continue

all_dates = []
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        all_dates.append(d)
all_dates = sorted(set(all_dates))

chunk = all_dates[START:END]
t0 = time.time()
result = {}

for idx, date in enumerate(chunk):
    dt = pd.Timestamp(date)
    if dt not in prices.index: continue
    avail = max((d for d in all_tickers_by_date if d <= date), default=None)
    if not avail: continue
    tickers = all_tickers_by_date[avail]

    mom_map = {}
    for tk in tickers:
        if tk not in prices.columns: continue
        s = prices[tk].loc[:dt].dropna()
        cur = s.iloc[-1] if len(s) > 0 else 0
        if cur <= 0 or pd.isna(cur): continue

        if MODE == '6m':
            if len(s) >= 126:
                p_6m = s.iloc[-126]
                if p_6m > 0:
                    ret = cur / p_6m - 1
                    vol = s.pct_change().iloc[-126:].std()
                    if vol > 0: mom_map[tk] = ret / vol
        elif MODE == '6m-1m':
            if len(s) >= 126 and len(s) >= 21:
                p_6m = s.iloc[-126]; p_1m = s.iloc[-21]
                if p_6m > 0 and p_1m > 0:
                    ret = p_1m / p_6m - 1
                    vol = s.pct_change().iloc[-126:-21].std()
                    if vol and vol > 0: mom_map[tk] = ret / vol
        elif MODE == '12m-1m':
            if len(s) >= 252 and len(s) >= 21:
                p_12m = s.iloc[-252]; p_1m = s.iloc[-21]
                if p_12m > 0 and p_1m > 0:
                    ret = p_1m / p_12m - 1
                    vol = s.pct_change().iloc[-252:-21].std()
                    if vol and vol > 0: mom_map[tk] = ret / vol
        elif MODE == '12m':
            if len(s) >= 252:
                p_12m = s.iloc[-252]
                if p_12m > 0:
                    ret = cur / p_12m - 1
                    vol = s.pct_change().iloc[-252:].std()
                    if vol > 0: mom_map[tk] = ret / vol

    result[date] = mom_map
    if idx % 100 == 0:
        print(f'  {MODE} {START+idx}/{END} ({time.time()-t0:.0f}초)', flush=True)

out_path = f'C:\\dev\\backtest\\mom_{MODE}_cache_{START}_{END}.pkl'
with open(out_path, 'wb') as f:
    pickle.dump(result, f)
print(f'저장: {out_path} ({len(result)}일, {time.time()-t0:.0f}초)')
