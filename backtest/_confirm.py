# -*- coding: utf-8 -*-
"""더블컨펌 — production 독립픽 ∩ sleeve 독립픽 = 겹치는 종목이 each-only보다 더 버나. + 겹침 포트 성과."""
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
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dts.append(dt)
dts=sorted(dts);win=[d for d in tdays if dts[0]<=d<=dts[-1]]
def reg_s(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_s(win)
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') or dd.get('ni2') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
def fwd(t,d,h=60):
    i=tdi.get(d)
    if i is None or i+h>=len(tdays) or t not in pcol: return None
    p0,p1=parr[i,pcol[t]],parr[i+h,pcol[t]]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
rb=[];seen=set()
for d in win:
    if d in ar and d[:6] not in seen: seen.add(d[:6]);rb.append(d)
# 각 리밸런스일: production 독립픽(rank<=PY) vs sleeve 독립픽(선행성장 top SM, state유니버스)
PY,SM=6,15
ov_r=[];po_r=[];so_r=[]
ov_picks={}
for d in rb:
    i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)]
    prod=set(x['ticker'] for x in ar[d] if x.get('rank',99)<=PY)
    fg=[]
    for x in ar[d]:
        t=x['ticker'];e0=ttm(t,d);e1=ttm(t,d1)
        if t in pcol and parr[i,pcol[t]]>0 and e0 and e0>0 and e1 is not None: fg.append((t,e1/e0-1))
    sleeve=set(t for t,_ in sorted(fg,key=lambda z:-z[1])[:SM])
    ov=prod&sleeve; po=prod-sleeve; so=sleeve-prod
    ov_picks[d]=list(ov)
    for t in ov:
        r=fwd(t,d); 
        if r is not None: ov_r.append(r)
    for t in po:
        r=fwd(t,d)
        if r is not None: po_r.append(r)
    for t in so:
        r=fwd(t,d)
        if r is not None: so_r.append(r)
print(f"[더블컨펌] production rank<={PY} ∩ sleeve 선행성장 top{SM}, fwd60 수익 (리밸 {len(rb)}회)\n")
print(f"  겹침(둘다 확인)  : n={len(ov_r):>4} 평균 {np.mean(ov_r):+.2f}% 승률 {(np.array(ov_r)>0).mean()*100:.0f}%")
print(f"  production만     : n={len(po_r):>4} 평균 {np.mean(po_r):+.2f}% 승률 {(np.array(po_r)>0).mean()*100:.0f}%")
print(f"  sleeve만         : n={len(so_r):>4} 평균 {np.mean(so_r):+.2f}% 승률 {(np.array(so_r)>0).mean()*100:.0f}%")
# 겹침 포트 (월리밸, 동일가중, 약세현금)
held=[];daily=[];prev=None
for d in win:
    r=0.0
    if held and prev:
        rs=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
        r=float(np.mean(rs)) if rs else 0.0
    daily.append(r)
    if not reg.get(d,True): held=[]
    elif d in ov_picks: held=ov_picks[d] if ov_picks[d] else held
    prev=d
a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
sh=a.mean()/(a.std() or 1)*np.sqrt(252)
avgn=np.mean([len(ov_picks[d]) for d in rb])
print(f"\n  겹침 포트(월리밸, 평균 {avgn:.1f}종목): CAGR {cagr:.0f}% MDD {mdd:.1f}% Calmar {cagr/abs(mdd):.2f} Sharpe {sh:.2f}")
print(f"  (production 단독 Calmar 4.24 Sharpe 2.06 / sleeve 1.4)")
