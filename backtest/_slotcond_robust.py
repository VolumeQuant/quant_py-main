# -*- coding: utf-8 -*-
"""조건부 슬롯비중 견고성 — LOWO + 임계 sweep + 연도별 WF. 베이스: cond KOSPI>MA200*1.10."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdate={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0]
ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean();ma200=kc.rolling(200).mean()
files=sorted(f for f in glob.glob(P+'/state/ranking_*.json') if os.path.basename(f)[8:16]>='20190102')
dates=[os.path.basename(f)[8:16] for f in files]
rankmap0={}
for f,d in zip(files,dates):
    rankmap0[d]={x['ticker']:x.get('rank',99) for x in json.load(open(f,encoding='utf-8'))['rankings']}
NAME={}
for f,d in zip(files[-30:],dates[-30:]):
    for x in json.load(open(f,encoding='utf-8'))['rankings']: NAME[x['ticker']]=x['name']
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
def strong(d,thr):
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma200.get(ts,np.nan)): return False
    return kc[ts]/ma200[ts]-1>thr
def close(tk,d):
    if tk not in pcol or d not in pdate: return None
    v=parr[pdate[d],pcol[tk]]; return v if v>0 else None
EQ=[1/3,1/3,1/3];CC=[0.4,0.4,0.2]
def sim(sub, cond_thr, exclude=None):
    rmap=rankmap0
    held={};daily=[];prev=None
    for d in sub:
        ws_sched= CC if (cond_thr is not None and strong(d,cond_thr)) else EQ
        ret=0.0
        if held and prev:
            order=sorted(held,key=lambda t:held[t]['rk']);ws=ws_sched[:len(order)];sw=sum(ws);ws=[w/sw for w in ws]
            for tk,w in zip(order,ws):
                pc=close(tk,prev);nc=close(tk,d)
                if pc and nc: ret+=w*(nc/pc-1)
        daily.append(ret)
        rk={t:v for t,v in rmap.get(d,{}).items() if t!=exclude}
        if not reg.get(d,True): held={}
        else:
            held={t:v for t,v in held.items() if rk.get(t,99)<=6}
            for t in sorted([t for t in rk if rk[t]<=3],key=lambda z:rk[z]):
                if len(held)>=3: break
                if t not in held and close(t,d): held[t]={'rk':rk[t]}
            for t in held: held[t]['rk']=rk.get(t,99)
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
def cal(thr,exclude=None): return sim(dates,thr,exclude)
# 집중비중 최다 수혜(rank<=2 boost일) 종목
cnt={}
for d in dates:
    if reg.get(d,True):
        for t,r in rankmap0.get(d,{}).items():
            if r<=2: cnt[t]=cnt.get(t,0)+1
top=sorted(cnt,key=lambda t:-cnt[t])[:6]
eqB=cal(None); ccB=cal(0.10)
print(f"[베이스] 동일 {eqB:.2f} / 조건부(MA200*1.10) {ccB:.2f}  Δ{ccB-eqB:+.2f}\n")
print("=== LOWO: rank<=2 최다종목 제외 후 (동일 vs 조건부) ===")
for t in top:
    e=cal(None,t); c=cal(0.10,t)
    print(f"  -{NAME.get(t,t)[:9]:9s}({cnt[t]}일집중): 동일 {e:.2f} / 조건부 {c:.2f}  Δ{c-e:+.2f}")
print("\n=== 임계 촘촘 sweep (조건부 vs 동일 4.07) ===")
for thr in [0.06,0.08,0.10,0.12,0.14]:
    print(f"  MA200*+{thr:.0%}: 조건부 {cal(thr):.2f}  (Δ{cal(thr)-eqB:+.2f})")
print("\n=== 연도별 WF (동일 vs 조건부 MA200*1.10) ===")
for y in ['2019','2020','2021','2022','2023','2024','2025','2026']:
    sub=[d for d in dates if d[:4]==y]
    if len(sub)<30: continue
    e=sim(sub,None);c=sim(sub,0.10)
    print(f"  {y}: 동일 {e:>5.2f} / 조건부 {c:>5.2f}  Δ{c-e:>+5.2f}")
