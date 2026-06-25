# -*- coding: utf-8 -*-
"""놓친 승자 EDA — 순위구간별 fwd 수익률 (boost일). 3슬롯이 맞나, rank4-6에 승자 흘리나."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pidx={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)};parr=prices.values;pcol={c:i for i,c in enumerate(prices.columns)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
files=sorted(f for f in glob.glob(P+'/state/ranking_*.json') if os.path.basename(f)[8:16]>='20190102')
dates=[os.path.basename(f)[8:16] for f in files]
def reg_s(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_s(dates)
def fwd(tk,d,h):
    if tk not in pcol or d not in pidx: return None
    i=pidx[d];ci=pcol[tk]
    if i+h>=len(parr): return None
    p0,p1=parr[i,ci],parr[i+h,ci]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
rows=[]
for f,d in zip(files,dates):
    if not reg.get(d,True): continue  # boost만
    r=json.load(open(f,encoding='utf-8'))['rankings']
    for x in r:
        rk=x.get('rank',99)
        if rk<=20:
            rows.append({'rk':rk,'f20':fwd(x['ticker'],d,20),'f60':fwd(x['ticker'],d,60)})
df=pd.DataFrame(rows)
print(f"boost일 rank<=20 관측 {len(df)}건 (당일 스냅샷, 진입중복 포함)\n")
def bucket(lo,hi):
    g=df[(df['rk']>=lo)&(df['rk']<=hi)].dropna(subset=['f60'])
    return len(g),g['f20'].mean(),g['f60'].mean(),(g['f60']>0).mean()*100
print(f"  {'순위구간':10s}{'n':>7s}{'fwd20':>8s}{'fwd60':>8s}{'승률':>7s}")
for lo,hi,nm in [(1,1,'1위'),(2,2,'2위'),(3,3,'3위'),(4,4,'4위'),(5,5,'5위'),(6,6,'6위'),(7,10,'7-10위'),(11,20,'11-20위')]:
    n,a,b,w=bucket(lo,hi)
    print(f"  {nm:10s}{n:>7}{a:>+7.1f}%{b:>+7.1f}%{w:>6.0f}%")
