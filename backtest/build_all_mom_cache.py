"""통합 모멘텀+K_ratio 캐시 빌더 — 1회 가격 슬라이싱으로 5개 값 동시 계산
Usage: python build_all_mom_cache.py <start_idx> <end_idx>
Output: C:\dev\backtest\all_mom_cache_{start}_{end}.pkl
  {date: {ticker: {'kr': x, 'mom_6m': y, 'mom_6m1m': z, 'mom_12m1m': w, 'mom_12m': v}}}
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
OHLCV_FILE = os.path.join(CACHE, 'all_ohlcv_20190102_20260320.parquet')

prices = pd.read_parquet(OHLCV_FILE).replace(0, np.nan)
print(f'OHLCV: {prices.index[0]} ~ {prices.index[-1]}, {prices.shape}', flush=True)

# 전체 유니버스 (market_cap)
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

def k_ratio(s):
    if len(s) < 20:
        return np.nan
    log_cum = np.log(s / s.iloc[0])
    x = np.arange(len(log_cum))
    try:
        slope, _, _, _, stderr = linregress(x, log_cum.values)
        return slope / stderr if stderr > 0 else 0
    except:
        return 0

chunk = all_dates[START:END]
print(f'청크: {START}~{END} ({len(chunk)}일)', flush=True)

t0 = time.time()
result = {}
for idx, date in enumerate(chunk):
    dt = pd.Timestamp(date)
    if dt not in prices.index:
        continue
    avail = max((d for d in all_tickers_by_date if d <= date), default=None)
    if not avail:
        continue
    tickers = all_tickers_by_date[avail]

    date_data = {}
    for tk in tickers:
        if tk not in prices.columns:
            continue
        s = prices[tk].loc[:dt].dropna()
        if len(s) < 21:
            continue
        cur = s.iloc[-1]
        if cur <= 0 or pd.isna(cur):
            continue

        vals = {}

        # K_ratio (6M 기간)
        if len(s) >= 126:
            vals['kr'] = k_ratio(s.iloc[-126:])

        # 6M ret/vol
        if len(s) >= 126:
            p_6m = s.iloc[-126]
            if p_6m > 0:
                ret = cur / p_6m - 1
                vol = s.pct_change().iloc[-126:].std()
                if vol > 0:
                    vals['mom_6m'] = ret / vol

        # 6M-1M ret/vol
        if len(s) >= 126:
            p_6m = s.iloc[-126]
            p_1m = s.iloc[-21]
            if p_6m > 0 and p_1m > 0:
                ret = p_1m / p_6m - 1
                vol = s.pct_change().iloc[-126:-21].std()
                if vol and vol > 0:
                    vals['mom_6m1m'] = ret / vol

        # 12M-1M ret/vol
        if len(s) >= 252:
            p_12m = s.iloc[-252]
            p_1m = s.iloc[-21]
            if p_12m > 0 and p_1m > 0:
                ret = p_1m / p_12m - 1
                vol = s.pct_change().iloc[-252:-21].std()
                if vol and vol > 0:
                    vals['mom_12m1m'] = ret / vol

        # 12M ret/vol
        if len(s) >= 252:
            p_12m = s.iloc[-252]
            if p_12m > 0:
                ret = cur / p_12m - 1
                vol = s.pct_change().iloc[-252:].std()
                if vol > 0:
                    vals['mom_12m'] = ret / vol

        if vals:
            date_data[tk] = vals

    result[date] = date_data
    if idx % 50 == 0:
        print(f'  {START+idx}/{END} ({time.time()-t0:.0f}초)', flush=True)

out_path = f'C:\\dev\\backtest\\all_mom_cache_{START}_{END}.pkl'
with open(out_path, 'wb') as f:
    pickle.dump(result, f)
print(f'저장: {out_path} ({len(result)}일, {time.time()-t0:.0f}초)')
