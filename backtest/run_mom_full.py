"""모멘텀 기간 비교 — 전체 유니버스 섹터 내 rank z-score (프로덕션 동일)
Usage: python run_mom_full.py <mode>
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
MIN_SECTOR = 10

prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

# 전체 유니버스: market_cap 파일에서 종목 + 섹터
mc_files = sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet')))
# {date: DataFrame with index=ticker}
mc_cache = {}
for f in mc_files:
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8 and d.isdigit():
        mc_cache[d] = d  # lazy load path
mc_paths = {d: f for f, d in [(f, os.path.basename(f).split('_')[-1].replace('.parquet', '')) for f in mc_files] if len(d) == 8}

# 섹터 데이터: krx_sector 파일
sector_files = sorted(glob.glob(os.path.join(CACHE, 'krx_sector_*.parquet')))
sector_cache = {}
for f in sector_files:
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        sector_cache[d] = f

all_rankings = {}
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[d] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())

def _rank_to_z(series):
    valid = series.dropna()
    if len(valid) < 3:
        return pd.Series(0, index=series.index)
    ranks = valid.rank(method='average')
    n = len(valid)
    u = (ranks - 0.375) / (n + 0.25)
    z = pd.Series(norm.ppf(u), index=valid.index).clip(-3, 3)
    return z.reindex(series.index, fill_value=0)

def sector_rank_zscore(values, sectors):
    if sectors is None:
        z = _rank_to_z(values)
        if z.std() > 0: z = z / z.std()
        return z
    full_z = _rank_to_z(values)
    result = pd.Series(0.0, index=values.index)
    valid_mask = values.notna()
    for sec in sectors[valid_mask].unique():
        sec_mask = (sectors == sec) & valid_mask
        if sec_mask.sum() >= MIN_SECTOR:
            result[sec_mask] = _rank_to_z(values[sec_mask])
        else:
            result[sec_mask] = full_z[sec_mask]
    if result.std() > 0:
        result = result / result.std()
    return result

def k_ratio(s):
    if len(s) < 20: return 0
    log_cum = np.log(s / s.iloc[0])
    x = np.arange(len(log_cum))
    try:
        slope, _, _, _, stderr = linregress(x, log_cum.values)
        return slope / stderr if stderr > 0 else 0
    except: return 0

# 전체 유니버스 K_ratio 캐시 로드
KR_FULL_CACHE_PATH = os.path.join(os.path.dirname(__file__), 'kr_full_cache.pkl')
_kr_full_cache = {}
if os.path.exists(KR_FULL_CACHE_PATH):
    import pickle as _pkl
    with open(KR_FULL_CACHE_PATH, 'rb') as _f:
        _kr_full_cache = _pkl.load(_f)
    print(f'K_ratio 캐시 로드: {len(_kr_full_cache)}일', flush=True)

def get_sector_map(date_str):
    """해당 날짜의 전체 유니버스 섹터 맵 {ticker: sector}"""
    # 가장 가까운 이전 날짜의 섹터 파일 사용
    avail = sorted([d for d in sector_cache if d <= date_str], reverse=True)
    if not avail:
        return {}
    sf = sector_cache[avail[0]]
    try:
        df = pd.read_parquet(sf)
        if '업종명' in df.columns:
            return df['업종명'].to_dict()
        elif '섹터' in df.columns:
            return df['섹터'].to_dict()
        else:
            # 첫번째 문자열 컬럼 사용
            for c in df.columns:
                if df[c].dtype == object:
                    return df[c].to_dict()
    except:
        pass
    return {}

def get_universe_tickers(date_str):
    """해당 날짜의 프로덕션 유니버스 종목 리스트 (시총 1000억+ 필터)"""
    avail = sorted([d for d in mc_paths if d <= date_str], reverse=True)
    if not avail:
        return []
    try:
        df = pd.read_parquet(mc_paths[avail[0]])
        # 프로덕션 동일 필터: 시총 1000억 이상
        if '시가총액' in df.columns:
            df = df[df['시가총액'] >= 1000 * 1e8]
        return list(df.index)
    except:
        return []

def calc_mom_full_universe(date_str, mode):
    """전체 유니버스에서 모멘텀 계산 → 섹터 내 rank z-score"""
    dt = pd.Timestamp(date_str)
    if dt not in prices.index:
        return {}

    # 전체 유니버스
    universe = get_universe_tickers(date_str)
    sec_map = get_sector_map(date_str)
    if not universe:
        return {}

    tickers = []
    mom_raws = []
    kr_raws = []
    secs = []

    for tk in universe:
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
                p_6m = s.iloc[-126]; p_1m = s.iloc[-21]
                ret = (p_1m / p_6m - 1) if p_6m > 0 else np.nan
                vol = s.pct_change().iloc[-126:-21].std()
                mom_val = ret / vol if vol and vol > 0 else np.nan
        elif mode == '12m-1m':
            if len(s) >= 252 and len(s) >= 21:
                p_12m = s.iloc[-252]; p_1m = s.iloc[-21]
                ret = (p_1m / p_12m - 1) if p_12m > 0 else np.nan
                vol = s.pct_change().iloc[-252:-21].std()
                mom_val = ret / vol if vol and vol > 0 else np.nan
        elif mode == '12m':
            if len(s) >= 252:
                ret = cur / s.iloc[-252] - 1
                vol = s.pct_change().iloc[-252:].std()
                mom_val = ret / vol if vol > 0 else np.nan

        # K_ratio (항상 6M) — 캐시 우선
        if _kr_full_cache and date_str in _kr_full_cache and tk in _kr_full_cache[date_str]:
            kr_val = _kr_full_cache[date_str][tk]
        else:
            kr_val = k_ratio(s.iloc[-126:]) if len(s) >= 126 else 0

        tickers.append(tk)
        mom_raws.append(mom_val)
        kr_raws.append(kr_val)
        secs.append(sec_map.get(tk, '기타'))

    if not tickers:
        return {}

    mom_ser = pd.Series(mom_raws, index=tickers)
    kr_ser = pd.Series(kr_raws, index=tickers)
    sec_ser = pd.Series(secs, index=tickers)

    mom_z = sector_rank_zscore(mom_ser, sec_ser)
    kr_z = sector_rank_zscore(kr_ser, sec_ser)

    combined = (mom_z + kr_z) / 2
    if combined.std() > 0:
        combined = combined / combined.std()

    return combined.to_dict()

# 실행
t0 = time.time()
modified = {}
for idx, date in enumerate(dates):
    orig = all_rankings[date]
    mz = calc_mom_full_universe(date, MODE)
    new_ranks = []
    for item in orig:
        ic = dict(item)
        tk = ic['ticker']
        if tk in mz and not np.isnan(mz[tk]):
            ic['momentum_s'] = mz[tk]
        new_ranks.append(ic)
    modified[date] = new_ranks
    if idx % 100 == 0:
        print(f'  진행: {idx}/{len(dates)} ({time.time()-t0:.0f}초)', flush=True)

sim = ProductionSimulator(modified, dates, prices, bench)
r = sim.run(0.20, 0.20, 0.30, 0.30, g_rev=0.7, strategy='rank',
            entry_param=5, exit_param=15, max_slots=7, stop_loss=-0.10)

label = {'6m': '6M/Vol', '6m-1m': '6M-1M/Vol', '12m-1m': '12M-1M/Vol', '12m': '12M/Vol'}[MODE]
elapsed = time.time() - t0
print(f'{label:15s}  CAGR={r["cagr"]:5.1f}%  Sharpe={r["sharpe"]:.3f}  Sortino={r["sortino"]:.3f}  MDD={r["mdd"]:5.1f}%  ({elapsed:.0f}초)')
