"""모멘텀 기간 비교 백테스트 — 6M, 6M-1M, 12M-1M, 12M"""
import sys, io, os, glob, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
from scipy.stats import norm
from production_simulator import ProductionSimulator

CACHE = r'C:\dev\data_cache'
t0 = time.time()

# 데이터 로드
ohlcv_file = sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]
prices = pd.read_parquet(ohlcv_file).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

all_rankings = {}
for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{year}/ranking_*.json'))):
        date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[date] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())
print(f'데이터: {len(dates)}거래일, OHLCV {prices.shape}')

# Blom rank z-score
def rank_zscore(values):
    """Series -> rank z-score (Blom transform)"""
    valid = values.dropna()
    if len(valid) < 3:
        return pd.Series(0, index=values.index)
    ranks = valid.rank(method='average')
    n = len(valid)
    u = (ranks - 0.375) / (n + 0.25)
    z = pd.Series(norm.ppf(u), index=valid.index)
    z = z.clip(-3, 3)
    # std=1 재표준화
    if z.std() > 0:
        z = z / z.std()
    return z.reindex(values.index, fill_value=0)

# 모멘텀 계산 함수
def calc_momentum(date_str, tickers, mode='6m'):
    """주어진 날짜/종목들에 대해 모멘텀 계산 후 rank z-score 반환"""
    dt = pd.Timestamp(date_str)
    if dt not in prices.index:
        return {}

    results = {}
    for tk in tickers:
        if tk not in prices.columns:
            continue
        s = prices[tk].loc[:dt].dropna()
        if len(s) < 30:
            continue

        cur = s.iloc[-1]
        if cur <= 0 or pd.isna(cur):
            continue

        if mode == '6m':
            # 현행: 6M return / volatility
            if len(s) >= 126:
                ret_6m = cur / s.iloc[-126] - 1 if s.iloc[-126] > 0 else np.nan
                vol = s.pct_change().iloc[-126:].std()
                results[tk] = ret_6m / vol if vol > 0 else np.nan
            else:
                results[tk] = np.nan
        elif mode == '6m-1m':
            # 6M - 1M (최근 1개월 제외)
            if len(s) >= 126:
                p_6m = s.iloc[-126] if s.iloc[-126] > 0 else np.nan
                p_1m = s.iloc[-21] if len(s) >= 21 and s.iloc[-21] > 0 else np.nan
                if pd.notna(p_6m) and pd.notna(p_1m):
                    results[tk] = p_1m / p_6m - 1  # 6M ago -> 1M ago
                else:
                    results[tk] = np.nan
            else:
                results[tk] = np.nan
        elif mode == '12m-1m':
            # 12M - 1M
            if len(s) >= 252:
                p_12m = s.iloc[-252] if s.iloc[-252] > 0 else np.nan
                p_1m = s.iloc[-21] if len(s) >= 21 and s.iloc[-21] > 0 else np.nan
                if pd.notna(p_12m) and pd.notna(p_1m):
                    results[tk] = p_1m / p_12m - 1
                else:
                    results[tk] = np.nan
            else:
                results[tk] = np.nan
        elif mode == '12m':
            # 순수 12M
            if len(s) >= 252:
                ret_12m = cur / s.iloc[-252] - 1 if s.iloc[-252] > 0 else np.nan
                results[tk] = ret_12m
            else:
                results[tk] = np.nan

    if not results:
        return {}

    # rank z-score
    ser = pd.Series(results)
    z = rank_zscore(ser)
    return z.to_dict()

# 모멘텀 모드별 rankings 생성
modes = ['6m', '6m-1m', '12m-1m', '12m']
mode_labels = {
    '6m': '6M/Vol (현행)',
    '6m-1m': '6M-1M',
    '12m-1m': '12M-1M',
    '12m': '12M',
}

print(f'\n=== 모멘텀 기간 비교 ===')
for mode in modes:
    # rankings 복사 + momentum_s 대체
    modified_rankings = {}
    for date in dates:
        orig = all_rankings[date]
        tickers = [r['ticker'] for r in orig]
        mom_z = calc_momentum(date, tickers, mode)

        new_ranks = []
        for item in orig:
            item_copy = dict(item)
            tk = item_copy['ticker']
            if tk in mom_z and not np.isnan(mom_z[tk]):
                item_copy['momentum_s'] = mom_z[tk]
            # else: keep original momentum_s
            new_ranks.append(item_copy)
        modified_rankings[date] = new_ranks

    sim = ProductionSimulator(modified_rankings, dates, prices, bench)
    r = sim.run(0.20, 0.20, 0.30, 0.30, g_rev=0.7, strategy='rank',
                entry_param=5, exit_param=15, max_slots=7, stop_loss=-0.10)
    print(f'  {mode_labels[mode]:15s}  CAGR={r["cagr"]:5.1f}%  Sharpe={r["sharpe"]:.3f}  '
          f'Sortino={r["sortino"]:.3f}  MDD={r["mdd"]:5.1f}%  Alpha={r["alpha"]:+.1f}%')

elapsed = time.time() - t0
print(f'\n완료: {elapsed:.0f}초')
