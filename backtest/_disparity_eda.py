# -*- coding: utf-8 -*-
"""이격도20 필터 EDA — 매수권 fwd수익률을 이격도로 split + 금호/제주/SK 현재값.
금호(펌프) 잡으면서 제주(모멘텀승자) 살리는 임계 있나?"""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
PROJ='C:/dev'
px=pd.read_parquet(sorted(glob.glob(PROJ+'/data_cache/all_ohlcv_2017*_20260*.parquet'))[-1]).replace(0,np.nan)
ma20=px.rolling(20).mean()
disp=px/ma20  # 이격도20
days={};dall=[]
for f in sorted(glob.glob(PROJ+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        days[dt]={r['ticker']:r for r in json.load(open(f,encoding='utf-8'))['rankings']};dall.append(dt)
dall=sorted(dall)
di={d:i for i,d in enumerate(px.index.strftime('%Y%m%d'))}
pcol={c:j for j,c in enumerate(px.columns)};parr=px.values;darr=disp.values
def disp_of(tk,d):
    i=di.get(d);j=pcol.get(tk)
    if i is None or j is None: return None
    v=darr[i,j]; return float(v) if v==v else None
def fwd(tk,d,h=60):
    i=di.get(d);j=pcol.get(tk)
    if i is None or j is None or i+h>=len(parr): return None
    p0=parr[i,j];p1=parr[i+h,j]
    return p1/p0-1 if (p0>0 and p1>0) else None
# 현재값
print("[현재 이격도20]")
last=dall[-1]
for tk,nm in [('002990','금호건설'),('080220','제주반도체'),('000660','SK하이닉스'),('005930','삼성전자'),('131290','티에스이')]:
    print(f"  {nm}: {disp_of(tk,last)}")
# 제주 역대 최대 이격도 (매수권일 때)
print("\n[제주반도체 매수권(rank<=3)이었던 날의 이격도20 분포]")
jd=[disp_of('080220',d) for d in dall if days[d].get('080220',{}).get('rank',99)<=3 and disp_of('080220',d)]
if jd: print(f"  n={len(jd)} 평균{np.mean(jd):.2f} 중앙{np.median(jd):.2f} 최대{np.max(jd):.2f} | >1.5비율 {np.mean([x>1.5 for x in jd])*100:.0f}%")
# 매수권 fwd60 split by 이격도
print("\n[매수권(rank<=3) stock-day fwd60 — 이격도20별]")
for lo,hi,lb in [(0,1.2,'<1.2'),(1.2,1.5,'1.2~1.5'),(1.5,1.8,'1.5~1.8'),(1.8,99,'>1.8')]:
    v=[fwd(tk,d) for d in dall for tk,r in days[d].items() if r.get('rank',99)<=3 and (disp_of(tk,d) or 0)>=lo and (disp_of(tk,d) or 0)<hi and fwd(tk,d) is not None]
    if v: print(f"  이격도 {lb:<8} n={len(v):>4} 평균{np.mean(v)*100:+.1f}% 승률{np.mean([x>0 for x in v])*100:.0f}% 중앙{np.median(v)*100:+.1f}%")
print("\n[완료]")
