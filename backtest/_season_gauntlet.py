# -*- coding: utf-8 -*-
"""계절 동적전환 후보 풀 관문 (2026-06-29) — WF 4/4 통과한 단일후보를 V20 죽인 그 관문에.
후보: base V15Q0G55M30, 밸류계절(드로다운>thr AND 6개월시장수익>0)엔 valw V25Q0G45M30.
풀관문: ①정밀 임계 고원 ②LOWO ③과열캡 재최적. production-faithful(recent_ca ON)."""
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
def vseason(d, thr):
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    dd=dd_series.get(ts,np.nan); mm=mom126.get(ts,np.nan)
    return bool(pd.notna(dd) and dd>thr and pd.notna(mm) and mm>0)
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
def make(sub, oh=0.2, exclude=None):
    sd=({d:[r for r in ar_all[d] if r['ticker'] not in exclude] for d in sub} if exclude
        else {d:ar_all[d] for d in sub})
    t=TurboSimulator(sd, sub, prices, overheat_w=oh); t._use_overlay=True; t._use_stored_growth=True
    patch_ca(t,sd); return t
def flat_of(t,w):
    t._ensure_cache(w[0]/100,w[1]/100,w[2]/100,w[3]/100,0.4,20,'12m',*G3[:3],*G3[3:]); return list(t._cached_flat)
def cal_static(t,sub,reg,w):
    fl=flat_of(t,w)
    return _run_regime_inner(fl,fl,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
def cal_dyn(t,sub,reg,base,valw,thr):
    fb=flat_of(t,base); fv=flat_of(t,valw)
    st=[ (fv[i] if vseason(sub[i],thr) else fb[i]) for i in range(len(sub)) ]
    return _run_regime_inner(fb,st,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)

BASE=(15,0,55,30); VALW=(25,0,45,30); THR=0.10
regF=calc_reg(dall); tF=make(dall)
sb=cal_static(tF,dall,regF,BASE)
print("="*68); print(f"동적전환 후보 풀관문 | base{BASE} → 밸류계절 valw{VALW} | 온도계=드로다운>thr & 6m>0")
print(f"static BASE full Calmar {sb:.3f}"); print("="*68)

print("\n[1] 정밀 임계 고원 (full, thr 미세변화에 Δ 안정?=plateau, 출렁=spike)")
for thr in [0.06,0.07,0.08,0.09,0.10,0.11,0.12,0.13]:
    d=cal_dyn(tF,dall,regF,BASE,VALW,thr)
    print(f"  thr {thr:.2f}: dyn {d:.3f}  Δ{d-sb:+.3f}")

print("\n[2] LOWO (thr0.10 고정, 승자 제외 후 static vs dynamic)")
WIN={'033100':'제룡전기','000660':'SK하이닉스','080220':'제주반도체','042700':'한미반도체','039030':'이오테크닉스','187870':'디바이스이엔지'}
print(f"  (제외없음) static {sb:.3f}  dyn {cal_dyn(tF,dall,regF,BASE,VALW,THR):.3f}  Δ{cal_dyn(tF,dall,regF,BASE,VALW,THR)-sb:+.3f}")
surv=0
for tk,nm in WIN.items():
    t=make(dall,exclude={tk}); s=cal_static(t,dall,regF,BASE); d=cal_dyn(t,dall,regF,BASE,VALW,THR)
    surv+=(d>s+0.001); print(f"  −{nm:<8}: static {s:.3f}  dyn {d:.3f}  Δ{d-s:+.3f}  {'✅' if d>s+0.001 else '❌'}")
print(f"  → dyn 우위 {surv}/{len(WIN)} 생존")

print("\n[3] 과열캡 재최적 (각 W서 static vs dynamic — V20은 여기서 죽음)")
for oh in [0.0,0.1,0.2,0.3]:
    t=make(dall,oh=oh); s=cal_static(t,dall,regF,BASE); d=cal_dyn(t,dall,regF,BASE,VALW,THR)
    print(f"  과열캡W={oh}: static {s:.3f}  dyn {d:.3f}  Δ{d-s:+.3f}")
print("\n[완료]")
