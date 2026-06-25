# -*- coding: utf-8 -*-
import sys, io, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pidx={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)};parr=prices.values;pcol={c:i for i,c in enumerate(prices.columns)}
df=pd.read_parquet(P+'/backtest/_trap_entries.parquet')
def prior(tk,d,h):  # 진입前 h일 수익률 (양수=올라서 진입)
    if tk not in pcol or d not in pidx: return None
    i=pidx[d];ci=pcol[tk]
    if i-h<0: return None
    p0,p1=parr[i-h,ci],parr[i,ci]  # p0=과거, p1=진입일
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
df['pr60']=[prior(tk,d,60) for tk,d in zip(df['tk'],df['d'])]
df['pr120']=[prior(tk,d,120) for tk,d in zip(df['tk'],df['d'])]
df['이격20']=[prior(tk,d,20) for tk,d in zip(df['tk'],df['d'])]
v=df.dropna(subset=['f60']).copy()
print("=== 진입前 상승률 (양수=급등 후 매수=추격) ===")
for nm,g in [('승자(f60>0)',v[v['f60']>0]),('패자(f60<0)',v[v['f60']<0]),('큰손실(<-15)',v[v['f60']<-15])]:
    gp=g.dropna(subset=['pr60'])
    print(f"  {nm}: 진입前60일 평균 {gp['pr60'].mean():+.0f}%·중앙 {gp['pr60'].median():+.0f}%, +50%↑후매수 {(gp['pr60']>50).mean()*100:.0f}%, +100%↑ {(gp['pr60']>100).mean()*100:.0f}%")
# 이격 분위별 fwd60
print("\n=== 진입前 60일상승 분위별 fwd60 ===")
vv=v.dropna(subset=['pr60']).copy(); vv['pq']=pd.qcut(vv['pr60'],4,labels=['저(눌림)','Q2','Q3','고(급등후)'])
for q,g in vv.groupby('pq',observed=True):
    print(f"  {q}: 진입前 {g['pr60'].mean():+.0f}% → fwd60 {g['f60'].mean():+.1f}% 승률{(g['f60']>0).mean()*100:.0f}%")
# 큰손실 = 급등후 vs 눌림after
big=v[v['f60']<-15].dropna(subset=['pr60'])
print(f"\n  큰손실 63건: 급등후매수(pr60>30%) {(big['pr60']>30).mean()*100:.0f}% / 눌림매수(pr60<0) {(big['pr60']<0).mean()*100:.0f}%")
