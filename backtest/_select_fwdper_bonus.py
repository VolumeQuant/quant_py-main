# -*- coding: utf-8 -*-
"""사용자 알파 정확 재현: trailing PER 높아도 forward PER 낮으면(이익폭증) 끌어올림(보너스).
종목선택에 반영. 빼기 아님 — forward 싼/이익가속 종목을 top으로. look-ahead proxy."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh={t:mc.loc[t,'상장주식수'] for t in mc.index}
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi:
        ar[dt]=sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99));dts.append(dt)
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
def px(t,d):
    if t not in pcol or d not in tdi: return None
    v=parr[tdi[d],pcol[t]]; return float(v) if v>0 else None
# 월별: forward PER + trailing PER + 기대성장
fwm={};twm={};gwm={};curm=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];cf={};ct={};cg={}
        for t in cache:
            p0=px(t,d); e0=ttm(t,d); e1=ttm(t,d1)
            if p0 and t in sh and sh[t]>0:
                if e1 and e1>0: cf[t]=(p0*sh[t])/(e1*1e8)
                if e0 and e0>0: ct[t]=(p0*sh[t])/(e0*1e8)
                if e0 and e0>0 and e1 and e1>0: cg[t]=e1/e0
    fwm[d]=cf;twm[d]=ct;gwm[d]=cg
def sim(mode, w, pool):
    held=[];daily=[];prev=None
    for d in dts:
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[]
        else:
            cand=ar[d][:pool]; fp=fwm.get(d,{}); tp=twm.get(d,{}); gw=gwm.get(d,{})
            if w>0:
                def bonus(c):
                    t=c['ticker']; f=fp.get(t)
                    if mode=='fwd_low':      # forward PER 낮을수록 보너스 (절대값)
                        return (20.0/f) if (f and f>0) else 0  # f=10→2, f=20→1, f=40→0.5
                    if mode=='fwd_under20':  # forward<20 이진 보너스
                        return 1.0 if (f and f<20) else 0.0
                    if mode=='accel':        # trailing/forward 낙폭(기대성장) × forward 낮음
                        g=gw.get(t); return (g or 0)*(20.0/f if (f and f>0) else 0)
                    return 0
                def sc(c,i): return -i + w*bonus(c)
                order=sorted(enumerate(cand),key=lambda x:-sc(x[1],x[0]))
                held=[c['ticker'] for _,c in order[:3]]
            else: held=[c['ticker'] for c in cand[:3]]
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
print("[형 알파: forward PER 낮은(이익폭증) 종목 끌어올림 — 보너스, look-ahead 상한]\n")
c,m,cal=sim('x',0,10); print(f"  현행(반영X): Cal {cal:.2f} (CAGR {c:.0f}% MDD {m:.1f}%)\n")
for mode,lbl in [('fwd_low','forward PER 낮을수록↑'),('fwd_under20','forward<20 우대'),('accel','이익가속(낙폭)×forward낮음')]:
    print(f"  ── {lbl} ──")
    for pool in [10,20]:
        best=None
        for w in [1,2,3,5,8]:
            c,m,cal=sim(mode,w,pool)
            if best is None or cal>best[0]: best=(cal,w,c,m)
        print(f"  pool{pool}: 최고 Cal {best[0]:.2f} @W{best[1]} (CAGR {best[2]:.0f}% MDD {best[3]:.1f}%)")
    print()
print("→ 현행 넘으면 형 알파가 종목선택서 작동. trailing빼기(망함)와 정반대 = 핵심")
