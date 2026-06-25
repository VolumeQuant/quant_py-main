# -*- coding: utf-8 -*-
"""이탈룰(rank>6 매도 / 방어전환 청산) 실현손익 vs 장부 f60 — 패자 손실 얼마나 잘라냈나."""
import sys, io, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import json
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pidx={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)};parr=prices.values;pcol={c:i for i,c in enumerate(prices.columns)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
files=sorted(f for f in glob.glob(P+'/state/ranking_*.json') if os.path.basename(f)[8:16]>='20190102')
dates=[os.path.basename(f)[8:16] for f in files]
# state rank 맵 + regime
rankmap={}
for f,d in zip(files,dates):
    r=json.load(open(f,encoding='utf-8'))['rankings']
    rankmap[d]={x['ticker']:x.get('rank',99) for x in r}
def reg_series(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_series(dates)
dpos={d:i for i,d in enumerate(dates)}
def px(tk,d):
    if tk not in pcol or d not in pidx: return None
    return parr[pidx[d],pcol[tk]]
def realized(tk,d0):
    # 진입 다음날부터 rank>6 또는 defense면 매도. 매도가=그날 종가.
    p0=px(tk,d0)
    if not(p0 and p0>0): return None,None
    start=dpos.get(d0)
    if start is None: return None,None
    for j in range(start+1,len(dates)):
        d=dates[j]
        rk=rankmap.get(d,{}).get(tk,99)
        if rk>6 or not reg.get(d,True):  # 이탈 or 방어청산
            p1=px(tk,d)
            if p1 and p1>0: return (p1/p0-1)*100, j-start
            return None,None
    return None,None  # 끝까지 보유
df=pd.read_parquet(P+'/backtest/_trap_entries.parquet')
res=[realized(tk,d) for tk,d in zip(df['tk'],df['d'])]
df['realized']=[r[0] for r in res]; df['holddays']=[r[1] for r in res]
v=df.dropna(subset=['f60','realized']).copy()
def stat(g,nm):
    print(f"  {nm}: n={len(g)} 장부f60 {g['f60'].mean():+.1f}% → 실현 {g['realized'].mean():+.1f}% (보유 중앙 {g['holddays'].median():.0f}일)")
print("=== 이탈룰 실현 vs 장부(f60) ===")
stat(v,'전체 진입')
stat(v[v['f60']>0],'승자(f60>0)')
stat(v[v['f60']<0],'패자(f60<0)')
stat(v[v['f60']<-15],'큰손실(f60<-15)')
big=v[v['f60']<-15]
print(f"\n  큰손실 63건: 장부 평균 {big['f60'].mean():+.1f}% → 실현 {big['realized'].mean():+.1f}% = 이탈룰이 {big['f60'].mean()-big['realized'].mean():+.1f}%p 잘라냄")
print(f"  큰손실 실현 분포: <-30% {(big['realized']<-30).sum()}건 / -30~-15% {((big['realized']>=-30)&(big['realized']<-15)).sum()}건 / -15~0% {((big['realized']>=-15)&(big['realized']<0)).sum()}건 / 실현+ {(big['realized']>0).sum()}건")
# 삼천리 등 개별
print("\n  개별 예(장부 vs 실현):")
for _,x in big.sort_values('f60').head(8).iterrows():
    print(f"    {x['d']} {x['nm'][:9]:9s} 장부f60 {x['f60']:+.0f}% → 실현 {x['realized']:+.0f}% (보유 {int(x['holddays'])}일)")
