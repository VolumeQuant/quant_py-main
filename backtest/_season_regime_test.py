# -*- coding: utf-8 -*-
"""계절 온도계 동적전환 검증 (2026-06-29) — 사용자 "계절옷" 통찰.
온도계=시장 드로다운 오버행(KOSPI 1년최고 대비 하락폭). 밸류계절(회복중)엔 밸류틸트↑, 아니면 모멘텀.
날짜별 flat stitching(가중치 동적전환). production-faithful(recent_ca ON).
1차 관문=full + 워크포워드(V20이 떨어진 그 OOS 시험). 통과시에만 LOWO/과열캡."""
import sys, io, os, glob, json, time
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
roll_high = kc.rolling(252, min_periods=60).max()
dd_series = 1 - kc/roll_high   # 1년최고 대비 하락폭(오버행)
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
ma120k = kc.rolling(120).mean()
mom126 = kc/kc.shift(126) - 1   # 6개월 시장 수익률
CONFIRM = os.environ.get('CONFIRM','')  # 'ma120' 또는 'mom6' 면 회복확인 추가
def dd_of(d):
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    v=dd_series.get(ts, np.nan)
    return float(v) if pd.notna(v) else 0.0
def is_value_season(d, thr):
    if dd_of(d) <= thr: return False
    if not CONFIRM: return True
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if CONFIRM=='ma120':
        m=ma120k.get(ts,np.nan); return bool(pd.notna(m) and kc.get(ts,0)>m)  # 장기 상승추세 확인
    if CONFIRM=='mom6':
        r=mom126.get(ts,np.nan); return bool(pd.notna(r) and r>0)  # 6개월 +회복 확인
    return True
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
def flat_of(t, vqgm):
    v,q,g,m=vqgm
    t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    return list(t._cached_flat)
def run_static(t, sub, reg, vqgm):
    fl=flat_of(t,vqgm)
    r=_run_regime_inner(fl,fl,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
def run_dynamic(t, sub, reg, base, valw, thr):
    fb=flat_of(t,base); fv=flat_of(t,valw)
    stitched=[ (fv[i] if is_value_season(sub[i],thr) else fb[i]) for i in range(len(sub)) ]
    r=_run_regime_inner(fb,stitched,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)

BASE=(15,0,55,30)
regF=calc_reg(dall)
print("="*70); print("계절 온도계 동적전환 — 밸류계절(드로다운>thr)엔 밸류틸트, 아니면 모멘텀"); print("="*70)

# EDA: 온도계가 켜진 날 분포 (국면별)
print("\n[EDA] 드로다운 오버행 분포 & 밸류계절 비율(boost일 한정)")
boostd=[d for d in dall if regF[d]]
for thr in [0.08,0.12,0.16,0.20]:
    vs=[d for d in boostd if is_value_season(d,thr)]
    by={}
    for d in vs: by.setdefault(d[:4],0); by[d[:4]]+=1
    print(f"  thr {thr:.2f}: 밸류계절 {len(vs)}/{len(boostd)} boost일 ({len(vs)/len(boostd)*100:.0f}%)  연도분포 {dict(sorted(by.items()))}")

# 1차 관문: full + WF, base(static) vs dynamic 여러 valw/thr
print("\n[1차] static BASE vs 동적전환  (valw=밸류계절 가중치, thr=드로다운 임계)")
tF=make(dall)
base_full=run_static(tF,dall,regF,BASE)
print(f"  static BASE V15Q0G55M30 full: Calmar {base_full[0]:.3f}  MDD {base_full[1]:.1f}%")
VALWS=[(20,0,55,25),(25,0,55,20),(25,0,45,30)]
FOLDS=[('19-20','20190102','20201231'),('21-22','20210101','20221231'),
       ('23-24','20230101','20241231'),('25-26','20250101','20261231')]
foldobj={nm:(make([d for d in dall if lo<=d<=hi]),[d for d in dall if lo<=d<=hi]) for nm,lo,hi in FOLDS}
foldreg={nm:calc_reg(foldobj[nm][1]) for nm,_,_ in [(n,a,b) for n,a,b in FOLDS]}
for valw in VALWS:
    print(f"\n  ── 밸류계절 가중치 = V{valw[0]}Q{valw[1]}G{valw[2]}M{valw[3]} ──")
    for thr in [0.10,0.14,0.18]:
        df=run_dynamic(tF,dall,regF,BASE,valw,thr)
        wfwins=0; wfline=[]
        for nm,_,_ in FOLDS:
            tf,sub=foldobj[nm]; reg=foldreg[nm]
            b=run_static(tf,sub,reg,BASE)[0]; d=run_dynamic(tf,sub,reg,BASE,valw,thr)[0]
            wfwins+= (d>b+0.001); wfline.append(f"{nm}{'+'if d>b+0.001 else '-'}{d-b:+.2f}")
        print(f"    thr{thr:.2f}: full Cal {df[0]:.3f}(Δ{df[0]-base_full[0]:+.3f}) MDD{df[1]:.1f}%  | WF {wfwins}/4  [{' '.join(wfline)}]")
print("\n[해석] full Δ>+0.1 AND WF 3~4/4 동시 통과해야 1차통과(V20은 WF 2/4서 탈락). 그래야 LOWO/과열캡 진행.")
