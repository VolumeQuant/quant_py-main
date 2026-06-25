# -*- coding: utf-8 -*-
"""fwd_per 효과 재검증 — 흑자전환 이상치(grow>5x) 제외, 정상성장(1.2~5x)만. fwd_per 단조성 확인."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh={t:mc.loc[t,'상장주식수'] for t in mc.index}
dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi: dts.append(dt)
dts=sorted(dts)
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
def px(t,d):
    if t not in pcol or d not in tdi: return None
    v=parr[tdi[d],pcol[t]]; return float(v) if v>0 else None
def fwd_ret(t,d,h):
    i=tdi[d]; d2=tdays[min(i+h,len(tdays)-1)]; p0=px(t,d); p1=px(t,d2)
    return (p1/p0-1)*100 if p0 and p1 else None
rows=[]; seen=set()
for d in dts:
    if d[:6] in seen: continue
    seen.add(d[:6]); i=tdi[d]; d1=tdays[min(i+250,len(tdays)-1)]
    for t in cache:
        p0=px(t,d)
        if p0 is None or t not in sh or not(sh[t]>0): continue
        e0=ttm(t,d); e1=ttm(t,d1)
        if e0 and e0>0 and e1 is not None and e1>0:
            grow=e1/e0; fwdper=(p0*sh[t])/(e1*1e8)
            if 0<fwdper<200:
                r20=fwd_ret(t,d,20); r60=fwd_ret(t,d,60)
                if r20 is not None: rows.append({'fwdper':fwdper,'grow':grow,'r20':r20,'r60':r60})
df=pd.DataFrame(rows)
# ★정상성장만: grow 1.2~5x (흑자전환 이상치·역성장 제외)
g=df[(df['grow']>=1.2)&(df['grow']<=5.0)]
print(f"[fwd_per 재검증 — 정상성장(1.2~5x)만, 흑자전환 이상치 제외, n={len(g)}]\n")
print(f"  {'fwd_per 구간':<14}{'n':>6}{'평균성장':>9}{'fwd20':>8}{'fwd60':>8}{'승률20':>8}")
for lo,hi in [(0,10),(10,15),(15,20),(20,30),(30,50),(50,200)]:
    s=g[(g['fwdper']>=lo)&(g['fwdper']<hi)]
    if len(s)>0:
        print(f"  {f'{lo}~{hi}':<14}{len(s):>6}{s['grow'].mean():>8.2f}x{s['r20'].mean():>7.1f}%{s['r60'].mean():>7.1f}%{(s['r20']>0).mean()*100:>7.0f}%")
lo20=g[g['fwdper']<20]; hi20=g[g['fwdper']>=20]
print(f"\n  fwd_per<20 : n={len(lo20):5d}  fwd20 {lo20['r20'].mean():+.1f}%  fwd60 {lo20['r60'].mean():+.1f}%  승률 {(lo20['r20']>0).mean()*100:.0f}%")
print(f"  fwd_per>=20: n={len(hi20):5d}  fwd20 {hi20['r20'].mean():+.1f}%  fwd60 {hi20['r60'].mean():+.1f}%  승률 {(hi20['r20']>0).mean()*100:.0f}%")
# 더 거친 분할: <15 vs 15~25 vs >25
print(f"\n=== 3분할 (정상성장) ===")
for lbl,lo,hi in [('<15(쌈)',0,15),('15~25(중간)',15,25),('>25(비쌈)',25,200)]:
    s=g[(g['fwdper']>=lo)&(g['fwdper']<hi)]
    print(f"  {lbl:<12} n={len(s):5d}  fwd60 {s['r60'].mean():+.1f}%  승률 {(s['r20']>0).mean()*100:.0f}%")
