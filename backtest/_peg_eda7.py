"""EDA7: 비대칭 과열 페널티 (사용자 '가격 폭등' 우려 직접 대응).
- 싼 건 보상 안 하고, '과열'(PE 급팽창 or 단면 초고평가)만 감점 → top-3 모멘텀 승자 보호하며 거품만 회피?
- pen_ts = min(0, -pe_chg60_z)  (PE 팽창 상위만 음수)
- pen_cs = min(0, ey_z)         (단면 초고평가만 음수)
- 과열 상위 X%만 감점하는 hard 버전도.
"""
import glob, sys, json, time, bisect
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()

ohlcv = pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2017*_*.parquet'))[-1]).sort_index()
oidx=ohlcv.index
mc_files={f.split('_')[-1].replace('.parquet',''):f for f in glob.glob('data_cache/market_cap_ALL_*.parquet')}
mc_dates=sorted(mc_files.keys()); _mcc={}
def get_mc(ds):
    i=bisect.bisect_right(mc_dates,ds)-1
    if i<0: return None
    k=mc_dates[i]
    if k not in _mcc: _mcc[k]=pd.read_parquet(mc_files[k])
    return _mcc[k]
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
    for a in ['지배주주당기순이익','당기순이익']:
        sub=vis[vis['계정']==a]
        if sub.empty: continue
        sub=sub.sort_values('기준일').drop_duplicates('기준일',keep='last').tail(4)
        if len(sub)>=4: return sub['값'].sum()
    return None
def sper(tk,ds,dt):
    mc=get_mc(ds)
    if mc is None or tk not in mc.index: return None
    m=mc.loc[tk,'시가총액']
    if not m or m<=0: return None
    ni=ttm_ni(tk,dt)
    if ni is None or ni<=0: return None
    return m/(ni*1e8)
def zsc(s):
    s=s.astype(float); sd=s.std(); return (s-s.mean())/sd if sd>0 else s*0

sample=(sorted(glob.glob('state/ranking_2023*.json')+glob.glob('state/ranking_2024*.json')))[::6]
Ws=[0.0,0.1,0.2,0.3,0.5]
res={k:{(w,N):[] for w in Ws for N in [3,5]} for k in ['pen_ts','pen_cs','pen_hard']}
base_store=[]
for jf in sample:
    date=jf.split('_')[-1].replace('.json',''); dt=pd.Timestamp(date)
    if dt not in oidx: continue
    di=oidx.get_loc(dt)
    if di+20>=len(oidx) or di-60<0: continue
    c0=ohlcv.iloc[di]; c20=ohlcv.iloc[di+20]
    dt_l=oidx[di-60]; ds_l=dt_l.strftime('%Y%m%d')
    items=json.load(open(jf,encoding='utf-8'))
    items=items if isinstance(items,list) else items.get('rankings',[])
    recs=[]
    for it in items:
        tk=it['ticker']; sc=it.get('score')
        if sc is None: continue
        spn=sper(tk,date,dt); spo=sper(tk,ds_l,dt_l)
        if not spn or not spo: continue
        cc0=c0.get(tk); cc20=c20.get(tk)
        if not cc0 or not cc20 or pd.isna(cc0) or pd.isna(cc20) or cc0<=0: continue
        recs.append({'tk':tk,'score':sc,'pe_chg':spn/spo-1,'ey':(spn and 1.0/spn),'fwd':cc20/cc0-1})
    if len(recs)<30: continue
    g=pd.DataFrame(recs)
    g['pe_chg_z']=zsc(g['pe_chg'].clip(-0.8,3.0))
    g['ey_z']=zsc(np.log((1.0/ (1.0/g['ey'])).clip(lower=1e-4))) if False else zsc(np.log(g['ey'].clip(lower=1e-6)))
    # 과열만 감점: PE 팽창 상위 => pe_chg_z 양수 => 신호 음수
    g['pen_ts']=-np.clip(g['pe_chg_z'],0,None)
    # 단면 초고평가만 감점: ey 낮음 => ey_z 음수 => 그대로 (음수만 살림)
    g['pen_cs']=np.clip(g['ey_z'],None,0)
    # hard: pe_chg 상위 15%만 -1
    thr=g['pe_chg'].quantile(0.85)
    g['pen_hard']=np.where(g['pe_chg']>=thr,-1.0,0.0)
    base3=g.sort_values('score',ascending=False)['fwd'].head(3).mean()
    base_store.append(base3)
    for key in res:
        for w in Ws:
            g['ns']=g['score']+w*g[key]
            gg=g.sort_values('ns',ascending=False)
            for N in [3,5]:
                res[key][(w,N)].append(gg['fwd'].head(N).mean())

base=np.array(base_store)
print(f'\n유효일 {len(base)}, baseline top3 {base.mean():+.4f}, {time.time()-t0:.0f}s')
for key in ['pen_ts','pen_cs','pen_hard']:
    print(f'\n=== {key} (과열 감점만) ===')
    print(f'  {"W":>5} {"top3":>9} {"top5":>9}  승률(top3 vs base)')
    for w in Ws:
        a3=np.array(res[key][(w,3)]); a5=np.array(res[key][(w,5)])
        wr=f'{(a3>=base).mean():.0%}' if w>0 else ''
        print(f'  {w:>5} {a3.mean():>+9.4f} {a5.mean():>+9.4f}  {wr}')
