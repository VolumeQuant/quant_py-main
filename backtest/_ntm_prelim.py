# -*- coding: utf-8 -*-
"""NTM 선행데이터 15일 예비검증 — NTM 리비전/score가 단기 fwd수익 예측하나. ★표본 극소·노이즈, 방향성만."""
import sqlite3, sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}
c=sqlite3.connect(P+'/kr_eps_momentum/eps_momentum_data_kr.db')
df=pd.read_sql('SELECT date,ticker,score,ntm_current,ntm_30d,is_turnaround FROM ntm_screening',c)
df['tk6']=df['ticker'].str[:6]
df['dt']=df['date'].str.replace('-','')
dates=sorted(df['dt'].unique())
print(f"NTM 데이터 {dates[0]}~{dates[-1]} {len(dates)}일, {df['tk6'].nunique()}종목")
def fwd(tk,d0,d1):
    if tk not in pcol or d0 not in pdi or d1 not in pdi: return None
    p0,p1=parr[pdi[d0],pcol[tk]],parr[pdi[d1],pcol[tk]]
    return (p1/p0-1)*100 if (p0>0 and p1>0) else None
END=dates[-1]
df['rev30']=np.where((df['ntm_30d']>0)&(df['ntm_current'].notna()), (df['ntm_current']/df['ntm_30d']-1)*100, np.nan)
# 풀드 — 각 (date,tk) → date~END 수익 (선행구간 ≥5일)
rows=[]
for _,r in df.iterrows():
    if r['dt']>=dates[-5]: continue  # 최소 5거래일 선행구간
    fr=fwd(r['tk6'], r['dt'], END)
    if fr is not None and pd.notna(r['rev30']):
        rows.append({'rev30':r['rev30'],'score':r['score'],'turn':r['is_turnaround'],'fwd':fr,'horizon':r['dt']})
o=pd.DataFrame(rows)
print(f"\n관측 {len(o)}건 (date~{END} 수익, 선행구간 5일+)  전체평균fwd {o['fwd'].mean():+.1f}%")
print("\n=== NTM 30일 리비전 분위별 fwd수익 ===")
o['q']=pd.qcut(o['rev30'],4,labels=['Q1하향','Q2','Q3','Q4상향'],duplicates='drop')
for q,g in o.groupby('q',observed=True):
    print(f"  {q}: n={len(g):>4} 리비전중앙{g['rev30'].median():+.1f}% → fwd {g['fwd'].mean():+.2f}% 승률{(g['fwd']>0).mean()*100:.0f}%")
print("\n=== 시스템 NTM score 분위별 ===")
o['sq']=pd.qcut(o['score'],4,labels=['Q1','Q2','Q3','Q4고'],duplicates='drop')
for q,g in o.groupby('sq',observed=True):
    print(f"  {q}: n={len(g):>4} score중앙{g['score'].median():.1f} → fwd {g['fwd'].mean():+.2f}% 승률{(g['fwd']>0).mean()*100:.0f}%")
# 상관
print(f"\n[상관] rev30 vs fwd: {o['rev30'].corr(o['fwd']):+.3f} / score vs fwd: {o['score'].corr(o['fwd']):+.3f}")
