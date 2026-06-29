# -*- coding: utf-8 -*-
import sqlite3, sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)}
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
NM=json.load(open(P+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
def nm(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in NM: return NM[k].get('shortName',t)
    return t
def ttm_eps(t):
    p=P+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(p) or t not in mc.index: return None
    fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    q=fs[(fs['공시구분']=='q')&(fs['계정']=='지배주주당기순이익')&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
    v=q['값'].astype(float).values
    if len(v)<4: return None
    sh=mc.loc[t,'상장주식수']; return (v[-4:].sum()*1e8)/sh if sh>0 else None
def ret(t,d0,d1):
    if t not in pcol or d0 not in pdi or d1 not in pdi: return None
    p0,p1=parr[pdi[d0],pcol[t]],parr[pdi[d1],pcol[t]]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
c=sqlite3.connect(P+'/kr_eps_momentum/eps_momentum_data_kr.db')
d0=sorted(r[0] for r in c.execute("SELECT DISTINCT date FROM ntm_screening WHERE date>='2026-06-01'"))[0]
df=pd.read_sql(f"SELECT ticker,ntm_current FROM ntm_screening WHERE date='{d0}'",c)
df['tk6']=df['ticker'].str[:6]
rows=[]
for _,r in df.iterrows():
    if not r['ntm_current'] or r['ntm_current']<=0: continue
    te=ttm_eps(r['tk6'])
    if te and te>0: rows.append((r['tk6'],r['ntm_current']/te))
g=pd.DataFrame(rows,columns=['tk6','gap']); g=g[g['gap']<15].sort_values('gap',ascending=False).head(15)
print(f"=== 기대성장 sleeve {d0} 진입 → 6/24 (15일) ===")
print(f"  {'#':>2} {'종목':12s}{'기대성장':>9s}{'6/24까지':>9s}")
tot=[]
for i,(_,r) in enumerate(g.iterrows(),1):
    rr=ret(r['tk6'],d0.replace('-',''),'20260624'); tot.append(rr)
    star=' ★top5' if i<=5 else ''
    print(f"  {i:>2} {nm(r['tk6'])[:12]:12s}{(r['gap']-1)*100:>+8.0f}%{(('%+.1f%%'%rr) if rr is not None else 'NA'):>9s}{star}")
v=[x for x in tot if x is not None]
print(f"\n  top5 평균 {np.mean(tot[:5]):+.1f}% / 전체15 평균 {np.mean(v):+.1f}%")
