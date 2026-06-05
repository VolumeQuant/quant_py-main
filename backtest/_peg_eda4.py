"""EDA4: 성장-밸류 괴리(KR판 PEG) 알파 검증 (표본).
- 가격반응 valuation: ey = TTM_지배NI(PIT) / 시가총액(일별)  → 높을수록 저평가(cheap)
- 성장: JSON growth_s (PIT)
- 괴리 후보: growth_z+ey_z 가산 / 잔차(true 괴리) / 상호작용
- 평가: rank-IC vs forward 20·60일 수익률, 분위 스프레드
- 비교 baseline: 현재 score, growth 단독, ey 단독 (괴리가 marginal 위에 추가 알파 주는지)
"""
import glob, sys, json, time
import pandas as pd, numpy as np
from scipy import stats
sys.stdout.reconfigure(encoding='utf-8')

t0 = time.time()
PROJ = '.'

# ---- all_ohlcv (forward returns) ----
ohlcv = pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2017*_*.parquet'))[-1])
ohlcv = ohlcv.sort_index()
ohlcv_dates = list(ohlcv.index)

# ---- market_cap files index ----
mc_files = {f.split('_')[-1].replace('.parquet',''): f
            for f in glob.glob('data_cache/market_cap_ALL_*.parquet')}
mc_dates_sorted = sorted(mc_files.keys())

def get_mc(date_str):
    """date_str(YYYYMMDD) 이하 가장 가까운 market_cap."""
    import bisect
    i = bisect.bisect_right(mc_dates_sorted, date_str) - 1
    if i < 0: return None
    return pd.read_parquet(mc_files[mc_dates_sorted[i]]), mc_dates_sorted[i]

# ---- fs_dart preload (지배NI 우선, 당기순이익 폴백) ----
print('fs_dart 로딩...', flush=True)
fs_cache = {}
for f in glob.glob('data_cache/fs_dart_*.parquet'):
    tk = f.split('_')[-1].replace('.parquet','')
    try:
        df = pd.read_parquet(f)
        ni = df[df['계정'].isin(['지배주주당기순이익','당기순이익'])].copy()
        if ni.empty: continue
        ni['rcept_dt'] = pd.to_datetime(ni['rcept_dt'])
        ni['기준일'] = pd.to_datetime(ni['기준일'])
        fs_cache[tk] = ni
    except Exception:
        pass
print(f'  {len(fs_cache)} 종목 NI 로드 ({time.time()-t0:.0f}s)', flush=True)

def ttm_ni(tk, asof):
    """asof(Timestamp) 시점 PIT TTM 지배NI (억원). rcept_dt<=asof 인 분기만."""
    d = fs_cache.get(tk)
    if d is None: return None
    vis = d[d['rcept_dt'] <= asof]
    if vis.empty: return None
    # 지배주주당기순이익 우선
    for acct in ['지배주주당기순이익','당기순이익']:
        sub = vis[vis['계정']==acct]
        if sub.empty: continue
        # 분기별: 기준일 desc 최근 4개 (각 분기 단일 값)
        sub = sub.sort_values('기준일').drop_duplicates('기준일', keep='last')
        last4 = sub.tail(4)
        if len(last4) >= 4:
            return last4['값'].sum()
    return None

# ---- 표본 날짜: 2023~2024 중 10거래일 간격 ----
json_files = sorted(glob.glob('state/ranking_2023*.json') + glob.glob('state/ranking_2024*.json'))
sample_files = json_files[::10]
print(f'표본 날짜 {len(sample_files)}개', flush=True)

rows = []
for jf in sample_files:
    date = jf.split('_')[-1].replace('.json','')
    dt = pd.Timestamp(date)
    if dt not in ohlcv.index: continue
    # forward 20/60 returns
    di = ohlcv.index.get_loc(dt)
    if di + 60 >= len(ohlcv.index): continue
    p0 = ohlcv.iloc[di]
    p20 = ohlcv.iloc[di+20]
    p60 = ohlcv.iloc[di+60]
    mcres = get_mc(date)
    if mcres is None: continue
    mc, mcd = mcres
    d = json.load(open(jf, encoding='utf-8'))
    items = d if isinstance(d, list) else d.get('rankings', [])
    for it in items:
        tk = it['ticker']
        g = it.get('growth_s')
        if g is None: continue
        if tk not in mc.index: continue
        mcap = mc.loc[tk, '시가총액']
        if not mcap or mcap <= 0: continue
        ni = ttm_ni(tk, dt)
        if ni is None or ni <= 0: continue   # 적자 제외 (PER 의미X)
        ey = (ni * 1e8) / mcap   # earnings yield (TTM NI / mcap), 높을수록 cheap
        # forward returns
        if tk not in ohlcv.columns: continue
        c0 = p0.get(tk); c20 = p20.get(tk); c60 = p60.get(tk)
        if not c0 or not c20 or pd.isna(c0) or pd.isna(c20) or c0<=0: continue
        fwd20 = c20/c0 - 1
        fwd60 = (c60/c0 - 1) if (c60 and not pd.isna(c60) and c0>0) else np.nan
        rows.append({'date':date,'tk':tk,'growth':g,'ey':ey,
                     'value_s':it.get('value_s'),'score':it.get('score'),
                     'fwd20':fwd20,'fwd60':fwd60})

df = pd.DataFrame(rows)
print(f'\n관측치 {len(df)}개, 날짜 {df["date"].nunique()}개 ({time.time()-t0:.0f}s)', flush=True)

# ---- 날짜별 cross-sectional z & 괴리 신호 ----
def zsc(s):
    s = s.astype(float)
    sd = s.std()
    return (s - s.mean())/sd if sd>0 else s*0

sigs = {}
parts = []
for date, g in df.groupby('date'):
    g = g.copy()
    g['growth_z'] = zsc(g['growth'])
    g['ey_z'] = zsc(np.log(g['ey'].clip(lower=1e-4)))   # log ey (분포 왜곡 완화)
    g['value_z'] = zsc(g['value_s'].fillna(0))
    # C1 additive (성장+저평가 동등)
    g['C1_add'] = g['growth_z'] + g['ey_z']
    # C3 residual: ey_z ~ growth_z 회귀 잔차 (성장 대비 싼 정도 = 진짜 괴리)
    if g['growth_z'].std()>0:
        b = np.polyfit(g['growth_z'], g['ey_z'], 1)
        g['C3_resid'] = g['ey_z'] - (b[0]*g['growth_z']+b[1])
    else:
        g['C3_resid'] = 0.0
    # C4 interaction: 성장>0 & 저평가 동시
    g['C4_inter'] = np.where(g['growth_z']>0, g['growth_z']*g['ey_z'], 0.0)
    # C5 PEG-rank: 성장상위 가중 저평가
    parts.append(g)
allg = pd.concat(parts)

# ---- rank-IC (Spearman) per date, then mean ----
def mean_ic(signal, fwd):
    ics = []
    for date, g in allg.groupby('date'):
        sub = g[[signal,fwd]].dropna()
        if len(sub) < 20: continue
        ic = stats.spearmanr(sub[signal], sub[fwd]).correlation
        if not np.isnan(ic): ics.append(ic)
    return np.mean(ics), np.std(ics), len(ics)

print('\n=== rank-IC (per-date Spearman, 평균) ===')
print(f'{"signal":<12} {"IC_fwd20":>10} {"IC_fwd60":>10}  n')
for sig in ['growth_z','ey_z','value_z','C1_add','C3_resid','C4_inter','score']:
    if sig not in allg.columns: continue
    m20,s20,n20 = mean_ic(sig,'fwd20')
    m60,s60,n60 = mean_ic(sig,'fwd60')
    print(f'{sig:<12} {m20:>+10.4f} {m60:>+10.4f}  {n20}')

# ---- 분위 스프레드 (C1_add Q5-Q1, fwd20) ----
print('\n=== C1_add 5분위 평균 fwd20 (날짜별 분위→풀) ===')
allg['q'] = allg.groupby('date')['C1_add'].transform(lambda s: pd.qcut(s.rank(method='first'),5,labels=False))
print(allg.groupby('q')['fwd20'].mean())
print('Q5-Q1 spread:', allg[allg.q==4]['fwd20'].mean()-allg[allg.q==0]['fwd20'].mean())

print('\n=== growth_z 단독 5분위 fwd20 (비교) ===')
allg['qg'] = allg.groupby('date')['growth_z'].transform(lambda s: pd.qcut(s.rank(method='first'),5,labels=False))
print(allg.groupby('qg')['fwd20'].mean())
print('Q5-Q1 spread:', allg[allg.qg==4]['fwd20'].mean()-allg[allg.qg==0]['fwd20'].mean())
print(f'\n총 {time.time()-t0:.0f}s')
