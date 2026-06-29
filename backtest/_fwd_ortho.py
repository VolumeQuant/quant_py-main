# -*- coding: utf-8 -*-
"""선행성장갭이 기존 팩터(growth/value/momentum/overheat)와 직교하나 — 추가가치 판정 + 과열캡 충돌 점검."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fp=pd.read_parquet(P+'/data_cache/consensus_forward_per.parquet').set_index('ticker')
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
st=json.load(open(sorted(glob.glob(P+'/state/ranking_*.json'))[-1],encoding='utf-8'))['rankings']
sd={x['ticker']:x for x in st}
def ttm_ni(t):
    p=P+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(p): return None
    fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    q=fs[(fs['공시구분']=='q')&(fs['계정']=='지배주주당기순이익')&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
    v=q['값'].astype(float).values; return v[-4:].sum() if len(v)>=4 else None
rows=[]
for t in fp.index:
    fper=fp.loc[t,'forward_per']
    if t not in mc.index or pd.isna(fper) or fper<=0: continue
    ni=ttm_ni(t); cap=mc.loc[t,'시가총액']
    if ni is None or ni<=0 or pd.isna(cap): continue
    tper=cap/(ni*1e8); gap=np.log(tper/fper)
    x=sd.get(t,{})
    rows.append({'t':t,'fwd_gap':gap,'growth':x.get('growth_s'),'value':x.get('value_s'),
                 'mom':x.get('mom_12m_s'),'overheat':x.get('overheat_pen'),'in_state':t in sd})
df=pd.DataFrame(rows)
print(f"매칭 {len(df)}종목 (state 내 {df['in_state'].sum()})")
d2=df.dropna(subset=['fwd_gap','growth'])
print(f"\n=== 선행성장갭 vs 기존팩터 상관 (직교=추가가치) ===")
for c in ['growth','value','mom','overheat']:
    dd=d2.dropna(subset=[c])
    if len(dd)>20: print(f"  fwd_gap vs {c:9s}: corr {dd['fwd_gap'].corr(dd[c]):+.3f} (n={len(dd)})")
# 과열캡 충돌: 고선행갭인데 과열캡 페널티 받는 종목 (인플렉션을 과열로 오인?)
print(f"\n=== 과열캡 충돌 점검: 선행갭 큰데 overheat 페널티 받는 종목 ===")
clash=d2[(d2['fwd_gap']>0.5)&(d2['overheat']<-0.1)].sort_values('fwd_gap',ascending=False)
for _,x in clash.head(8).iterrows():
    nm=sd.get(x['t'],{}).get('name',x['t'])
    print(f"  {nm[:12]:12s} 선행갭 {np.exp(x['fwd_gap'])-1:+.0%} 인데 overheat {x['overheat']:+.2f} (과열로 감점)")
