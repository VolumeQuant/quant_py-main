"""유니버스 필터 최적화 — 사전캐시 활용 고속 버전
Usage: python run_univ_fast.py <min_cap> <min_tv>
"""
import sys, io, os, glob, json, time, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
from scipy.stats import norm
from production_simulator import ProductionSimulator

MIN_CAP = int(sys.argv[1])
MIN_TV = int(sys.argv[2])
CACHE = r'C:\dev\data_cache'
MIN_SECTOR = 10

t0 = time.time()

# 사전 캐시 로드
prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

with open(r'C:\dev\backtest\kr_full_cache.pkl', 'rb') as f:
    kr_cache = pickle.load(f)

with open(r'C:\dev\backtest\tv_avg_cache.pkl', 'rb') as f:
    tv_avg_cache = pickle.load(f)

# market_cap: {date: {ticker: 시총(원)}}
mc_cap_cache = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        try:
            df = pd.read_parquet(f, columns=['시가총액'])
            mc_cap_cache[d] = df['시가총액'].to_dict()
        except:
            continue

# 섹터: {date: {ticker: sector}}
sec_cache = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'krx_sector_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        try:
            df = pd.read_parquet(f)
            for c in df.columns:
                if df[c].dtype == object:
                    sec_cache[d] = df[c].to_dict()
                    break
        except:
            continue

# 금융업 종목
finance_tickers = set()
for d in sorted(sec_cache.keys(), reverse=True)[:5]:
    for tk, sec in sec_cache[d].items():
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

load_time = time.time() - t0
print(f'로드 완료: {load_time:.0f}초', flush=True)

def _rank_to_z(series):
    valid = series.dropna()
    if len(valid) < 3: return pd.Series(0, index=series.index)
    ranks = valid.rank(method='average'); n = len(valid)
    u = (ranks - 0.375) / (n + 0.25)
    z = pd.Series(norm.ppf(u), index=valid.index).clip(-3, 3)
    return z.reindex(series.index, fill_value=0)

def sector_rank_zscore(values, sectors):
    full_z = _rank_to_z(values)
    if sectors is None:
        if full_z.std() > 0: full_z = full_z / full_z.std()
        return full_z
    result = pd.Series(0.0, index=values.index)
    valid_mask = values.notna()
    for sec in sectors[valid_mask].unique():
        sec_mask = (sectors == sec) & valid_mask
        if sec_mask.sum() >= MIN_SECTOR:
            result[sec_mask] = _rank_to_z(values[sec_mask])
        else:
            result[sec_mask] = full_z[sec_mask]
    if result.std() > 0: result = result / result.std()
    return result

def get_filtered_universe(date_str):
    """사전캐시 기반 고속 유니버스 필터"""
    # 가장 가까운 이전 날짜
    cap_d = max((d for d in mc_cap_cache if d <= date_str), default=None)
    tv_d = max((d for d in tv_avg_cache if d <= date_str), default=None)
    if not cap_d: return []
    caps = mc_cap_cache[cap_d]
    tvs = tv_avg_cache.get(tv_d, {}) if tv_d else {}
    result = []
    for tk, cap in caps.items():
        if cap < MIN_CAP * 1e8: continue
        if tk in finance_tickers: continue
        if MIN_TV > 0 and tvs.get(tk, 0) < MIN_TV: continue
        result.append(tk)
    return result

def get_sector_map(date_str):
    d = max((d for d in sec_cache if d <= date_str), default=None)
    return sec_cache.get(d, {}) if d else {}

def calc_mom(date_str):
    dt = pd.Timestamp(date_str)
    if dt not in prices.index: return {}
    universe = get_filtered_universe(date_str)
    sec_map = get_sector_map(date_str)
    if not universe: return {}
    kr_map = kr_cache.get(date_str, {})
    tickers = []; mom_raws = []; kr_raws = []; secs = []
    for tk in universe:
        if tk not in prices.columns: continue
        s = prices[tk].loc[:dt].dropna()
        if len(s) < 126: continue
        cur = s.iloc[-1]
        if cur <= 0 or pd.isna(cur): continue
        ret = cur / s.iloc[-126] - 1
        vol = s.pct_change().iloc[-126:].std()
        if vol <= 0: continue
        tickers.append(tk); mom_raws.append(ret / vol)
        kr_raws.append(kr_map.get(tk, 0)); secs.append(sec_map.get(tk, '기타'))
    if not tickers: return {}
    mom_z = sector_rank_zscore(pd.Series(mom_raws, index=tickers), pd.Series(secs, index=tickers))
    kr_z = sector_rank_zscore(pd.Series(kr_raws, index=tickers), pd.Series(secs, index=tickers))
    combined = (mom_z + kr_z) / 2
    if combined.std() > 0: combined = combined / combined.std()
    return combined.to_dict()

# 실행
modified = {}
for idx, date in enumerate(dates):
    orig = all_rankings[date]
    mz = calc_mom(date)
    new_ranks = []
    for item in orig:
        ic = dict(item); tk = ic['ticker']
        if tk in mz and not np.isnan(mz[tk]): ic['momentum_s'] = mz[tk]
        new_ranks.append(ic)
    modified[date] = new_ranks
    if idx % 200 == 0:
        print(f'  {idx}/{len(dates)} ({time.time()-t0:.0f}초)', flush=True)

sim = ProductionSimulator(modified, dates, prices, bench)
r = sim.run(0.20, 0.20, 0.30, 0.30, g_rev=0.7, strategy='rank',
            entry_param=5, exit_param=15, max_slots=7, stop_loss=-0.10)
elapsed = time.time() - t0
print(f'CAP={MIN_CAP} TV={MIN_TV}  CAGR={r["cagr"]:5.1f}%  Sharpe={r["sharpe"]:.3f}  MDD={r["mdd"]:5.1f}%  ({elapsed:.0f}초)')
