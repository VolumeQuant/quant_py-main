"""모멘텀 기간 비교 — 통합 캐시 기반, 프로덕션 유니버스 필터 동일 적용
캐시: all_mom_cache.pkl ({date: {ticker: {kr, mom_6m, mom_6m1m, mom_12m1m, mom_12m}}})
"""
import sys, io, os, glob, json, time, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
from scipy.stats import norm
from production_simulator import ProductionSimulator

CACHE = r'C:\dev\data_cache'
MIN_SECTOR = 10
OHLCV_FILE = os.path.join(CACHE, 'all_ohlcv_20190102_20260320.parquet')

t0 = time.time()
print('로드 중...', flush=True)

prices = pd.read_parquet(OHLCV_FILE).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

with open(r'C:\dev\backtest\all_mom_cache.pkl', 'rb') as f:
    mom_cache = pickle.load(f)

with open(r'C:\dev\backtest\tv_avg_cache.pkl', 'rb') as f:
    tv_cache = pickle.load(f)

# 시총
mc_cap = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        try:
            df = pd.read_parquet(f, columns=['시가총액'])
            mc_cap[d] = df['시가총액'].to_dict()
        except:
            continue

# 섹터
sec_data = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'krx_sector_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        try:
            df = pd.read_parquet(f)
            for c in df.columns:
                if df[c].dtype == object:
                    sec_data[d] = df[c].to_dict()
                    break
        except:
            continue

# 금융업
finance_tickers = set()
for d in sorted(sec_data.keys(), reverse=True)[:5]:
    for tk, sec in sec_data[d].items():
        if any(k in str(sec) for k in ['금융', '은행', '보험', '증권', '캐피탈']):
            finance_tickers.add(tk)

# rankings
all_rankings = {}
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[d] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())

print(f'로드 완료: {time.time()-t0:.0f}초 ({len(dates)}거래일, 캐시 {len(mom_cache)}일)', flush=True)

# ── z-score 함수 ──
def _rank_to_z(series):
    valid = series.dropna()
    if len(valid) < 3:
        return pd.Series(0, index=series.index)
    ranks = valid.rank(method='average')
    n = len(valid)
    u = (ranks - 0.375) / (n + 0.25)
    z = pd.Series(norm.ppf(u), index=valid.index).clip(-3, 3)
    return z.reindex(series.index, fill_value=0)

def sector_rank_zscore_raw(values, sectors):
    """프로덕션 동일: 서브팩터 단위에서는 restandardize 안 함.
    카테고리 합산 후 1번만 restandardize."""
    full_z = _rank_to_z(values)
    if sectors is None:
        return full_z  # raw Blom z-score, no restandardize
    result = pd.Series(0.0, index=values.index)
    valid_mask = values.notna()
    for sec in sectors[valid_mask].unique():
        sec_mask = (sectors == sec) & valid_mask
        if sec_mask.sum() >= MIN_SECTOR:
            result[sec_mask] = _rank_to_z(values[sec_mask])
        else:
            result[sec_mask] = full_z[sec_mask]
    return result  # raw, no restandardize

# ── 프로덕션 유니버스 필터 (차등 거래대금) ──
def get_production_universe(date_str):
    """프로덕션과 동일한 유니버스 필터:
    - 시총 >= 1000억
    - 거래대금: 대형(시총1조+) >= 50억, 중소형 >= 20억
    - 금융업 제외
    """
    cap_d = max((d for d in mc_cap if d <= date_str), default=None)
    tv_d = max((d for d in tv_cache if d <= date_str), default=None)
    if not cap_d:
        return []
    caps = mc_cap[cap_d]
    tvs = tv_cache.get(tv_d, {}) if tv_d else {}
    result = []
    for tk, cap in caps.items():
        cap_억 = cap / 1e8
        if cap_억 < 1000:
            continue
        if tk in finance_tickers:
            continue
        tv = tvs.get(tk, 0)
        if cap_억 >= 10000:  # 대형주 1조+
            if tv < 50:
                continue
        else:  # 중소형
            if tv < 20:
                continue
        result.append(tk)
    return result

# ── 모멘텀 기간별 비교 ──
mom_keys = {
    '6M/Vol (현행)': 'mom_6m',
    '6M-1M/Vol': 'mom_6m1m',
    '12M-1M/Vol': 'mom_12m1m',
    '12M/Vol': 'mom_12m',
}

print(f'\n=== 모멘텀 기간 비교 (프로덕션 유니버스 필터, 섹터 내 rank z-score) ===')
print(f'{"모멘텀":<16s}  CAGR   Sharpe  Sortino  MDD    Alpha  커버리지')
print('-' * 72)

for label, mom_key in mom_keys.items():
    ts = time.time()
    modified = {}
    coverage_total = 0
    coverage_hit = 0

    for date in dates:
        orig = all_rankings[date]
        date_mom = mom_cache.get(date, {})
        universe = get_production_universe(date)
        sec_d = max((d for d in sec_data if d <= date), default=None)
        secs = sec_data.get(sec_d, {}) if sec_d else {}

        if not date_mom:
            modified[date] = orig
            continue

        # ranking JSON 종목 = 프로덕션 유니버스 (v70과 동일 조건)
        tickers = []
        mom_vals = []
        kr_vals = []
        sec_vals = []
        for item in orig:
            tk = item.get('ticker', '')
            if tk not in date_mom:
                continue
            tk_data = date_mom[tk]
            if mom_key not in tk_data:
                continue
            tickers.append(tk)
            mom_vals.append(tk_data[mom_key])
            kr_vals.append(tk_data.get('kr', 0) or 0)
            sec_vals.append(item.get('sector', '기타'))

        coverage_total += len(universe)
        coverage_hit += len(tickers)

        if len(tickers) < 10:
            modified[date] = orig
            continue

        # 섹터 내 rank z-score (프로덕션 동일: raw → 합산 → 1번 restandardize)
        mom_z = sector_rank_zscore_raw(
            pd.Series(mom_vals, index=tickers),
            pd.Series(sec_vals, index=tickers))
        kr_z = sector_rank_zscore_raw(
            pd.Series(kr_vals, index=tickers),
            pd.Series(sec_vals, index=tickers))

        # 카테고리 평균 후 restandardize (프로덕션 동일)
        combined = (mom_z.fillna(0) + kr_z.fillna(0)) / 2
        if combined.std() > 0:
            combined = combined / combined.std()
        mz = combined.to_dict()

        # ranking 수정
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

    cov_pct = coverage_hit / coverage_total * 100 if coverage_total > 0 else 0
    elapsed = time.time() - ts
    print(f'{label:<16s}  {r["cagr"]:5.1f}%  {r["sharpe"]:.3f}   {r["sortino"]:.3f}   {r["mdd"]:5.1f}%  {r["alpha"]:+5.1f}%  {cov_pct:.0f}%  ({elapsed:.0f}초)')

print(f'\n총 소요: {time.time()-t0:.0f}초')
print('\n※ 절대값은 프로덕션(85.2%)과 다름 — M만 재계산, V/Q/G는 ranking JSON 고정')
print('※ 상대 비교(어떤 기간이 더 나은가)만 유효')
