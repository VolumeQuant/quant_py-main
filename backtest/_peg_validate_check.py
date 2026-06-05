"""pen_cs 구현 정확성 검증: base vs w01 비교 + 독립 재계산 대조."""
import glob, json, sys, bisect
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')

# 독립 재계산용 데이터
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

def load(label):
    out={}
    for f in sorted(glob.glob(f'backtest/_peg_val_{label}/ranking_*.json')):
        date=f.split('_')[-1].replace('.json','')
        items=json.load(open(f,encoding='utf-8'))
        items=items if isinstance(items,list) else items.get('rankings',[])
        out[date]={it['ticker']:it for it in items}
    return out

base=load('base'); w01=load('w01')
dates=sorted(set(base)&set(w01))
print(f'검증 날짜 {len(dates)}일')

# 1) overheat_pen 독립 재계산 대조 (한 날짜)
d0=dates[len(dates)//2]; dt=pd.Timestamp(d0)
print(f'\n=== [{d0}] overheat_pen 독립 재계산 대조 ===')
items=w01[d0]
# 독립 ey
recs={}
mc=get_mc(d0)
for tk,it in items.items():
    if tk not in mc.index: continue
    mcap=mc.loc[tk,'시가총액']
    ni=ttm_ni(tk,dt)
    if ni and ni>0 and mcap and mcap>0:
        recs[tk]=(ni*1e8)/mcap
eys=pd.Series(recs)
log_ey=np.log(eys); m,s=log_ey.mean(),log_ey.std()
indep_pen={tk: min((np.log(eys[tk])-m)/s,0.0) for tk in eys.index}
# 비교
diffs=[]
for tk,it in items.items():
    fg_pen=it.get('overheat_pen')
    ind=indep_pen.get(tk)
    if fg_pen is not None and ind is not None:
        diffs.append(abs(fg_pen-ind))
diffs=np.array(diffs)
print(f'  대조 종목수 {len(diffs)}, 평균|차| {diffs.mean():.4f}, 최대|차| {diffs.max():.4f}')
print('  (차이 큰 건 universe/필터 차이 — FG는 더 많은 필터 통과 종목으로 z 계산)')
# FG가 overheat_pen 단 종목 수 (음수)
n_pen=sum(1 for it in items.values() if it.get('overheat_pen',0)<0)
n_zero=sum(1 for it in items.values() if it.get('overheat_pen',1)==0)
print(f'  overheat_pen<0 (감점된 비싼 종목): {n_pen}, ==0: {n_zero}, 총 {len(items)}')

# 2) 점수 델타 = 0.1 × overheat_pen 확인
print(f'\n=== [{d0}] score 델타 = 0.1×pen 확인 (base vs w01) ===')
ok=0; bad=0
for tk,it in items.items():
    if tk not in base[d0]: continue
    pen=it.get('overheat_pen',0.0)
    exp_delta=0.1*pen
    act_delta=it.get('score',0)-base[d0][tk].get('score',0)
    if abs(act_delta-exp_delta)<0.001: ok+=1
    else: bad+=1
print(f'  델타 일치 {ok}, 불일치 {bad} (불일치는 다른요인; 대부분 일치 기대)')

# 3) 강등된 종목 = 비싼 종목인가 (rank 변화 vs overheat_pen)
print(f'\n=== top-3 변화 (base→w01) 전체 날짜 ===')
changed=0
for d in dates:
    b3=[tk for tk,it in sorted(base[d].items(),key=lambda x:x[1]['rank'])[:3]]
    w3=[tk for tk,it in sorted(w01[d].items(),key=lambda x:x[1]['rank'])[:3]]
    if b3!=w3:
        changed+=1
        # 빠진 종목의 pen
        dropped=[tk for tk in b3 if tk not in w3]
        for tk in dropped:
            pen=w01[d].get(tk,{}).get('overheat_pen','?')
            print(f'  {d}: top3에서 빠짐 {tk}({base[d][tk]["name"]}) pen={pen} | base#{base[d][tk]["rank"]}→w01#{w01[d].get(tk,{}).get("rank","out")}')
print(f'  top-3 변화 날짜: {changed}/{len(dates)}')
