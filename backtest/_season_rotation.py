# -*- coding: utf-8 -*-
"""계절 로테이션 검증 (2026-06-29) — 사용자 일반론: 계절전환 감지→계절별 최적비율.
이론기반 고정비율(폴드 최적화X=과적합원천 제거). production-faithful(recent_ca ON).
A: 늦여름→퀄리티방어(내 제안)  B: 봄/여름/늦여름 3계절 로테이션(사용자 제안)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECENT_CA_W = 0.3
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
roll_high=kc.rolling(252,min_periods=60).max(); dd_series=1-kc/roll_high
mom126=kc/kc.shift(126)-1
def calc_reg(ds):
    reg={}; md=True; stk=0; ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md; continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
def season(d):
    """boost일의 계절. spring/late/summer."""
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    dd=dd_series.get(ts,np.nan); mm=mom126.get(ts,np.nan); px=kc.get(ts,np.nan); m20=ma20.get(ts,np.nan)
    if pd.notna(dd) and dd>0.10 and pd.notna(mm) and mm>0: return 'spring'   # 회복(겨울→여름)
    if pd.notna(dd) and dd<0.04 and pd.notna(px) and pd.notna(m20) and px<m20: return 'late'  # 고점부근 꺾임(여름→겨울)
    return 'summer'
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
ar_all={}; dall=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        ar_all[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dall.append(dt)
dall=sorted(dall)
def patch_ca(t, sd):
    for date, arr in t._overlay_pre.items():
        if arr is None: continue
        rk=sd.get(date)
        if rk is None: continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'): arr[j]-=RECENT_CA_W*float(s['recent_ca'])
def make(sub):
    sd={d:ar_all[d] for d in sub}
    t=TurboSimulator(sd, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    patch_ca(t,sd); return t
def flat_of(t,w):
    t._ensure_cache(w[0]/100,w[1]/100,w[2]/100,w[3]/100,0.4,20,'12m',*G3[:3],*G3[3:]); return list(t._cached_flat)
def run(t,sub,reg,mapping):
    """mapping: season名→weights. 'summer'는 base. flat stitching."""
    flats={k:flat_of(t,w) for k,w in mapping.items()}
    base=flats['summer']
    st=[ flats.get(season(sub[i]), base)[i] for i in range(len(sub)) ]
    r=_run_regime_inner(base,st,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)

BASE=(15,0,55,30); SPRING=(25,0,45,30); LATE=(15,20,45,20)
regF=calc_reg(dall); tF=make(dall)
sb=run(tF,dall,regF,{'summer':BASE})
# 계절 분포
from collections import Counter
cnt=Counter(season(d) for d in dall if regF[d])
print("="*68); print(f"계절 로테이션 | static base{BASE} full Calmar {sb[0]:.3f} MDD {sb[1]:.1f}%")
print(f"boost일 계절분포: {dict(cnt)}  (spring=V25G45M30, late=V15Q20G45M20, summer=base)")
print("="*68)

MAPS={
 'A 늦여름→퀄리티(내 제안)': {'summer':BASE, 'late':LATE},
 'B 3계절 로테이션(사용자)': {'summer':BASE, 'spring':SPRING, 'late':LATE},
 '(참고) 봄만(spring)':       {'summer':BASE, 'spring':SPRING},
}
print("\n[full 7.4년]")
for nm,mp in MAPS.items():
    c=run(tF,dall,regF,mp)
    print(f"  {nm:<26}: Calmar {c[0]:.3f} (Δ{c[0]-sb[0]:+.3f})  MDD {c[1]:.1f}%  누적 {c[2]:.0f}%")

print("\n[확장창 워크포워드 — 고정비율, 매 test년 OOS 평가 (파라미터 선택 없음=과적합 없음)]")
TESTS=['2022','2023','2024','2025','2026']
for nm,mp in MAPS.items():
    line=[]; wins=0; harm=0
    for ty in TESTS:
        te=[d for d in dall if d[:4]==ty]
        if len(te)<20: continue
        tte=make(te); rte=calc_reg(te)
        s=run(tte,te,rte,{'summer':BASE})[0]; d=run(tte,te,rte,mp)[0]
        wins+=(d>s+0.001); harm+=(d<s-0.10)
        line.append(f"{ty}{d-s:+.2f}")
    print(f"  {nm:<26}: OOS우세 {wins}/{len(TESTS)} 악화 {harm}  [{' '.join(line)}]")
print("\n[완료]")
