# -*- coding: utf-8 -*-
"""매수 진입 이벤트(boost+wr-rank<=3 신규진입) + fwd 수익률 수집 → 승자/패자 분류 + 저장팩터."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pidx={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)}; parr=prices.values; pcol={c:i for i,c in enumerate(prices.columns)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
def reg_series(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]); stk=stk+1 if s==ss else 1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
def fwd(tk,d,h):
    if tk not in pcol or d not in pidx: return None
    i=pidx[d];ci=pcol[tk]
    if i+h>=len(parr): return None
    p0,p1=parr[i,ci],parr[i+h,ci]
    return (p1/p0-1)*100 if (p0>0 and p1>0) else None
files=sorted(f for f in glob.glob(P+'/state/ranking_*.json') if os.path.basename(f)[8:16]>='20190102')
dates=[os.path.basename(f)[8:16] for f in files]
reg=reg_series(dates)
top3_prev=set()
rows=[]
for f,d in zip(files,dates):
    r=json.load(open(f,encoding='utf-8'))['rankings']
    cur={x['ticker'] for x in r if x.get('rank',99)<=3}
    if reg.get(d,True):  # boost만
        for x in r:
            if x.get('rank',99)<=3 and x['ticker'] not in top3_prev:  # 신규 진입
                rows.append({'d':d,'tk':x['ticker'],'nm':x['name'],'sector':x.get('sector',''),
                    'growth':x.get('growth_s'),'value':x.get('value_s'),'qual':x.get('quality_s'),
                    'mom':x.get('mom_12m_s') or x.get('momentum_s'),'overheat':x.get('overheat_pen') or 0,
                    'recent_ca':x.get('recent_ca') or 0,'per':x.get('per'),'pbr':x.get('pbr'),'roe':x.get('roe'),
                    'f20':fwd(x['ticker'],d,20),'f60':fwd(x['ticker'],d,60)})
    top3_prev=cur
df=pd.DataFrame(rows)
df.to_parquet(P+'/backtest/_trap_entries.parquet')
print(f"매수 진입(boost·신규 rank<=3): {len(df)}건")
v=df.dropna(subset=['f60'])
print(f"fwd60 평균 {v['f60'].mean():+.1f}% 승률 {(v['f60']>0).mean()*100:.0f}%")
print(f"패자(f60<0): {(v['f60']<0).sum()}건 / 큰손실(f60<-15%): {(v['f60']<-15).sum()}건")
print("\n=== 큰손실 진입 top (f60<-15%) ===")
big=v[v['f60']<-15].sort_values('f60')
for _,x in big.head(20).iterrows():
    print(f"  {x['d']} {x['nm'][:10]:10s} f60={x['f60']:+.0f}% growth={x['growth']:.2f} mom={x['mom']:.2f} per={x['per']} pbr={x['pbr']} overheat={x['overheat']:.2f} recent_ca={int(x['recent_ca'])}")
