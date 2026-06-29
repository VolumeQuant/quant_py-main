# -*- coding: utf-8 -*-
"""폭등 × 성장성 — 폭등주를 growth_s로 갈라 정치펌프(저성장) vs 폭발승자(고성장) 구분되나."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
PROJ='C:/dev'
px=pd.read_parquet(sorted(glob.glob(PROJ+'/data_cache/all_ohlcv_2017*_20260*.parquet'))[-1]).replace(0,np.nan)
di={d:i for i,d in enumerate(px.index.strftime('%Y%m%d'))};pcol={c:j for j,c in enumerate(px.columns)};parr=px.values
def ret(tk,d,w):
    i=di.get(d);j=pcol.get(tk)
    if i is None or j is None or i-w<0:return None
    p0=parr[i-w,j];p1=parr[i,j];return p1/p0-1 if(p0>0 and p1>0)else None
def fwd(tk,d,h=60):
    i=di.get(d);j=pcol.get(tk)
    if i is None or j is None or i+h>=len(parr):return None
    p0=parr[i,j];p1=parr[i+h,j];return p1/p0-1 if(p0>0 and p1>0)else None
days={};dall=[]
for f in sorted(glob.glob(PROJ+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        days[dt]={r['ticker']:r for r in json.load(open(f,encoding='utf-8'))['rankings']};dall.append(dt)
dall=sorted(dall)
# 금호 today
r=days['20260629']['002990']
print(f"금호: 5일{ret('002990','20260629',5)*100:.0f}% growth_s={r['growth_s']:.2f} value_s={r['value_s']:.2f}")
# 폭등주(rank<=6 & 5일>40%) 를 growth_s로 split
print("\n[폭등주(rank<=6 & 5일수익률>40%) fwd60 — growth_s별]")
for glo,ghi,lb in [(-9,0.5,'성장<0.5(펌프의심)'),(0.5,9,'성장>=0.5(진짜)')]:
    coh=[fwd(tk,d) for d in dall for tk,x in days[d].items()
         if x.get('rank',99)<=6 and (ret(tk,d,5) or 0)>0.40 and glo<=x.get('growth_s',0)<ghi and fwd(tk,d) is not None]
    if coh: print(f"  {lb:<18} n={len(coh):>3} 평균{np.mean(coh)*100:+.1f}% 승률{np.mean([c>0 for c in coh])*100:.0f}% 중앙{np.median(coh)*100:+.1f}%")
# 더 넓게: 이격도>1.4 기준
ma20=px.rolling(20).mean();disp=(px/ma20).values
def dsp(tk,d):
    i=di.get(d);j=pcol.get(tk)
    return float(disp[i,j]) if (i is not None and j is not None and disp[i,j]==disp[i,j]) else None
print("\n[과열주(rank<=6 & 이격도>1.4) fwd60 — growth_s별]")
for glo,ghi,lb in [(-9,0.5,'성장<0.5'),(0.5,9,'성장>=0.5')]:
    coh=[fwd(tk,d) for d in dall for tk,x in days[d].items()
         if x.get('rank',99)<=6 and (dsp(tk,d) or 0)>1.4 and glo<=x.get('growth_s',0)<ghi and fwd(tk,d) is not None]
    if coh: print(f"  {lb:<10} n={len(coh):>3} 평균{np.mean(coh)*100:+.1f}% 승률{np.mean([c>0 for c in coh])*100:.0f}% 중앙{np.median(coh)*100:+.1f}%")
print("\n[완료]")
