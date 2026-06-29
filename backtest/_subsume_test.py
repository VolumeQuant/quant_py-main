# -*- coding: utf-8 -*-
"""'모멘텀이 선행성장 먹는다' 검증 — 모멘텀×선행성장 이중정렬. 통제 후 선행성장이 수익 예측하면 = 안 먹음."""
import sys, io, os, glob, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
def ttm(t,d):
    dd=cache.get(t)
    if dd is None: return None
    s=dd.get('ni') or dd.get('ni2')
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))]
    return v[-4:].sum() if len(v)>=4 else None
def pat(t,i):
    if t not in pcol or i<0 or i>=len(tdays): return None
    v=parr[i,pcol[t]]; return v if v>0 else None
tks=list(cache.keys())
rows=[]
sample=[d for k,d in enumerate(tdays) if '20190102'<=d<='20250601' and k%10==0]
for d in sample:
    i=tdi[d]
    for t in tks:
        p0,pm,pf=pat(t,i),pat(t,i-250),pat(t,i+120)  # 현재, 12m전, 120일후
        if p0 is None or pm is None or pf is None: continue
        e0=ttm(t,d); e1=ttm(t,tdays[min(i+250,len(tdays)-1)])
        if e0 is None or e0<=0 or e1 is None: continue
        rows.append({'mom':p0/pm-1,'fg':e1/e0-1,'ret':(pf/p0-1)*100})
df=pd.DataFrame(rows)
print(f"관측 {len(df)}건 (2019~2025, 817종목 샘플)\n")
print(f"[직교성] 모멘텀 vs 선행성장 상관: {df['mom'].corr(df['fg']):+.3f}  (낮을수록 다른 정보)")
print(f"[단독 IC(fwd120)] 모멘텀 {df['mom'].corr(df['ret'],method='spearman'):+.3f} / 선행성장 {df['fg'].corr(df['ret'],method='spearman'):+.3f}\n")
df['mq']=pd.qcut(df['mom'],3,labels=['모멘L','모멘M','모멘H'])
df['fq']=pd.qcut(df['fg'],3,labels=['선행L','선행M','선행H'])
print("=== 이중정렬: 모멘텀(행) × 선행성장(열) 평균 fwd120 수익 ===")
piv=df.pivot_table('ret','mq','fq',aggfunc='mean',observed=True)
print(piv.round(1).to_string())
print("\n=== 각 모멘텀 구간 내 선행성장 H−L 스프레드 (양수면 모멘텀이 못 먹음=선행성장 독립예측) ===")
for mq in ['모멘L','모멘M','모멘H']:
    sub=df[df['mq']==mq]
    hi=sub[sub['fq']=='선행H']['ret'].mean(); lo=sub[sub['fq']=='선행L']['ret'].mean()
    print(f"  {mq}: 선행H {hi:+.1f}% − 선행L {lo:+.1f}% = {hi-lo:+.1f}%p")
