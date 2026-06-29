# -*- coding: utf-8 -*-
"""선행성장 sleeve 구조 최적화 (7.4년 look-ahead 프록시=실현 미래12m EPS성장).
N·리밸런스·이탈·약세게이트 sweep + production(4.24) 대결. ★look-ahead=상한선·구조탐색(배포X)."""
import sys, io, os, glob, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
pdates=[d.strftime('%Y%m%d') for d in prices.index]; pdi={d:i for i,d in enumerate(pdates)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
# 거래일
tdays=[d for d in pdates if '20190102'<=d<='20260624']
def reg_s():
    reg={};md=True;stk=0;ss=None
    for d in tdays:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_s()
def ttm_ni_at(t,d):
    dd=cache.get(t)
    if dd is None: return None
    s=dd.get('ni') or dd.get('ni2')
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))]
    return v[-4:].sum() if len(v)>=4 else None
# 리밸런스일 (월/분기 첫 거래일)
def rebal_days(freq):
    out=[];seen=set()
    for d in tdays:
        key=d[:6] if freq=='M' else d[:4]+str((int(d[4:6])-1)//3)
        if key not in seen: seen.add(key); out.append(d)
    return out
tks=list(cache.keys())
def fwd_growth(t,d):  # 실현 미래12m: d+250거래일 TTM / d TTM
    i=pdi.get(d)
    if i is None or i+250>=len(tdays): 
        d1=tdays[-1]
    else: d1=tdays[i+250]
    e0=ttm_ni_at(t,d); e1=ttm_ni_at(t,d1)
    if e0 is None or e1 is None or e0<=0: return None
    return e1/e0-1
def sim(N,freq,gate):
    rb=rebal_days(freq); rbset=set(rb)
    held=[]; daily=[]; prev=None
    rb_i={d:None for d in tdays}
    for d in tdays:
        # 수익 (전일→당일, 동일가중)
        ret=0.0
        if held and prev:
            rs=[parr[pdi[d],pcol[t]]/parr[pdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[pdi[prev],pcol[t]]>0 and parr[pdi[d],pcol[t]]>0]
            ret=float(np.mean(rs)) if rs else 0.0
        daily.append(ret)
        # 리밸런스
        if gate and not reg.get(d,True): held=[]
        elif d in rbset:
            sc=[(fwd_growth(t,d),t) for t in tks]
            sc=[(g,t) for g,t in sc if g is not None and t in pcol and parr[pdi[d],pcol[t]]>0]
            sc.sort(reverse=True); held=[t for g,t in sc[:N]]
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
print("[선행성장 sleeve 최적화 — 7.4년 look-ahead] production 메인 = Calmar 4.24 기준\n")
print(f"  {'config':28s}{'Calmar':>8s}{'CAGR':>8s}{'MDD':>8s}")
for freq in ['M','Q']:
    for N in [10,15,20]:
        for gate in [True,False]:
            cal,cagr,mdd=sim(N,freq,gate)
            print(f"  N{N} {freq} gate{'ON' if gate else 'OFF':3s}        {cal:>8.2f}{cagr:>7.0f}%{mdd:>7.1f}%")
