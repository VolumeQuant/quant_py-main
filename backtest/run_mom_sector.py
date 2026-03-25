"""모멘텀 기간 비교 — 섹터 내 rank z-score (프로덕션 동일)
Usage: python run_mom_sector.py <mode>
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
MIN_SECTOR = 10

prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

all_rankings = {}
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[d] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())

def _rank_to_z(series):
    """Blom rank z-score"""
    valid = series.dropna()
    if len(valid) < 3:
        return pd.Series(0, index=series.index)
    ranks = valid.rank(method='average')
    n = len(valid)
    u = (ranks - 0.375) / (n + 0.25)
    z = pd.Series(norm.ppf(u), index=valid.index).clip(-3, 3)
    return z.reindex(series.index, fill_value=0)

def sector_rank_zscore(values, sectors):
    """섹터 내 rank z-score (프로덕션 동일 로직)
    대형 섹터(>=MIN_SECTOR): 섹터 내 rank z-score
    소형 섹터: 전체 유니버스 fallback
    """
    if sectors is None:
        z = _rank_to_z(values)
        if z.std() > 0:
            z = z / z.std()
        return z

    full_z = _rank_to_z(values)
    result = pd.Series(0.0, index=values.index)
    valid_mask = values.notna()

    for sec in sectors[valid_mask].unique():
        sec_mask = (sectors == sec) & valid_mask
        count = sec_mask.sum()
        if count >= MIN_SECTOR:
            result[sec_mask] = _rank_to_z(values[sec_mask])
        else:
            result[sec_mask] = full_z[sec_mask]

    # std=1 재표준화
    if result.std() > 0:
        result = result / result.std()
    return result

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

# K_ratio 캐시 로드
if os.path.exists(KR_CACHE):
    with open(KR_CACHE, 'rb') as f:
        kr_cache = pickle.load(f)
else:
    print('K_ratio 캐시 없음 — 먼저 run_mom_parallel.py 6m 실행 필요')
    sys.exit(1)

def calc_mom_sector(date_str, rankings, mode):
    """섹터 내 rank z-score로 모멘텀 계산"""
    dt = pd.Timestamp(date_str)
    if dt not in prices.index:
        return {}

    # raw 모멘텀 + K_ratio + 섹터 수집
    tickers = []
    mom_raws = []
    kr_raws = []
    secs = []

    kr_map = kr_cache.get(date_str, {})

    for item in rankings:
        tk = item.get('ticker', '')
        sec = item.get('sector', '기타')
        if tk not in prices.columns:
            continue
        s = prices[tk].loc[:dt].dropna()
        cur = s.iloc[-1] if len(s) > 0 else 0
        if cur <= 0 or pd.isna(cur):
            continue

        mom_val = np.nan
        if mode == '6m':
            if len(s) >= 126:
                ret = cur / s.iloc[-126] - 1
                vol = s.pct_change().iloc[-126:].std()
                mom_val = ret / vol if vol > 0 else np.nan
        elif mode == '6m-1m':
            if len(s) >= 126 and len(s) >= 21:
                p_6m = s.iloc[-126]
                p_1m = s.iloc[-21]
                ret = (p_1m / p_6m - 1) if p_6m > 0 else np.nan
                vol = s.pct_change().iloc[-126:-21].std()
                mom_val = ret / vol if vol and vol > 0 else np.nan
        elif mode == '12m-1m':
            if len(s) >= 252 and len(s) >= 21:
                p_12m = s.iloc[-252]
                p_1m = s.iloc[-21]
                ret = (p_1m / p_12m - 1) if p_12m > 0 else np.nan
                vol = s.pct_change().iloc[-252:-21].std()
                mom_val = ret / vol if vol and vol > 0 else np.nan
        elif mode == '12m':
            if len(s) >= 252:
                ret = cur / s.iloc[-252] - 1
                vol = s.pct_change().iloc[-252:].std()
                mom_val = ret / vol if vol > 0 else np.nan

        tickers.append(tk)
        mom_raws.append(mom_val)
        kr_raws.append(kr_map.get(tk, 0))
        secs.append(sec)

    if not tickers:
        return {}

    # 섹터 내 rank z-score
    mom_ser = pd.Series(mom_raws, index=tickers)
    kr_ser = pd.Series(kr_raws, index=tickers)
    sec_ser = pd.Series(secs, index=tickers)

    mom_z = sector_rank_zscore(mom_ser, sec_ser)
    kr_z = sector_rank_zscore(kr_ser, sec_ser)

    # 결합: 평균 후 재표준화
    combined = (mom_z + kr_z) / 2
    if combined.std() > 0:
        combined = combined / combined.std()

    return combined.to_dict()

# ranking 수정 + 시뮬레이션
t0 = time.time()
modified = {}
for date in dates:
    orig = all_rankings[date]
    mz = calc_mom_sector(date, orig, MODE)
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
elapsed = time.time() - t0
print(f'{label:15s}  CAGR={r["cagr"]:5.1f}%  Sharpe={r["sharpe"]:.3f}  Sortino={r["sortino"]:.3f}  MDD={r["mdd"]:5.1f}%  ({elapsed:.0f}초)')
