"""유니버스 필터 그리드 — 사전캐시 기반 초고속
모멘텀 raw + K_ratio + 거래대금 + 시총 캐시 전부 활용
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
t0 = time.time()

# 캐시 로드
print('캐시 로드 중...', flush=True)
prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

with open(r'C:\dev\backtest\kr_full_cache.pkl', 'rb') as f:
    kr_cache = pickle.load(f)
with open(r'C:\dev\backtest\mom_raw_cache.pkl', 'rb') as f:
    mom_cache = pickle.load(f)
with open(r'C:\dev\backtest\tv_avg_cache.pkl', 'rb') as f:
    tv_cache = pickle.load(f)

# 시총 캐시
mc_cap = {}
for f in sorted(glob.glob(os.path.join(CACHE, 'market_cap_ALL_*.parquet'))):
    d = os.path.basename(f).split('_')[-1].replace('.parquet', '')
    if len(d) == 8:
        try:
            df = pd.read_parquet(f, columns=['시가총액'])
            mc_cap[d] = df['시가총액'].to_dict()
        except: continue

# 섹터 캐시
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
        except: continue

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

print(f'로드 완료: {time.time()-t0:.0f}초', flush=True)

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

def run_combo(min_cap, min_tv):
    """캐시 기반 조합 실행 — 가격 접근 0"""
    modified = {}
    for date in dates:
        # 유니버스 필터 (캐시에서)
        cap_d = max((d for d in mc_cap if d <= date), default=None)
        tv_d = max((d for d in tv_cache if d <= date), default=None)
        sec_d = max((d for d in sec_data if d <= date), default=None)
        if not cap_d: continue

        caps = mc_cap[cap_d]
        tvs = tv_cache.get(tv_d, {}) if tv_d else {}
        secs = sec_data.get(sec_d, {}) if sec_d else {}
        mom_raw = mom_cache.get(date, {})
        kr_raw = kr_cache.get(date, {})

        # 유니버스 필터링
        universe = []
        for tk in mom_raw:
            if caps.get(tk, 0) < min_cap * 1e8: continue
            if tk in finance_tickers: continue
            if min_tv > 0 and tvs.get(tk, 0) < min_tv: continue
            universe.append(tk)

        if not universe:
            modified[date] = all_rankings[date]
            continue

        # 섹터 내 rank z-score
        mom_ser = pd.Series({tk: mom_raw[tk] for tk in universe if tk in mom_raw})
        kr_ser = pd.Series({tk: kr_raw.get(tk, 0) for tk in universe})
        sec_ser = pd.Series({tk: secs.get(tk, '기타') for tk in universe})

        mom_z = sector_rank_zscore(mom_ser, sec_ser)
        kr_z = sector_rank_zscore(kr_ser, sec_ser)
        combined = (mom_z + kr_z) / 2
        if combined.std() > 0: combined = combined / combined.std()
        mz = combined.to_dict()

        # ranking 수정
        orig = all_rankings[date]
        new_ranks = []
        for item in orig:
            ic = dict(item); tk = ic['ticker']
            if tk in mz and not np.isnan(mz[tk]): ic['momentum_s'] = mz[tk]
            new_ranks.append(ic)
        modified[date] = new_ranks

    sim = ProductionSimulator(modified, dates, prices, bench)
    r = sim.run(0.20, 0.20, 0.30, 0.30, g_rev=0.7, strategy='rank',
                entry_param=5, exit_param=15, max_slots=7, stop_loss=-0.10)
    return r

# 그리드 실행
caps = [500, 1000, 1500, 2000]
tvs = [0, 10, 20, 30, 50]

print(f'\n=== 유니버스 필터 그리드 (금융업 제외 공통) ===')
header = "시총\\거래대금"
print(f'{header:<12s}', end='')
for tv in tvs:
    print(f'  TV≥{tv:<3d}', end='')
print()
print('-' * (12 + 8 * len(tvs)))

for cap in caps:
    line = f'CAP≥{cap:<7d}'
    for tv in tvs:
        ts = time.time()
        r = run_combo(cap, tv)
        elapsed = time.time() - ts
        line += f'  {r["sharpe"]:.3f}'
    print(line, flush=True)

# 상세 결과 (Sharpe 상위 5)
print(f'\n=== 상위 조합 상세 ===')
results = []
for cap in caps:
    for tv in tvs:
        r = run_combo(cap, tv)
        results.append({'cap': cap, 'tv': tv, 'cagr': r['cagr'], 'sharpe': r['sharpe'], 'mdd': r['mdd']})

results.sort(key=lambda x: -x['sharpe'])
print(f'{"CAP":>5} {"TV":>4}  CAGR   Sharpe  MDD')
for r in results[:8]:
    print(f'{r["cap"]:5d} {r["tv"]:4d}  {r["cagr"]:5.1f}%  {r["sharpe"]:.3f}   {r["mdd"]:5.1f}%')

print(f'\n총 소요: {time.time()-t0:.0f}초')
