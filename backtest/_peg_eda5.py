"""EDA5: 전략 관점 게이트 — score + W*ey_z 재랭킹 시 TOP-N 미래수익 개선?
실제 매매는 top-3 by score. ey_z 가산이 상위 픽을 개선하는지가 진짜 질문.
또한 value_trap 우려: 극단 cheap 제외(winsor) 효과도 확인.
"""
import glob, sys, json, time, bisect
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()

ohlcv = pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2017*_*.parquet'))[-1]).sort_index()
mc_files = {f.split('_')[-1].replace('.parquet',''):f for f in glob.glob('data_cache/market_cap_ALL_*.parquet')}
mc_dates = sorted(mc_files.keys())
def get_mc(ds):
    i=bisect.bisect_right(mc_dates,ds)-1
    return (pd.read_parquet(mc_files[mc_dates[i]]) if i>=0 else None)

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

def zsc(s):
    s=s.astype(float); sd=s.std(); return (s-s.mean())/sd if sd>0 else s*0

json_files=sorted(glob.glob('state/ranking_2023*.json')+glob.glob('state/ranking_2024*.json'))
sample=json_files[::6]   # 더 촘촘히
print(f'표본 {len(sample)}일',flush=True)

# 날짜별로 후보 모으고 재랭킹
Ws=[0.0,0.1,0.2,0.3,0.5,0.8]
topN_ret={ (w,N):[] for w in Ws for N in [3,5,10] }
topN_ret_cap={ (w,N):[] for w in Ws for N in [3,5] }  # 극단cheap winsor

for jf in sample:
    date=jf.split('_')[-1].replace('.json','')
    dt=pd.Timestamp(date)
    if dt not in ohlcv.index: continue
    di=ohlcv.index.get_loc(dt)
    if di+20>=len(ohlcv.index): continue
    c0=ohlcv.iloc[di]; c20=ohlcv.iloc[di+20]
    mc=get_mc(date)
    if mc is None: continue
    items=json.load(open(jf,encoding='utf-8'))
    items=items if isinstance(items,list) else items.get('rankings',[])
    recs=[]
    for it in items:
        tk=it['ticker']; sc=it.get('score')
        if sc is None: continue
        if tk not in mc.index: continue
        mcap=mc.loc[tk,'시가총액']
        if not mcap or mcap<=0: continue
        ni=ttm_ni(tk,dt)
        if ni is None or ni<=0: continue
        ey=(ni*1e8)/mcap
        cc0=c0.get(tk); cc20=c20.get(tk)
        if not cc0 or not cc20 or pd.isna(cc0) or pd.isna(cc20) or cc0<=0: continue
        recs.append({'tk':tk,'score':sc,'ey':ey,'fwd':cc20/cc0-1})
    if len(recs)<30: continue
    g=pd.DataFrame(recs)
    g['ey_z']=zsc(np.log(g['ey'].clip(lower=1e-4)))
    # winsor: ey_z 상위 2%(극단 cheap=value trap 후보) 캡
    g['ey_z_cap']=g['ey_z'].clip(upper=g['ey_z'].quantile(0.98))
    for w in Ws:
        g['ns']=g['score']+w*g['ey_z']
        gg=g.sort_values('ns',ascending=False)
        for N in [3,5,10]:
            topN_ret[(w,N)].append(gg['fwd'].head(N).mean())
        g['nsc']=g['score']+w*g['ey_z_cap']
        ggc=g.sort_values('nsc',ascending=False)
        for N in [3,5]:
            topN_ret_cap[(w,N)].append(ggc['fwd'].head(N).mean())

print(f'\n유효 표본일 {len(topN_ret[(0.0,3)])}, {time.time()-t0:.0f}s')
print('\n=== TOP-N 평균 fwd20 수익률 (score + W*ey_z 재랭킹) ===')
print(f'{"W":>5} {"top3":>9} {"top5":>9} {"top10":>9}')
for w in Ws:
    r3=np.mean(topN_ret[(w,3)]); r5=np.mean(topN_ret[(w,5)]); r10=np.mean(topN_ret[(w,10)])
    print(f'{w:>5} {r3:>+9.4f} {r5:>+9.4f} {r10:>+9.4f}')
print('\n=== winsor(극단cheap 2% 캡) TOP-N fwd20 ===')
print(f'{"W":>5} {"top3":>9} {"top5":>9}')
for w in Ws:
    r3=np.mean(topN_ret_cap[(w,3)]); r5=np.mean(topN_ret_cap[(w,5)])
    print(f'{w:>5} {r3:>+9.4f} {r5:>+9.4f}')

# 승률(표본일 중 W>0가 W=0 이기는 비율)
print('\n=== top3 표본일별 W vs W=0 승률 ===')
base=np.array(topN_ret[(0.0,3)])
for w in Ws[1:]:
    arr=np.array(topN_ret[(w,3)])
    print(f'  W={w}: 평균차 {np.mean(arr-base):+.4f}, 승률 {(arr>base).mean():.0%}')
