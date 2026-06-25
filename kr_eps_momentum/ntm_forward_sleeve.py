# -*- coding: utf-8 -*-
"""NTM 선행성장 sleeve + 검증 트래커 (별도 시스템, 2026-06-25).
ntm_screening(매일 누적) → 선행신호 랭킹 → 현재 픽 + 누적 OOS 예측력 측정.
신호: NTM리비전(추정상향) + 시스템score + 선행갭(후행PER/선행PER). 재실행 가능, 데이터 쌓일수록 검증력↑.
실행: python kr_eps_momentum/ntm_forward_sleeve.py  (언제든)"""
import sqlite3, sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=os.path.join(os.path.dirname(os.path.abspath(__file__)),'eps_momentum_data_kr.db')
px=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}
mc=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/market_cap_ALL_*.parquet'))[-1])
def z(s):
    s=pd.to_numeric(s,errors='coerce'); m,sd=s.median(),(s.quantile(.84)-s.quantile(.16))/2
    return ((s-m)/sd).clip(-3,3) if sd and sd>0 else s*0
def ttm_ni(tk6):
    p=ROOT+f'/data_cache/fs_dart_{tk6}.parquet'
    if not os.path.exists(p): return None
    fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    q=fs[(fs['공시구분']=='q')&(fs['계정']=='지배주주당기순이익')&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
    v=q['값'].astype(float).values; return v[-4:].sum() if len(v)>=4 else None
c=sqlite3.connect(DB)
df=pd.read_sql('SELECT date,ticker,rank,score,ntm_current,ntm_30d,is_turnaround FROM ntm_screening',c)
df['tk6']=df['ticker'].str[:6]; df['dt']=df['date'].str.replace('-','')
df['rev30']=np.where((df['ntm_30d']>0)&(df['ntm_current']>0),(df['ntm_current']/df['ntm_30d']-1)*100,np.nan)
dates=sorted(df['dt'].unique())
# 선행갭 (후행PER/선행PER) — 시총·종가·TTM순이익으로 (최신일만, 느림)
def fwd_gap(row):
    tk=row['tk6']
    if tk not in mc.index or not row['ntm_current'] or row['ntm_current']<=0: return np.nan
    px_=mc.loc[tk,'종가']; ni=ttm_ni(tk)
    if ni is None or ni<=0: return np.nan
    tper=mc.loc[tk,'시가총액']/(ni*1e8); fper=px_/row['ntm_current']
    return (tper/fper-1)*100 if fper>0 else np.nan
# === 1. 신호 합성 (일별 단면 z) ===
def make_signal(g):
    g=g.copy()
    g['sig']=z(g['rev30']).fillna(0)*0.5 + z(g['score']).fillna(0)*0.5
    return g
df=df.groupby('dt',group_keys=False).apply(make_signal)
# === 2. 누적 OOS 검증 (선행구간 가능한 것만) ===
END=dates[-1]
def fwd(tk,d0,d1):
    if tk not in pcol or d0 not in pdi or d1 not in pdi: return None
    p0,p1=parr[pdi[d0],pcol[tk]],parr[pdi[d1],pcol[tk]]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
obs=[]
for _,r in df.iterrows():
    if r['dt']>=dates[-5]: continue
    fr=fwd(r['tk6'],r['dt'],END)
    if fr is not None: obs.append({'sig':r['sig'],'fwd':fr})
o=pd.DataFrame(obs)
print(f"=== NTM 선행 sleeve 검증 ({dates[0]}~{END}, {len(dates)}일 누적) ===")
if len(o)>40:
    o['q']=pd.qcut(o['sig'],4,labels=['Q1약','Q2','Q3','Q4강'],duplicates='drop')
    print("  선행신호 분위별 fwd수익(누적):")
    for q,g in o.groupby('q',observed=True):
        print(f"    {q}: n={len(g):>4} fwd {g['fwd'].mean():+.2f}% 승률{(g['fwd']>0).mean()*100:.0f}%")
    print(f"  IC(신호 vs fwd): {o['sig'].corr(o['fwd']):+.3f}  ★데이터 {len(dates)}일=예비, 60일+이면 신뢰도↑")
# === 3. 현재 sleeve 픽 (최신일 top10) ===
g=df[df['dt']==END].copy().sort_values('sig',ascending=False)
g['fwd_gap']=g.apply(fwd_gap,axis=1)
print(f"\n=== 오늘({END}) NTM 선행 sleeve 픽 top10 ===")
nmmap=pd.read_sql('SELECT DISTINCT ticker FROM ntm_screening',c)
for _,r in g.head(10).iterrows():
    print(f"  {r['tk6']} sig{r['sig']:+.2f} (리비전{r['rev30']:+.0f}% score{r['score']:.0f}) 선행갭{('%.0f%%'%r['fwd_gap']) if pd.notna(r['fwd_gap']) else 'NA'} turn{r['is_turnaround']}")
# 픽 로그 저장 (OOS 추적용)
g.head(15)[['dt','tk6','sig','rev30','score','fwd_gap']].to_csv(ROOT+'/kr_eps_momentum/ntm_sleeve_picks_log.csv',mode='a',header=not os.path.exists(ROOT+'/kr_eps_momentum/ntm_sleeve_picks_log.csv'),index=False)
print(f"\n픽 로그 저장 → ntm_sleeve_picks_log.csv (재실행마다 누적 = OOS 추적)")
