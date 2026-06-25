# -*- coding: utf-8 -*-
"""컷오프 게이트 vs 컷없이 전체 grow비례 (브이엠 억울? cliff 검증). look-ahead 상한 BT."""
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
# 일별 grow값 + 상위100 컷 (월별캐시)
growmap={};cutmap={};curg={};curcut=None;curm=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];fg=[]
        for t in cache:
            if t not in pcol or not(parr[i,pcol[t]]>0): continue
            e0=ttm(t,d);e1=ttm(t,d1)
            if e0 and e0>0 and e1 is not None: fg.append((t,e1/e0-1))
        fg.sort(key=lambda z:-z[1])
        curg={t:g for t,g in fg}; curcut=fg[99][1] if len(fg)>=100 else (fg[-1][1] if fg else 0)
    growmap[d]=curg; cutmap[d]=curcut
K,CAP=2.0,5.0
def sim(mode):
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
            gm=growmap.get(d,{}); cut=cutmap.get(d,0); pw={}
            for t in held:
                g=gm.get(t)
                if g is None: pw[t]=1.0; continue  # 컨센없음(평가불가)
                if mode=='gate':       w=min(1.0+K*max(g,0),CAP) if g>=cut else 1.0   # 현행: 상위100 안만
                elif mode=='nogate':   w=min(1.0+K*max(g,0),CAP)                       # 컷없이 grow비례(컨센 있으면)
                elif mode=='gate200':  cut2=cut; w=min(1.0+K*max(g,0),CAP) if g>=cut*0.5 else 1.0  # 컷 절반(완화)
                pw[t]=w
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
print("[컷오프 게이트 vs 컷없음 — 브이엠 cliff 검증, look-ahead 상한]\n")
print(f"  {'방식':<34}{'CAGR':>7}{'MDD':>8}{'Calmar':>8}")
for nm,md in [('★현행: 상위100 게이트+grow비례','gate'),
              ('컷없이 grow비례(컨센있으면 다)','nogate'),
              ('컷 절반완화(상위~200까지)','gate200')]:
    c,m,cal=sim(md); print(f"  {nm:<34}{c:>6.0f}%{m:>7.1f}%{cal:>8.2f}")
print("\n→ nogate/완화가 현행보다 높으면 컷이 너무 빡빡(브이엠 억울 정당). 비슷/낮으면 컷이 알파")
