import sqlite3, sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT='C:/dev'
px=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan); px=px.dropna(how='all')
mc=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/market_cap_ALL_*.parquet'))[-1])
# === MA120 아래 비율 ===
ma120=px.rolling(120,min_periods=80).mean()
last=px.index[-1]
cur=px.loc[last]; m=ma120.loc[last]
def breadth(tickers):
    valid=[t for t in tickers if t in px.columns and pd.notna(cur.get(t)) and pd.notna(m.get(t))]
    below=sum(1 for t in valid if cur[t]<m[t])
    return below,len(valid)
uni=[t for t in mc.index if mc.loc[t,'시가총액']>=1e11 and isinstance(t,str) and len(t)==6 and t[-1]=='0']
b1,n1=breadth(list(px.columns)); b2,n2=breadth(uni)
print(f"=== MA120 아래 비율 ({str(last)[:10]}) ===")
print(f"  전체 {n1}종목: {b1}개 아래 ({b1/n1*100:.0f}%) — {n1-b1}개만 MA120 위")
print(f"  시총>=1000억 유니버스 {n2}종목: {b2}개 아래 ({b2/n2*100:.0f}%)")
print(f"  → {'광범위 약세(소형주 ㅈ됨)' if b1/n1>0.5 else '대체로 건강'}\n")

# === EPS 진입/이탈/슬롯 시뮬 ===
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)};parr=px.values;pcol={c:i for i,c in enumerate(px.columns)}
c=sqlite3.connect(ROOT+'/kr_eps_momentum/eps_momentum_data_kr.db')
df=pd.read_sql('SELECT date,ticker,composite_rank FROM ntm_screening',c)
df['tk']=df['ticker'].str[:6];df['d8']=df['date'].str.replace('-','')
days=sorted([d for d in df['d8'].unique() if d in tdi])
rk={d:dict(zip(df[df['d8']==d]['tk'],df[df['d8']==d]['composite_rank'])) for d in days}
def ret(t,d0,d1):
    if t not in pcol: return 0.0
    p0=parr[tdi[d0],pcol[t]];p1=parr[tdi[d1],pcol[t]]
    return (p1/p0-1) if p0>0 and p1>0 else 0.0
def sim(entry,exit_,slots):
    held=[];eq=1.0;prev=None;dailies=[]
    for d in days:
        if prev:
            r=np.mean([ret(t,prev,d) for t in held]) if held else 0.0
            eq*=(1+r);dailies.append(r)
        rr=rk[d]
        held=[t for t in held if rr.get(t,999)<=exit_]  # 이탈
        cand=sorted([t for t in rr if rr[t]<=entry and t not in held],key=lambda t:rr[t])
        for t in cand:
            if len(held)>=slots: break
            held.append(t)
        prev=d
    n=len(dailies);a=np.array(dailies)
    cum=(eq-1)*100; mdd=0
    e=np.cumprod(1+a);pk=np.maximum.accumulate(e);mdd=((e-pk)/pk).min()*100 if len(e) else 0
    return cum,mdd,n
print(f"=== EPS 진입/이탈/슬롯 시뮬 ({len(days)}일, composite_rank 기준, 국면게이트 없음) ===")
print(f"  ※ 15일·단일에피소드 = 예비. 누적수익 = 이 구간 전체\n")
print(f"  {'진입/이탈/슬롯':18s}{'누적수익':>9s}{'MDD':>8s}")
for e,x,s in [(3,6,3),(5,10,5),(3,10,3),(1,5,3),(5,15,5),(2,8,3),(10,20,10)]:
    cum,mdd,n=sim(e,x,s)
    print(f"  E{e} X{x} S{s:<11d}{cum:>+8.1f}%{mdd:>7.1f}%")
# 벤치: 유니버스 평균 같은 기간
bench=np.mean([ret(t,days[0],days[-1]) for t in rk[days[0]]])*100
print(f"\n  벤치(유니버스 buy&hold): {bench:+.1f}%")
