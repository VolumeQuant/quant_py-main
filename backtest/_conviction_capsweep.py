# -*- coding: utf-8 -*-
"""강도차등 grow비례 K×CAP 스위트스팟 탐색 (look-ahead 상한 BT, 상대비교)."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi:
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dts.append(dt)
dts=sorted(dts)
def reg_s():
    reg={};md=True;stk=0;ss=None
    for d in dts:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_s()
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
confirm={};cur={};curm=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];fg=[]
        for t in cache:
            if t not in pcol or not(parr[i,pcol[t]]>0): continue
            e0=ttm(t,d);e1=ttm(t,d1)
            if e0 and e0>0 and e1 is not None: fg.append((t,e1/e0-1))
        fg.sort(key=lambda z:-z[1]); cur={t:g for t,g in fg[:100]}
    confirm[d]=cur
def sim(wfn):
    held=[];daily=[];prev=None;pw={}
    for d in dts:
        ret=0.0
        if held and prev:
            num=0;den=0
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    w=pw.get(t,1.0); num+=w*(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1); den+=w
            ret=num/den if den>0 else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[];pw={}
        else:
            held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3]]
            cf=confirm.get(d,{}); pw={t:wfn(cf.get(t)) for t in held}
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
def grow_lin(k,cap): return lambda g:(min(1.0+k*max(g,0),cap) if g is not None else 1.0)
print("[grow비례 K×CAP 스위트스팟 — look-ahead 상한, 상대비교]\n")
c,m,cal=sim(lambda g:1.0); print(f"  동일가중 baseline: Cal {cal:.2f} (CAGR {c:.0f}% MDD {m:.1f}%)\n")
hdr='K/CAP'; print(f"  {hdr:>7}"+"".join(f"{cap:>8.0f}" for cap in [2,3,4,5,6,8]))
best=None
for k in [0.5,1.0,1.5,2.0,2.5,3.0]:
    row=f"  {k:>7.1f}"
    for cap in [2,3,4,5,6,8]:
        c,m,cal=sim(grow_lin(k,cap)); row+=f"{cal:>8.2f}"
        if best is None or cal>best[0]: best=(cal,k,cap,c,m)
    print(row)
print(f"\n★ 최고 Calmar {best[0]:.2f} @ K={best[1]} CAP={best[2]} (CAGR {best[3]:.0f}% MDD {best[4]:.1f}%)")
