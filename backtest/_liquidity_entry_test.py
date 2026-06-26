# -*- coding: utf-8 -*-
"""매수진입(rank<=3)을 진입시점 20일평균 거래대금별로 → forward수익 + 꼬리(큰손실 빈도). 작전위험 검증."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
vol=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_volume_*.parquet'))[-1])  # 거래대금(원)
vd=[d.strftime('%Y%m%d') for d in vol.index];vdi={d:i for i,d in enumerate(vd)};vval=vol.values
vcol={c:i for i,c in enumerate(vol.columns)}
def liq20(t,d):  # 진입시점 직전 20일 평균 거래대금(억)
    if t not in vcol or d not in vdi: return None
    i=vdi[d];s=vval[max(0,i-19):i+1,vcol[t]];s=s[s>0]
    return np.nanmean(s)/1e8 if len(s)>=10 else None
def fwd(t,d,h):
    if t not in pcol or d not in tdi: return None
    i=tdi[d];d2=tdays[min(i+h,len(tdays)-1)];p0=parr[i,pcol[t]];p1=parr[tdi[d2],pcol[t]]
    return (p1/p0-1)*100 if p0>0 and p1>0 else None
rows=[];prev=set()
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    d=os.path.basename(f)[8:16]
    if not(d.isdigit() and d>='20190102' and d in tdi): continue
    held=[x['ticker'] for x in sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99))[:3]]
    for t in held:
        if t in prev: continue  # 신규진입만
        L=liq20(t,d);r20=fwd(t,d,20);r60=fwd(t,d,60)
        if L and r20 is not None: rows.append({'liq':L,'r20':r20,'r60':r60})
    prev=set(held)
o=pd.DataFrame(rows)
print(f"[매수 신규진입 {len(o)}건 — 진입시점 20일평균 거래대금별 forward + 꼬리]\n")
print(f"  {'거래대금구간':<14}{'n':>5}{'fwd20':>8}{'fwd60':>8}{'승률':>7}{'큰손실<-20%':>11}{'폭락<-30%':>10}")
bins=[(0,50),(50,100),(100,200),(200,500),(500,2000),(2000,1e9)]
lbl=['<50억','50~100','100~200','200~500','500~2000','2000억+']
for (lo,hi),nm in zip(bins,lbl):
    s=o[(o['liq']>=lo)&(o['liq']<hi)]
    if len(s)>0:
        big=(s['r20']<-20).mean()*100; crash=(s['r20']<-30).mean()*100; wr=(s['r20']>0).mean()*100
        print(f"  {nm:<14}{len(s):>5}{s['r20'].mean():>7.1f}%{s['r60'].mean():>7.1f}%{wr:>6.0f}%{big:>10.0f}%{crash:>9.0f}%")
print(f"\n=== 얇음(<100억) vs 두꺼움(>=100억) ===")
thin=o[o['liq']<100];thick=o[o['liq']>=100]
for nm,s in [('<100억',thin),('>=100억',thick)]:
    print(f"  {nm:8s} n={len(s):4d}  fwd20 {s['r20'].mean():+.1f}%  승률 {(s['r20']>0).mean()*100:.0f}%  큰손실<-20% {(s['r20']<-20).mean()*100:.0f}%  최악 {s['r20'].min():.0f}%")
