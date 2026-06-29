# -*- coding: utf-8 -*-
"""조건부 슬롯비중 — 강한 boost에서만 40/40/20, 약한 boost는 동일. defense=cash."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdate={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0]
ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean();ma120=kc.rolling(120).mean();ma200=kc.rolling(200).mean()
files=sorted(f for f in glob.glob(P+'/state/ranking_*.json') if os.path.basename(f)[8:16]>='20190102')
dates=[os.path.basename(f)[8:16] for f in files]
rankmap={}
for f,d in zip(files,dates):
    rankmap[d]={x['ticker']:x.get('rank',99) for x in json.load(open(f,encoding='utf-8'))['rankings']}
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
def strength(d, kind):
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index: return None
    try:
        if kind=='ma2080': return ma20[ts]/ma80[ts]-1
        if kind=='ma200': return kc[ts]/ma200[ts]-1
        if kind=='ma120': return kc[ts]/ma120[ts]-1
    except: return None
def close(tk,d):
    if tk not in pcol or d not in pdate: return None
    v=parr[pdate[d],pcol[tk]]; return v if v>0 else None
def sim(sub, wfun):
    held={};daily=[];prev=None
    for d in sub:
        ret=0.0
        if held and prev:
            order=sorted(held,key=lambda t:held[t]['rk']); ws=wfun(d,len(order))[:len(order)];sw=sum(ws);ws=[w/sw for w in ws]
            for tk,w in zip(order,ws):
                pc=close(tk,prev);nc=close(tk,d)
                if pc and nc: ret+=w*(nc/pc-1)
        daily.append(ret)
        rk=rankmap.get(d,{})
        if not reg.get(d,True): held={}
        else:
            held={t:v for t,v in held.items() if rk.get(t,99)<=6}
            for t in sorted([t for t in rk if rk[t]<=3],key=lambda z:rk[z]):
                if len(held)>=3: break
                if t not in held and close(t,d): held[t]={'rk':rk[t]}
            for t in held: held[t]['rk']=rk.get(t,99)
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
EQ=[1/3,1/3,1/3];CC=[0.4,0.4,0.2]
def wf_equal(d,n): return EQ
def wf_conc(d,n): return CC
def make_cond(kind,thr):
    def f(d,n): return CC if (strength(d,kind) or -9)>thr else EQ
    return f
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26',('20240101'),dates[-1])]
def show(nm,wfun):
    o=[sim([d for d in dates if lo<=d<=hi],wfun) for _,lo,hi in segs]
    print(f"  {nm:30s} 전체{o[0][0]:>5.2f} 19-21 {o[1][0]:>5.2f} 약세 {o[2][0]:>5.2f} 24-26 {o[3][0]:>6.2f} MDD{o[0][2]:>6.1f}%")
print(f"[조건부 슬롯비중] 강한boost만 40/40/20\n  {'config':30s} {'전체':>7s} {'19-21':>8s} {'약세':>7s} {'24-26':>8s}")
show('동일 33/33/33 (현행)',wf_equal)
show('항상 40/40/20',wf_conc)
for kind,thrs in [('ma2080',[0.02,0.04,0.06]),('ma200',[0.05,0.10,0.15]),('ma120',[0.03,0.06])]:
    for t in thrs:
        show(f'cond {kind}>{t} → 40/40/20',make_cond(kind,t))
