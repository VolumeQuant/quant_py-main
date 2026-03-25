"""유니버스 필터 단일 조합 실행
Usage: python run_univ_single.py <min_cap> <min_tv>
  min_cap: 시총 하한 (억)
  min_tv: 20일평균 거래대금 하한 (억)
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

prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

with open(r'C:\dev\backtest\kr_full_cache.pkl', 'rb') as f:
    kr_cache = pickle.load(f)

mc_paths = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8: mc_paths[d] = f

sector_files = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'krx_sector_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8: sector_files[d] = f

all_rankings = {}
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[d] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())

# 금융업 종목
finance_tickers = set()
for d in sorted(sector_files.keys(), reverse=True)[:5]:
    try:
        df = pd.read_parquet(sector_files[d])
        for col in df.columns:
            if df[col].dtype == object:
                fin_mask = df[col].str.contains('금융|은행|보험|증권|캐피탈', na=False)
                finance_tickers.update(df[fin_mask].index.tolist())
                break
    except: continue

# 거래대금 캐시: {date: {ticker: 20일평균거래대금(억)}}
tv_cache = {}
for fp in sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet'))):
    d = os.path.basename(fp).split('_')[-1].replace('.parquet', '')
    if len(d) != 8: continue
    try:
        df = pd.read_parquet(fp, columns=['거래대금'])
        tv_cache[d] = (df['거래대금'] / 1e8).to_dict()
    except: continue

def get_avg_tv(ticker, date_str, lookback=20):
    tv_dates = sorted([d for d in tv_cache if d <= date_str], reverse=True)[:lookback]
    vals = [tv_cache[d].get(ticker, 0) for d in tv_dates]
    vals = [v for v in vals if v > 0]
    return np.mean(vals) if vals else 0

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
    avail = sorted([d for d in mc_paths if d <= date_str], reverse=True)
    if not avail: return []
    try:
        df = pd.read_parquet(mc_paths[avail[0]])
        if '시가총액' in df.columns:
            df = df[df['시가총액'] >= MIN_CAP * 1e8]
        df = df[~df.index.isin(finance_tickers)]
        if MIN_TV > 0:
            keep = [tk for tk in df.index if get_avg_tv(tk, date_str) >= MIN_TV]
            df = df.loc[df.index.isin(keep)]
        return list(df.index)
    except: return []

def get_sector_map(date_str):
    avail = sorted([d for d in sector_files if d <= date_str], reverse=True)
    if not avail: return {}
    try:
        df = pd.read_parquet(sector_files[avail[0]])
        for c in df.columns:
            if df[c].dtype == object: return df[c].to_dict()
    except: pass
    return {}

def calc_mom(date_str, rankings):
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
        mom_val = ret / vol if vol > 0 else np.nan
        tickers.append(tk); mom_raws.append(mom_val)
        kr_raws.append(kr_map.get(tk, 0)); secs.append(sec_map.get(tk, '기타'))
    if not tickers: return {}
    mom_z = sector_rank_zscore(pd.Series(mom_raws, index=tickers), pd.Series(secs, index=tickers))
    kr_z = sector_rank_zscore(pd.Series(kr_raws, index=tickers), pd.Series(secs, index=tickers))
    combined = (mom_z + kr_z) / 2
    if combined.std() > 0: combined = combined / combined.std()
    return combined.to_dict()

t0 = time.time()
modified = {}
for idx, date in enumerate(dates):
    orig = all_rankings[date]
    mz = calc_mom(date, orig)
    new_ranks = []
    for item in orig:
        ic = dict(item); tk = ic['ticker']
        if tk in mz and not np.isnan(mz[tk]): ic['momentum_s'] = mz[tk]
        new_ranks.append(ic)
    modified[date] = new_ranks

sim = ProductionSimulator(modified, dates, prices, bench)
r = sim.run(0.20, 0.20, 0.30, 0.30, g_rev=0.7, strategy='rank',
            entry_param=5, exit_param=15, max_slots=7, stop_loss=-0.10)
elapsed = time.time() - t0
print(f'CAP={MIN_CAP} TV={MIN_TV}  CAGR={r["cagr"]:5.1f}%  Sharpe={r["sharpe"]:.3f}  MDD={r["mdd"]:5.1f}%  ({elapsed:.0f}초)')
