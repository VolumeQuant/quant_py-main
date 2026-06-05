"""EDA6: 시계열 괴리 (US fwd_pe_chg의 KR 대응) — 자기 PER 압축.
self_per(t)=시총(t)/TTM_NI(t). pe_chg_k = self_per(t)/self_per(t-k)-1.
음수(PE 압축=실적이 주가 앞섬)=저평가 신호. signal = -pe_chg_z.
top-3/5 tilt 로 baseline 대비 개선되는지 (전략 관점).
"""
import glob, sys, json, time, bisect
import pandas as pd, numpy as np
from scipy import stats
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()

ohlcv = pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2017*_*.parquet'))[-1]).sort_index()
oidx = ohlcv.index
mc_files = {f.split('_')[-1].replace('.parquet',''):f for f in glob.glob('data_cache/market_cap_ALL_*.parquet')}
mc_dates = sorted(mc_files.keys())
_mc_cache={}
def get_mc(ds):
    i=bisect.bisect_right(mc_dates,ds)-1
    if i<0: return None
    key=mc_dates[i]
    if key not in _mc_cache: _mc_cache[key]=pd.read_parquet(mc_files[key])
    return _mc_cache[key]

fs_cache={}
for f in glob.glob('data_cache/fs_dart_*.parquet'):
    tk=f.split('_')[-1].replace('.parquet','')
    try:
        d=pd.read_parquet(f); ni=d[d['계정'].isin(['지배주주당기순이익','당기순이익'])].copy()
        if ni.empty: continue
        ni['rcept_dt']=pd.to_datetime(ni['rcept_dt']); ni['기준일']=pd.to_datetime(ni['기준일'])
        fs_cache[tk]=ni
    except Exception: pass

def ttm_ni(tk,asof):
    d=fs_cache.get(tk)
    if d is None: return None
    vis=d[d['rcept_dt']<=asof]
    if vis.empty: return None
    for acct in ['지배주주당기순이익','당기순이익']:
        sub=vis[vis['계정']==acct]
        if sub.empty: continue
        sub=sub.sort_values('기준일').drop_duplicates('기준일',keep='last').tail(4)
        if len(sub)>=4: return sub['값'].sum()
    return None

def self_per(tk,ds,dt):
    mc=get_mc(ds)
    if mc is None or tk not in mc.index: return None
    mcap=mc.loc[tk,'시가총액']
    if not mcap or mcap<=0: return None
    ni=ttm_ni(tk,dt)
    if ni is None or ni<=0: return None
    return mcap/(ni*1e8)

def zsc(s):
    s=s.astype(float); sd=s.std(); return (s-s.mean())/sd if sd>0 else s*0

json_files=sorted(glob.glob('state/ranking_2023*.json')+glob.glob('state/ranking_2024*.json'))
sample=json_files[::6]
print(f'표본 {len(sample)}일',flush=True)

LAGS=[20,60]
Ws=[0.0,0.1,0.2,0.3,0.5]
top_ret={(lag,w,N):[] for lag in LAGS for w in Ws for N in [3,5]}
ic_store={lag:[] for lag in LAGS}

for jf in sample:
    date=jf.split('_')[-1].replace('.json','')
    dt=pd.Timestamp(date)
    if dt not in oidx: continue
    di=oidx.get_loc(dt)
    if di+20>=len(oidx): continue
    c0=ohlcv.iloc[di]; c20=ohlcv.iloc[di+20]
    items=json.load(open(jf,encoding='utf-8'))
    items=items if isinstance(items,list) else items.get('rankings',[])
    base={}
    for lag in LAGS:
        if di-lag<0: continue
        dt_lag=oidx[di-lag]; ds_lag=dt_lag.strftime('%Y%m%d')
        recs=[]
        for it in items:
            tk=it['ticker']; sc=it.get('score')
            if sc is None: continue
            sp_now=self_per(tk,date,dt)
            sp_old=self_per(tk,ds_lag,dt_lag)
            if not sp_now or not sp_old: continue
            cc0=c0.get(tk); cc20=c20.get(tk)
            if not cc0 or not cc20 or pd.isna(cc0) or pd.isna(cc20) or cc0<=0: continue
            pe_chg=sp_now/sp_old-1
            recs.append({'tk':tk,'score':sc,'pe_chg':pe_chg,'fwd':cc20/cc0-1})
        if len(recs)<30: continue
        g=pd.DataFrame(recs)
        g['sig']=-zsc(g['pe_chg'].clip(-0.8,3.0))   # PE 압축(음수)=양수 신호
        # IC
        ic=stats.spearmanr(g['sig'],g['fwd']).correlation
        if not np.isnan(ic): ic_store[lag].append(ic)
        for w in Ws:
            g['ns']=g['score']+w*g['sig']
            gg=g.sort_values('ns',ascending=False)
            for N in [3,5]:
                top_ret[(lag,w,N)].append(gg['fwd'].head(N).mean())

print(f'\n{time.time()-t0:.0f}s')
for lag in LAGS:
    print(f'\n=== LAG {lag}d: 시계열 PE압축 신호 ===')
    print(f'  rank-IC(fwd20) 평균: {np.mean(ic_store[lag]):+.4f} (n={len(ic_store[lag])})')
    print(f'  {"W":>5} {"top3":>9} {"top5":>9}  (유효일 {len(top_ret[(lag,0.0,3)])})')
    base3=np.array(top_ret[(lag,0.0,3)])
    for w in Ws:
        r3=np.mean(top_ret[(lag,w,3)]); r5=np.mean(top_ret[(lag,w,5)])
        arr3=np.array(top_ret[(lag,w,3)])
        wr=f'승률{(arr3>base3).mean():.0%}' if w>0 else ''
        print(f'  {w:>5} {r3:>+9.4f} {r5:>+9.4f}  {wr}')
