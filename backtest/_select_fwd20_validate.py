# -*- coding: utf-8 -*-
"""forward PER<20 우대 풀검증 — WF(약세장)·LOWO·커버리지편향. look-ahead 상한이나 robust 방향 확인."""
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
fwm={};curm=None;mcapm={}
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];cf={};cm={}
        for t in cache:
            p0=px(t,d); e1=ttm(t,d1)
            if p0 and t in sh and sh[t]>0:
                cm[t]=p0*sh[t]/1e8
                if e1 and e1>0: cf[t]=(p0*sh[t])/(e1*1e8)
    fwm[d]=cf;mcapm[d]=cm
def sim(w,pool,sub=None,exclude=None):
    held=[];daily=[];prev=None
    for d in dts:
        if sub and not(sub[0]<=d<=sub[1]):
            prev=d if not sub else prev; 
        ret=0.0
        if held and prev and (not sub or sub[0]<=prev<=sub[1] or True):
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        daily.append((d,ret))
        if not reg.get(d,True): held=[]
        else:
            cand=ar[d][:pool]; fp=fwm.get(d,{})
            if exclude: cand=[c for c in cand if c['ticker']!=exclude]
            if w>0:
                def sc(c,i): 
                    f=fp.get(c['ticker']); return -i + w*(1.0 if (f and f<20) else 0.0)
                order=sorted(enumerate(cand),key=lambda x:-sc(x[1],x[0])); held=[c['ticker'] for _,c in order[:3]]
            else: held=[c['ticker'] for c in cand[:3]]
        prev=d
    return daily
def cal_of(daily,sub=None):
    a=np.array([r for d,r in daily if (not sub or sub[0]<=d<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
W,POOL=3,10
base=sim(0,POOL); fwd=sim(W,POOL)
print(f"[forward PER<20 우대 (W{W} pool{POOL}) 풀검증 — look-ahead 상한]\n")
print(f"  {'기간':<22}{'현행 Cal':>10}{'fwd<20 Cal':>12}{'Δ':>7}")
for lbl,sub in [('전체 2019-26',None),('2019-21 강세',('20190102','20211231')),
                ('★2022-23 약세',('20220101','20231231')),('2024-26 최근',('20240101','20261231'))]:
    _,_,cb=cal_of(base,sub); _,_,cf=cal_of(fwd,sub)
    print(f"  {lbl:<22}{cb:>10.2f}{cf:>12.2f}{cf-cb:>+7.2f}")
print(f"\n[LOWO — 슈퍼위너 빼도 유지되나]")
for ex,nm in [('000660','SK하이닉스'),('080220','제주반도체'),('089970','브이엠')]:
    db=sim(0,POOL,exclude=ex); df=sim(W,POOL,exclude=ex)
    _,_,cb=cal_of(db); _,_,cf=cal_of(df)
    print(f"  −{nm:<10} 현행 {cb:.2f} → fwd<20 {cf:.2f} (Δ{cf-cb:+.2f})")
# 커버리지 편향: fwd<20 우대로 뽑힌 종목 시총 분포
print(f"\n[커버리지 편향 — fwd<20 우대가 대형주만 뽑나]")
cnt={'대형1조+':0,'중형3천~1조':0,'소형<3천':0}; tot=0
prev=None;held=[]
for d in dts:
    if reg.get(d,True):
        cand=ar[d][:POOL];fp=fwm.get(d,{})
        order=sorted(enumerate(cand),key=lambda x:-(-x[0]+W*(1.0 if (fp.get(x[1]['ticker']) and fp.get(x[1]['ticker'])<20) else 0)))
        for _,c in order[:3]:
            mcv=mcapm.get(d,{}).get(c['ticker'],0)
            if mcv>=10000: cnt['대형1조+']+=1
            elif mcv>=3000: cnt['중형3천~1조']+=1
            elif mcv>0: cnt['소형<3천']+=1
            tot+=1
for k,v in cnt.items(): print(f"  {k:<12} {v/tot*100:.0f}%")
print("  → 소형 비중 현저히 낮으면 커버리지 편향(소형 차별). 균형이면 OK")
