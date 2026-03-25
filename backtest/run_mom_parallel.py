"""모멘텀 기간 비교 — K_ratio 사전캐시 + 단일 모드 실행
Usage: python run_mom_parallel.py <mode>
  mode: 6m, 6m-1m, 12m-1m, 12m
"""
import sys, io, os, glob, json, time, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
from scipy.stats import norm, linregress
from production_simulator import ProductionSimulator

MODE = sys.argv[1] if len(sys.argv) > 1 else '6m'
CACHE = r'C:\dev\data_cache'
KR_CACHE = r'C:\dev\backtest\kr_cache.pkl'

prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

all_rankings = {}
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[d] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())

def rank_zscore(values):
    valid = values.dropna()
    if len(valid) < 3:
        return pd.Series(0, index=values.index)
    ranks = valid.rank(method='average')
    n = len(valid)
    u = (ranks - 0.375) / (n + 0.25)
    z = pd.Series(norm.ppf(u), index=valid.index).clip(-3, 3)
    if z.std() > 0:
        z = z / z.std()
    return z.reindex(values.index, fill_value=0)

def k_ratio(s):
    if len(s) < 20:
        return 0
    log_cum = np.log(s / s.iloc[0])
    x = np.arange(len(log_cum))
    try:
        slope, _, _, _, stderr = linregress(x, log_cum.values)
        return slope / stderr if stderr > 0 else 0
    except:
        return 0

# K_ratio 사전계산 (캐시)
if os.path.exists(KR_CACHE):
    with open(KR_CACHE, 'rb') as f:
        kr_cache = pickle.load(f)
else:
    kr_cache = {}
    for idx, date in enumerate(dates):
        dt = pd.Timestamp(date)
        if dt not in prices.index:
            continue
        tickers = [r['ticker'] for r in all_rankings[date]]
        kr_map = {}
        for tk in tickers:
            if tk not in prices.columns:
                continue
            s = prices[tk].loc[:dt].dropna()
            if len(s) >= 126:
                kr_map[tk] = k_ratio(s.iloc[-126:])
        kr_cache[date] = kr_map
        if idx % 100 == 0:
            print(f'  K_ratio 캐시: {idx}/{len(dates)}', flush=True)
    with open(KR_CACHE, 'wb') as f:
        pickle.dump(kr_cache, f)
    print(f'K_ratio 캐시 저장: {len(kr_cache)}일')

# 모멘텀 계산
def calc_mom_single(date_str, tickers, mode):
    dt = pd.Timestamp(date_str)
    if dt not in prices.index:
        return {}
    mom_raw = {}
    for tk in tickers:
        if tk not in prices.columns:
            continue
        s = prices[tk].loc[:dt].dropna()
        cur = s.iloc[-1] if len(s) > 0 else 0
        if cur <= 0 or pd.isna(cur):
            continue

        if mode == '6m':
            if len(s) >= 126:
                ret = cur / s.iloc[-126] - 1
                vol = s.pct_change().iloc[-126:].std()
                mom_raw[tk] = ret / vol if vol > 0 else np.nan
        elif mode == '6m-1m':
            if len(s) >= 126:
                p_6m = s.iloc[-126]
                p_1m = s.iloc[-21] if len(s) >= 21 else cur
                ret = (p_1m / p_6m - 1) if p_6m > 0 else np.nan
                vol = s.pct_change().iloc[-126:-21].std() if len(s) > 21 else 0
                mom_raw[tk] = ret / vol if vol and vol > 0 else np.nan
        elif mode == '12m-1m':
            if len(s) >= 252:
                p_12m = s.iloc[-252]
                p_1m = s.iloc[-21] if len(s) >= 21 else cur
                ret = (p_1m / p_12m - 1) if p_12m > 0 else np.nan
                vol = s.pct_change().iloc[-252:-21].std() if len(s) > 21 else 0
                mom_raw[tk] = ret / vol if vol and vol > 0 else np.nan
        elif mode == '12m':
            if len(s) >= 252:
                ret = cur / s.iloc[-252] - 1
                vol = s.pct_change().iloc[-252:].std()
                mom_raw[tk] = ret / vol if vol > 0 else np.nan

    if not mom_raw:
        return {}

    # rank z-score for momentum
    mom_z = rank_zscore(pd.Series(mom_raw))
    # rank z-score for k_ratio
    kr_raw = kr_cache.get(date_str, {})
    kr_ser = pd.Series({tk: kr_raw.get(tk, 0) for tk in mom_raw})
    kr_z = rank_zscore(kr_ser)

    # 결합: (mom_z + kr_z) / 2, restandardize
    combined = {}
    for tk in mom_z.index:
        m = mom_z.get(tk, 0)
        k = kr_z.get(tk, 0) if tk in kr_z.index else 0
        combined[tk] = (m + k) / 2
    cs = pd.Series(combined)
    if cs.std() > 0:
        cs = cs / cs.std()
    return cs.to_dict()

# ranking 수정 + 시뮬레이션
modified = {}
for date in dates:
    orig = all_rankings[date]
    tickers = [r['ticker'] for r in orig]
    mz = calc_mom_single(date, tickers, MODE)
    new_ranks = []
    for item in orig:
        ic = dict(item)
        tk = ic['ticker']
        if tk in mz and not np.isnan(mz[tk]):
            ic['momentum_s'] = mz[tk]
        new_ranks.append(ic)
    modified[date] = new_ranks

sim = ProductionSimulator(modified, dates, prices, bench)
r = sim.run(0.20, 0.20, 0.30, 0.30, g_rev=0.7, strategy='rank',
            entry_param=5, exit_param=15, max_slots=7, stop_loss=-0.10)

label = {'6m': '6M/Vol', '6m-1m': '6M-1M/Vol', '12m-1m': '12M-1M/Vol', '12m': '12M/Vol'}[MODE]
print(f'{label:15s}  CAGR={r["cagr"]:5.1f}%  Sharpe={r["sharpe"]:.3f}  MDD={r["mdd"]:5.1f}%')
