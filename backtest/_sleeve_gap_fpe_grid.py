# -*- coding: utf-8 -*-
"""KR sleeve gap(기대성장=PER/fwdPER) × fwd_per 자격 그리드 — US 방식(gap컷) vs KR(fwd PER 자격) 비교.
look-ahead proxy(미래250일 TTM). 기간 쪼갬(강세19-21/최근24-26, 약세=defense 제외)."""
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
# 월별: 기대성장(gap=e1/e0) + fwd_per(가격/e1)
gm={};fm={};curm=None;cg={};cf={}
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];cg={};cf={}
        for t in cache:
            p0=px(t,d); e0=ttm(t,d); e1=ttm(t,d1)
            if p0 and t in sh and sh[t]>0:
                if e0 and e0>0 and e1 is not None and e1>0:
                    cg[t]=e1/e0       # gap=기대성장
                    cf[t]=(p0*sh[t])/(e1*1e8)  # fwd_per
    gm[d]=cg;fm[d]=cf
K,CAP=2.0,3.0
def sim(gap_min, fpe_max):
    """자격: gap>=gap_min AND fwd_per<fpe_max. 비중: 기대성장 비례 K2cap3."""
    held=[];out=[];prev=None;pw={}
    for d in dts:
        ret=0.0
        if held and prev:
            num=0;den=0
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    w=pw.get(t,1.0);num+=w*(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1);den+=w
            ret=num/den if den>0 else 0.0
        out.append((d,ret))
        if not reg.get(d,True): held=[];pw={}
        else:
            held=[x['ticker'] for x in ar[d][:3]]
            g=gm.get(d,{});fp=fm.get(d,{});pw={}
            for t in held:
                gv=g.get(t);fpv=fp.get(t)
                ok=(gv is not None)
                if gap_min and not(gv and gv>=gap_min): ok=False
                if fpe_max and not(fpv and fpv<fpe_max): ok=False
                pw[t]=min(1.0+K*max((gv or 1.0)-1.0,0.0),CAP) if ok else 1.0
        prev=d
    return out
def cal(out,sub=None):
    a=np.array([r for d,r in out if (not sub or sub[0]<=d<=sub[1])])
    if len(a)<20: return 0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
P1=('20190102','20211231');P3=('20240101','20261231')
print("[KR sleeve gap(기대성장)×fwd_per 자격 그리드 — Calmar 전체/강세/최근]\n")
print("  gap_min |  fpe無  /  fpe<20  /  fpe<25   (각칸 전체/강세/최근 Calmar)")
def cell(o): return f"{cal(o):.2f}/{cal(o,P1):.2f}/{cal(o,P3):.2f}"
for gm_min in [None,2.0,2.5,3.0]:
    row=f"  {(str(gm_min) if gm_min else '無'):<10}"
    for fpe in [None,20,25]:
        row+=f"{cell(sim(gm_min,fpe)):>16}"
    print(row)
print("\n  (각 칸 = 전체/강세19-21/최근24-26 Calmar)")
print("  → US는 gap2.5~3.5 단독 최고. KR도 그런지, 아니면 fwd_per<20이 나은지")
