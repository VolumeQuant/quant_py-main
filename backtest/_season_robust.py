# -*- coding: utf-8 -*-
"""계절 동적전환 강건성 최종 라운드 (2026-06-29).
①밸류 옷 이웃 강건성 ②확장창 워크포워드(train서 파라미터 선택→test OOS) ③회복확인 정의 강건성.
base V15Q0G55M30, 밸류계절(드로다운>thr AND 회복확인)엔 valw. production-faithful(recent_ca ON)."""
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
def momwin(w): return kc/kc.shift(w)-1
MOM={w:momwin(w) for w in (105,126,147)}
ma120k=kc.rolling(120).mean()
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
def vseason(d, thr, conf='mom126'):
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    dd=dd_series.get(ts,np.nan)
    if not (pd.notna(dd) and dd>thr): return False
    if conf=='ma120':
        m=ma120k.get(ts,np.nan); return bool(pd.notna(m) and kc.get(ts,0)>m)
    w=int(conf[3:]); r=MOM[w].get(ts,np.nan); return bool(pd.notna(r) and r>0)
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
_FCACHE={}
def make(sub):
    sd={d:ar_all[d] for d in sub}
    t=TurboSimulator(sd, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    patch_ca(t,sd); return t
def flat_of(t,w):
    t._ensure_cache(w[0]/100,w[1]/100,w[2]/100,w[3]/100,0.4,20,'12m',*G3[:3],*G3[3:]); return list(t._cached_flat)
def cal_static(t,sub,reg,w):
    fl=flat_of(t,w)
    return _run_regime_inner(fl,fl,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
def cal_dyn(t,sub,reg,base,valw,thr,conf='mom126'):
    fb=flat_of(t,base); fv=flat_of(t,valw)
    st=[ (fv[i] if vseason(sub[i],thr,conf) else fb[i]) for i in range(len(sub)) ]
    return _run_regime_inner(fb,st,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)

BASE=(15,0,55,30)
VALWS=[(v,0,g,100-v-g) for v in (20,25,30) for g in (45,50,55) if 15<=100-v-g<=40]
regF=calc_reg(dall); tF=make(dall); sb=cal_static(tF,dall,regF,BASE)
print("="*70); print(f"강건성 최종 | base{BASE} static full Calmar {sb:.3f} | recent_ca ON"); print("="*70)

# ── ① 밸류 옷 이웃 강건성 (full, conf=mom126, thr 0.08 & 0.11 둘 다) ──
print("\n[①] 밸류 옷 이웃 강건성 — valw 9종 × thr2개, full ΔCalmar (대부분 +면 방향 robust)")
print(f"   {'valw':<16}{'thr0.08':>9}{'thr0.11':>9}")
pos=0; tot=0
for w in VALWS:
    d8=cal_dyn(tF,dall,regF,BASE,w,0.08)-sb; d11=cal_dyn(tF,dall,regF,BASE,w,0.11)-sb
    pos+=(d8>0)+(d11>0); tot+=2
    print(f"   V{w[0]}Q0G{w[2]}M{w[3]:<8}{d8:>+9.3f}{d11:>+9.3f}")
print(f"   → {pos}/{tot} 양수 (방향 일관성)")

# ── ② 확장창 워크포워드 (train서 valw×thr 선택 → test OOS) ──
print("\n[②] 확장창 워크포워드 — 매 test년: 이전 전체 train서 best(valw,thr) 선택 → test에 적용")
THRS=[0.08,0.10,0.12]
TESTS=['2022','2023','2024','2025','2026']
dynwin=0; harm=0
for ty in TESTS:
    tr=[d for d in dall if d[:4]<ty]; te=[d for d in dall if d[:4]==ty]
    if len(tr)<200 or len(te)<20: continue
    ttr=make(tr); rtr=calc_reg(tr)
    best=None;bc=-9
    for w in VALWS:
        for thr in THRS:
            c=cal_dyn(ttr,tr,rtr,BASE,w,thr)
            if c>bc: bc=c;best=(w,thr)
    tte=make(te); rte=calc_reg(te)
    s=cal_static(tte,te,rte,BASE); d=cal_dyn(tte,te,rte,BASE,best[0],best[1])
    win=d>s+0.001; dynwin+=win; harm+=(d<s-0.10)
    print(f"   test {ty} (train {tr[0][:4]}~{tr[-1][:4]} {len(tr)}일): 선택 V{best[0][0]}G{best[0][2]}M{best[0][3]}/thr{best[1]:.2f}  → static {s:.2f} dyn {d:.2f}  Δ{d-s:+.2f}  {'✅OOS우세' if win else '❌'}")
print(f"   → dyn OOS우세 {dynwin}/{len(TESTS)}, 유의미악화(<-0.10) {harm}회")

# ── ③ 회복확인 정의 강건성 (full, valw=V25G45M30, thr0.10) ──
print("\n[③] 회복확인 정의 강건성 — 온도계 정의 바꿔도 +면 robust (valw V25G45M30 thr0.10)")
for conf in ['mom105','mom126','mom147','ma120']:
    d=cal_dyn(tF,dall,regF,BASE,(25,0,45,30),0.10,conf)
    print(f"   회복확인={conf:<7}: dyn {d:.3f}  Δ{d-sb:+.3f}")
print("\n[완료]")
