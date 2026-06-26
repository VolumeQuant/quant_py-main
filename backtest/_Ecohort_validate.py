# -*- coding: utf-8 -*-
"""E(고모멘텀 V면제) 표본검증 — 월별 스냅샷 mode C 재생성 → E가 살릴 코호트(V<-1.5 & M>=1.0 & Q/G>=-1.5)
forward 수익 측정. 좋으면 E 유망, 나쁘면 기각. (브이엠 1종목 → 90스냅샷 다종목으로 확장)"""
import sys, io, os, json, glob, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
sys.path.insert(0,'C:/dev')
from regime_indicator import get_regime_params
import run_daily as RD
px=pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan);px=px.dropna(how='all')
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
def fwd(t,d,h):
    if t not in pcol or d not in tdi: return None
    i=tdi[d];d2=tdays[min(i+h,len(tdays)-1)];p0=parr[i,pcol[t]];p1=parr[tdi[d2],pcol[t]]
    return (p1/p0-1)*100 if p0>0 and p1>0 else None
# 월별 첫 거래일 (2019~2026-06, forward 위해 끝에서 60일 여유)
snaps=[]
seen=set()
for d in tdays:
    if '20190102'<=d<=tdays[-60]:
        ym=d[:6]
        if ym not in seen: seen.add(ym);snaps.append(d)
boost=get_regime_params('boost')
env={**os.environ,'PYTHONIOENCODING':'utf-8',**RD._build_mode_env(boost)};env.pop('PRODUCTION_MODE',None);env['EXTREME_MODE']='C'
sd='C:/dev/state_Csnap';os.makedirs(sd,exist_ok=True)
print(f"월별 스냅샷 {len(snaps)}일 mode C 재생성 시작...",flush=True)
ecoh=[];still_excl=[];kept=[]   # E재admit / E도제외(V낮고 저모멘텀) / baseline유지(상위)
t0=time.time()
for k,d in enumerate(snaps):
    f=os.path.join(sd,f'ranking_{d}.json')
    if not os.path.exists(f):
        subprocess.run([sys.executable,'-u','C:/dev/backtest/fast_generate_rankings_v2.py',d,d,f'--state-dir={sd}'],env=env,cwd='C:/dev',capture_output=True,timeout=300)
    if not os.path.exists(f): continue
    rk=json.load(open(f,encoding='utf-8'))['rankings']
    for x in rk:
        v,m=x.get('value_s'),x.get('momentum_s');q,g=x.get('quality_s'),x.get('growth_s')
        if not all(isinstance(z,(int,float)) for z in [v,m,q,g]): continue
        r60=fwd(x['ticker'],d,60)
        if r60 is None: continue
        if v<-1.5 and m>=1.0 and q>=-1.5 and g>=-1.5: ecoh.append(r60)        # E가 살림
        elif v<-1.5 and m<1.0 and q>=-1.5 and g>=-1.5: still_excl.append(r60) # V낮은데 저모멘텀(E도 제외)
        elif v>=-1.5 and q>=-1.5 and g>=-1.5 and m>=-1.5: kept.append(r60)    # 정상 통과
    if (k+1)%20==0: print(f"  {k+1}/{len(snaps)} ({(time.time()-t0)/60:.0f}분)",flush=True)
print(f"\n[E 표본검증 결과 — {len(snaps)}스냅샷, fwd60]")
def stat(a,nm):
    a=np.array(a)
    if len(a)<5: print(f"  {nm}: n={len(a)} 부족");return
    print(f"  {nm:30s} n={len(a):5d}  평균 {a.mean():+.1f}%  승률 {(a>0).mean()*100:.0f}%  중앙 {np.median(a):+.1f}%")
stat(ecoh,'★E가 살리는 코호트(고모멘텀 비싼)')
stat(still_excl,'V낮은데 저모멘텀(E도 제외)')
stat(kept,'정상 통과(baseline 유지)')
print(f"\n  → E 코호트가 정상통과보다 좋으면 E 유망, 나쁘면(트랩) 기각")
