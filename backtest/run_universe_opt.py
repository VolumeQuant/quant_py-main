"""유니버스 필터 최적화 — 시총/거래대금 기준별 모멘텀 섹터 z-score 성과
6M/Vol 모멘텀 고정, 유니버스 필터만 변경
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

prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

# K_ratio 캐시
with open(r'C:\dev\backtest\kr_full_cache.pkl', 'rb') as f:
    kr_cache = pickle.load(f)
print(f'K_ratio 캐시: {len(kr_cache)}일', flush=True)

# market_cap 파일
mc_paths = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        mc_paths[d] = f

# 섹터 파일
sector_files = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'krx_sector_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        sector_files[d] = f

# rankings
all_rankings = {}
for y in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{y}/ranking_*.json'))):
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[d] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())

# 금융업 종목 캐시 (섹터 파일에서)
finance_tickers = set()
for d in sorted(sector_files.keys(), reverse=True)[:5]:
    try:
        df = pd.read_parquet(sector_files[d])
        for col in df.columns:
            if df[col].dtype == object:
                fin_mask = df[col].str.contains('금융|은행|보험|증권|캐피탈', na=False)
                finance_tickers.update(df[fin_mask].index.tolist())
                break
    except:
        continue
print(f'금융업 종목: {len(finance_tickers)}개', flush=True)

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

def get_filtered_universe(date_str, min_cap, exclude_finance=True):
    avail = sorted([d for d in mc_paths if d <= date_str], reverse=True)
    if not avail:
        return []
    try:
        df = pd.read_parquet(mc_paths[avail[0]])
        if '시가총액' in df.columns:
            df = df[df['시가총액'] >= min_cap * 1e8]
        if exclude_finance:
            df = df[~df.index.isin(finance_tickers)]
        return list(df.index)
    except:
        return []

def get_sector_map(date_str):
    avail = sorted([d for d in sector_files if d <= date_str], reverse=True)
    if not avail:
        return {}
    try:
        df = pd.read_parquet(sector_files[avail[0]])
        for c in df.columns:
            if df[c].dtype == object:
                return df[c].to_dict()
    except:
        pass
    return {}

def calc_mom_filtered(date_str, rankings, min_cap, exclude_finance):
    dt = pd.Timestamp(date_str)
    if dt not in prices.index:
        return {}
    universe = get_filtered_universe(date_str, min_cap, exclude_finance)
    sec_map = get_sector_map(date_str)
    if not universe:
        return {}
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
        tickers.append(tk)
        mom_raws.append(mom_val)
        kr_raws.append(kr_map.get(tk, 0))
        secs.append(sec_map.get(tk, '기타'))
    if not tickers:
        return {}
    mom_z = sector_rank_zscore(pd.Series(mom_raws, index=tickers), pd.Series(secs, index=tickers))
    kr_z = sector_rank_zscore(pd.Series(kr_raws, index=tickers), pd.Series(secs, index=tickers))
    combined = (mom_z + kr_z) / 2
    if combined.std() > 0:
        combined = combined / combined.std()
    return combined.to_dict()

# 테스트 조합
configs = [
    ('전체(필터없음)',    0,    False),
    ('금융제외만',        0,    True),
    ('500억+금융제외',    500,  True),
    ('1000억+금융제외',   1000, True),   # 현행
    ('1500억+금융제외',   1500, True),
    ('2000억+금융제외',   2000, True),
    ('3000억+금융제외',   3000, True),
]

print(f'\n=== 유니버스 필터 최적화 (6M/Vol 모멘텀 고정) ===')
print(f'{"필터":<18s}  CAGR   Sharpe  Sortino  MDD    유니버스')
print('-' * 65)

for label, min_cap, exc_fin in configs:
    t0 = time.time()
    modified = {}
    avg_univ = []
    for date in dates:
        orig = all_rankings[date]
        mz = calc_mom_filtered(date, orig, min_cap, exc_fin)
        avg_univ.append(len(get_filtered_universe(date, min_cap, exc_fin)))
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
    au = int(np.mean(avg_univ))
    elapsed = time.time() - t0
    print(f'{label:<18s}  {r["cagr"]:5.1f}%  {r["sharpe"]:.3f}   {r["sortino"]:.3f}   {r["mdd"]:5.1f}%  ~{au}종목  ({elapsed:.0f}초)')

print('\n완료')
