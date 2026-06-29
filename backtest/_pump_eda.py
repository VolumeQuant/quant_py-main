# -*- coding: utf-8 -*-
"""단기 폭등(5일/10일 수익률) 신호 EDA — 매수권 fwd수익률을 단기수익률로 split."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
PROJ='C:/dev'
px=pd.read_parquet(sorted(glob.glob(PROJ+'/data_cache/all_ohlcv_2017*_20260*.parquet'))[-1]).replace(0,np.nan)
di={d:i for i,d in enumerate(px.index.strftime('%Y%m%d'))};pcol={c:j for j,c in enumerate(px.columns)};parr=px.values
def ret(tk,d,w):
    i=di.get(d);j=pcol.get(tk)
    if i is None or j is None or i-w<0: return None
    p0=parr[i-w,j];p1=parr[i,j]
    return p1/p0-1 if (p0>0 and p1>0) else None
def fwd(tk,d,h=60):
    i=di.get(d);j=pcol.get(tk)
    if i is None or j is None or i+h>=len(parr): return None
    p0=parr[i,j];p1=parr[i+h,j]
    return p1/p0-1 if (p0>0 and p1>0) else None
days={};dall=[]
for f in sorted(glob.glob(PROJ+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        days[dt]={r['ticker']:r for r in json.load(open(f,encoding='utf-8'))['rankings']};dall.append(dt)
dall=sorted(dall)
print("[금호건설 최근 단기수익률]")
last='20260629'
for w in [5,10]: print(f"  {w}일 수익률: {ret('002990',last,w)}")
print("\n[매수권(rank<=3) fwd60 — 5일수익률(진입시점)별]")
for lo,hi,lb in [(-1,0.2,'<20%'),(0.2,0.4,'20~40%'),(0.4,0.6,'40~60%'),(0.6,0.8,'60~80%'),(0.8,99,'>80%')]:
    v=[fwd(tk,d) for d in dall for tk,r in days[d].items() if r.get('rank',99)<=3 and (ret(tk,d,5) is not None) and lo<=ret(tk,d,5)<hi and fwd(tk,d) is not None]
    if v: print(f"  5일 {lb:<8} n={len(v):>4} 평균{np.mean(v)*100:+.1f}% 승률{np.mean([x>0 for x in v])*100:.0f}% 중앙{np.median(v)*100:+.1f}%")
print("\n[10일수익률별]")
for lo,hi,lb in [(-1,0.3,'<30%'),(0.3,0.6,'30~60%'),(0.6,0.9,'60~90%'),(0.9,99,'>90%')]:
    v=[fwd(tk,d) for d in dall for tk,r in days[d].items() if r.get('rank',99)<=3 and (ret(tk,d,10) is not None) and lo<=ret(tk,d,10)<hi and fwd(tk,d) is not None]
    if v: print(f"  10일 {lb:<8} n={len(v):>4} 평균{np.mean(v)*100:+.1f}% 승률{np.mean([x>0 for x in v])*100:.0f}% 중앙{np.median(v)*100:+.1f}%")
# 차단 임계별 건수 (rank<=6, 진입권 근처)
print("\n[5일수익률 임계별 차단건수(rank<=6) + 그 코호트 fwd60]")
for thr in [0.5,0.6,0.7,0.8,1.0]:
    coh=[fwd(tk,d) for d in dall for tk,r in days[d].items() if r.get('rank',99)<=6 and (ret(tk,d,5) or 0)>thr and fwd(tk,d) is not None]
    if coh: print(f"  5일>{thr*100:.0f}%: n={len(coh)} 평균{np.mean(coh)*100:+.1f}% 승률{np.mean([x>0 for x in coh])*100:.0f}%")
print("\n[완료]")
