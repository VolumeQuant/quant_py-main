# -*- coding: utf-8 -*-
import sys, io, os
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = r'C:\dev\claude-code\quant_py-main'
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf_history.parquet')).iloc[:,0].sort_index()
kc = kc.dropna()
ma20, ma80 = kc.rolling(20).mean(), kc.rolling(80).mean()
idx = kc.index
md=True; stk=0; ss=None; reg={}
for ts in idx:
    if pd.isna(ma80.get(ts,np.nan)): reg[ts]=md; continue
    s=bool(ma20[ts]>ma80[ts])
    if s==ss: stk+=1
    else: stk=1; ss=s
    if stk>=5 and md!=s: md=s
    reg[ts]=md
reg=pd.Series(reg)
def fwd(ts,n):
    p=idx.get_loc(ts)
    return np.nan if p+n>=len(idx) else (kc.iloc[p+n]/kc.loc[ts]-1)*100

print("="*68)
print("【2019년 이전】 주요 급락(고점대비 -15%↑) 별 국면 대응")
print("="*68)
runpeak=kc.cummax(); dd=kc/runpeak-1
episodes=[]; in_ep=False
for ts in idx:
    if dd.loc[ts]<=-0.15 and not in_ep:
        in_ep=True; ep_peak=runpeak.loc[ts]
        ep_peak_dt=kc[kc.index<=ts][kc[kc.index<=ts]==ep_peak].index[-1]
        trough=kc.loc[ts]; trough_dt=ts
    if in_ep:
        if kc.loc[ts]<trough: trough=kc.loc[ts]; trough_dt=ts
        if kc.loc[ts]>=ep_peak: episodes.append((ep_peak_dt,ep_peak,trough_dt,trough)); in_ep=False
if in_ep: episodes.append((ep_peak_dt,ep_peak,trough_dt,trough))
for pk_dt,pk,tr_dt,tr in episodes:
    decline=(tr/pk-1)*100
    seg=reg[(reg.index>=pk_dt)&(reg.index<=tr_dt)]
    first_def=next((t for t,v in seg.items() if not v),None)
    days=(tr_dt-pk_dt).days
    print(f"\n● {pk_dt.date()} {pk:,.0f} → {tr_dt.date()} {tr:,.0f}  {decline:.0f}% ({days}일)")
    if first_def is None:
        before=reg[reg.index<=pk_dt]
        if len(before) and not before.iloc[-1]: print("   🛡️ 고점 이전부터 이미 방어(선제 회피)")
        else: print("   ❌ 방어 전환 없음(놓침)")
    else:
        lvl=kc.loc[first_def]; missed=(lvl/pk-1)*100; avoided=(tr/lvl-1)*100
        g='✅조기' if missed>-10 else '⚠️늦음' if missed>-20 else '❌많이놓침'
        print(f"   🛡️ {first_def.date()} @ {lvl:,.0f}: 놓침 {missed:+.0f}% / 회피 {avoided:+.0f}% {g}")

# 강세 복귀(공격 전환) 타이밍
print("\n"+"="*68)
print("【2019년 이전】 강세장 복귀(공격 전환) 타이밍")
print("="*68)
boost=[]; prev=None
for ts,v in reg.items():
    if prev is not None and v and not prev: boost.append(ts)
    prev=v
f60=[fwd(t,60) for t in boost]; f60=[x for x in f60 if not np.isnan(x)]
f120=[fwd(t,120) for t in boost]; f120=[x for x in f120 if not np.isnan(x)]
print(f"  공격 전환 {len(boost)}회")
print(f"  진입후 +60일 코스피: 평균 {np.mean(f60):+.1f}% / 승률 {np.mean([x>0 for x in f60])*100:.0f}%")
print(f"  진입후 +120일 코스피: 평균 {np.mean(f120):+.1f}% / 승률 {np.mean([x>0 for x in f120])*100:.0f}%")
bd=reg.reindex(idx).ffill().astype(bool); ret=kc.pct_change()*100
print(f"\n  공격구간 코스피 평균 일수익 {ret[bd].mean():+.3f}% / 방어구간 {ret[~bd].mean():+.3f}%")
print(f"  공격 {bd.mean()*100:.0f}% / 방어 {(1-bd.mean())*100:.0f}% 시간비중")
print(f"  검증기간 {idx.min().date()} ~ {idx.max().date()}")
