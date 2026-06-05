# -*- coding: utf-8 -*-
"""production state/ (boost)에 pen fold (W=0.2) + weighted_rank 재계산.
- composite_rank = rank(score + 0.2*overheat_pen) — 가격반응 PER 과열캡 반영
- score 필드도 갱신, 나머지 필드(z서브팩터/per/pbr/roe/price) 보존
- weighted_rank: production _postprocess_ranking과 동일 (T-1/T-2 Top20 cr, penalty50, 0.4/0.35/0.25)
- defense/ 는 건드리지 않음 (pen은 boost only)
"""
import sys, json, glob, bisect, time
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()
W=0.2; PENALTY=50; STATE=Path('state')
mc_files={f.split('_')[-1].replace('.parquet',''):f for f in glob.glob('data_cache/market_cap_ALL_*.parquet')}
mc_keys=sorted(mc_files.keys()); _mcc={}
def mc_asof(ds):
    i=bisect.bisect_right(mc_keys,ds)-1
    if i<0: return None
    k=mc_keys[i]
    if k not in _mcc: _mcc[k]=pd.read_parquet(mc_files[k])['시가총액'].to_dict()
    return _mcc[k]
# TTM NI series (지배 우선, 당기 폴백) — FG와 동일 규칙
ttm={}
for f in glob.glob('data_cache/fs_dart_*.parquet'):
    tk=f.split('_')[-1].replace('.parquet','')
    try:
        d=pd.read_parquet(f); ni=d[d['계정'].isin(['지배주주당기순이익','당기순이익'])].copy()
        if ni.empty: continue
        ni['기준일']=pd.to_datetime(ni['기준일']); ni['rcept_dt']=pd.to_datetime(ni['rcept_dt'])
        pref=ni[ni['계정']=='지배주주당기순이익']
        use=pref if pref['기준일'].nunique()>=ni['기준일'].nunique()*0.6 else ni[ni['계정']=='당기순이익']
        if use.empty: use=ni
        q=use.sort_values('기준일').drop_duplicates('기준일',keep='last')
        if len(q)<4: continue
        vals=q['값'].values; rcs=q['rcept_dt'].values; ser=[]
        for i in range(3,len(q)): ser.append((pd.Timestamp(rcs[i]).strftime('%Y%m%d'),vals[i-3:i+1].sum()))
        ser.sort()
        if ser: ttm[tk]=ser
    except Exception: pass
def ttm_asof(tk,ds):
    s=ttm.get(tk)
    if not s: return None
    i=bisect.bisect_right([x[0] for x in s],ds)-1
    return s[i][1] if i>=0 else None

files=sorted(STATE.glob('ranking_*.json'))
files=[f for f in files if f.stem.replace('ranking_','').isdigit() and len(f.stem.replace('ranking_',''))==8]
print(f'대상 {len(files)} 파일',flush=True)

# Pass1: fold pen → score, composite_rank 갱신. cr_top20 맵 보관(날짜순)
cr_top20={}   # date -> {tk: new_cr} (cr<=20)
data_cache={}
n_changed=0
for fp in files:
    ds=fp.stem.replace('ranking_','')
    d=json.load(open(fp,encoding='utf-8'))
    rows=d.get('rankings',[])
    if not rows:
        data_cache[ds]=d; cr_top20[ds]={}; continue
    mc=mc_asof(ds)
    ey={}
    for r in rows:
        tk=str(r['ticker']).zfill(6)
        if mc is None: continue
        mcap=mc.get(tk,0); ni=ttm_asof(tk,ds)
        if mcap and mcap>0 and ni and ni>0: ey[tk]=(ni*1e8)/mcap
    pen={}
    if len(ey)>=20:
        le=np.log(pd.Series(ey)); m,s=le.mean(),le.std()
        if s>0:
            for tk in ey: pen[tk]=min((np.log(ey[tk])-m)/s,0.0)
    # fold + 새 score
    for r in rows:
        tk=str(r['ticker']).zfill(6)
        p=pen.get(tk,0.0)
        base=r.get('score',0.0) or 0.0
        r['overheat_pen']=round(p,4)
        r['score']=round(base + W*p, 4)
    # composite_rank = rank(new score) desc, method first
    order=sorted(range(len(rows)), key=lambda i:(-rows[i]['score'], i))
    for newcr,i in enumerate(order,1):
        rows[i]['composite_rank']=newcr
    cr_top20[ds]={str(r['ticker']).zfill(6):r['composite_rank'] for r in rows if r['composite_rank']<=20}
    data_cache[ds]=d
    n_changed+=1
print(f'Pass1 fold 완료: {n_changed} 파일, {time.time()-t0:.0f}s',flush=True)

# Pass2: weighted_rank 재계산 (production 동일)
dates=sorted(data_cache.keys())
for idx,ds in enumerate(dates):
    d=data_cache[ds]; rows=d.get('rankings',[])
    if not rows: continue
    prev=[x for x in dates if x<ds]
    t1=cr_top20.get(prev[-1],{}) if len(prev)>=1 else {}
    t2=cr_top20.get(prev[-2],{}) if len(prev)>=2 else {}
    for r in rows:
        tk=str(r['ticker']).zfill(6)
        r0=r.get('composite_rank',r.get('rank',PENALTY))
        r1=t1.get(tk,PENALTY); r2=t2.get(tk,PENALTY)
        r['weighted_rank']=round(r0*0.4+r1*0.35+r2*0.25,1)
    rows.sort(key=lambda x:(x['weighted_rank'], -x.get('score',0)))
    for i,r in enumerate(rows,1): r['rank']=i
    json.dump(d, open(STATE/f'ranking_{ds}.json','w',encoding='utf-8'), ensure_ascii=False)
print(f'Pass2 wr 재계산 + 저장 완료: {len(dates)} 파일, {time.time()-t0:.0f}s',flush=True)
