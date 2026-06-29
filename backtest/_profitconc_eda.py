# -*- coding: utf-8 -*-
"""이익 일회성(profit concentration) 필터 EDA — 매수권 종목 fwd수익률을 일회성집중도로 split.
conc = max(최근4분기 지배순이익)/TTM. PIT(rcept_dt). 금호류 잡고 제주류 살리나?"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan)
# state 로드 (rank, ticker, name)
days={}; dall=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        days[dt]={r['ticker']:r for r in json.load(open(f,encoding='utf-8'))['rankings']}; dall.append(dt)
dall=sorted(dall)
tickers=set()
for d in dall: tickers|=set(days[d].keys())
# 종목별 분기 지배순이익 시계열 (rcept_dt PIT)
prof={}
for tk in tickers:
    fp=os.path.join(PROJ,'data_cache',f'fs_dart_{tk}.parquet')
    if not os.path.exists(fp): continue
    df=pd.read_parquet(fp)
    sub=df[df['계정']=='지배주주당기순이익']
    if sub.empty: sub=df[df['계정']=='당기순이익']
    if sub.empty: continue
    g=sub.groupby('기준일').agg(val=('값','last'),rc=('rcept_dt','last')).reset_index().sort_values('기준일')
    g['rc']=pd.to_datetime(g['rc']).dt.strftime('%Y%m%d')
    prof[tk]=g
def conc_of(tk, dstr):
    g=prof.get(tk)
    if g is None: return None
    avail=g[g['rc']<=dstr]
    if len(avail)<4: return None
    last4=avail.tail(4)['val'].values
    if (last4<=0).any(): return ('loss', None)  # 적자 분기 포함 = 회복/턴어라운드
    ttm=last4.sum()
    if ttm<=0: return None
    return ('pos', float(last4.max()/ttm))
# 금호 conc 궤적
print("[금호건설 002990 일회성집중도 궤적]")
for d in ['20260625','20260626','20260629']:
    print(f"  {d}: conc={conc_of('002990',d)}")
print("[제주반도체 080220]")
for d in dall[-3:]:
    print(f"  {d}: conc={conc_of('080220',d)}")
# EDA: 매수권(rank<=3) stock-day들을 conc로 split, fwd60 수익률
pidx={d:i for i,d in enumerate(prices.index.strftime('%Y%m%d'))}
parr=prices.values; pcols={c:j for j,c in enumerate(prices.columns)}
def fwd(tk,dstr,h=60):
    i=pidx.get(dstr); j=pcols.get(tk)
    if i is None or j is None or i+h>=len(parr): return None
    p0=parr[i,j]; p1=parr[i+h,j]
    if not(p0>0 and p1>0): return None
    return p1/p0-1
buckets={'일회성>0.5(pos)':[], '정상<0.5(pos)':[], '적자포함(회복)':[]}
for d in dall:
    for tk,r in days[d].items():
        if r.get('rank',99)>3: continue  # 매수권만
        c=conc_of(tk,d); fr=fwd(tk,d)
        if c is None or fr is None: continue
        if c[0]=='loss': buckets['적자포함(회복)'].append(fr)
        elif c[1]>0.5: buckets['일회성>0.5(pos)'].append(fr)
        else: buckets['정상<0.5(pos)'].append(fr)
print("\n[매수권(rank<=3) stock-day fwd60 수익률 — 일회성집중도별]")
for k,v in buckets.items():
    if v: print(f"  {k:<16} n={len(v):>4}  평균 {np.mean(v)*100:+.1f}%  승률 {np.mean([x>0 for x in v])*100:.0f}%  중앙 {np.median(v)*100:+.1f}%")
# 임계 민감도
print("\n[임계별 pos코호트 fwd60]")
for thr in [0.4,0.45,0.5,0.55,0.6]:
    hi=[];lo=[]
    for d in dall:
        for tk,r in days[d].items():
            if r.get('rank',99)>3:continue
            c=conc_of(tk,d);fr=fwd(tk,d)
            if c is None or fr is None or c[0]!='pos':continue
            (hi if c[1]>thr else lo).append(fr)
    if hi and lo: print(f"  thr{thr}: 일회성>{thr} n={len(hi)} 평균{np.mean(hi)*100:+.1f}%승{np.mean([x>0 for x in hi])*100:.0f}% | 정상 n={len(lo)} 평균{np.mean(lo)*100:+.1f}%승{np.mean([x>0 for x in lo])*100:.0f}%")
print("\n[완료]")
