# -*- coding: utf-8 -*-
"""V20·Q0·G55·M25 끝장 검증 vs production V15·Q0·G55·M30 (2026-06-29).
production-faithful 하니스(recent_ca -0.3 overlay 주입). 4종:
 A 인접 고원(plateau vs spike)  B 워크포워드(비중첩 폴드 OOS)
 C LOWO(승자 제외)  D 과열캡×슬롯 재최적(밸류 이중계산 점검)."""
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

def build(sub, overheat_w=0.2, exclude=None):
    if exclude:
        sd={d:[r for r in ar_all[d] if r['ticker'] not in exclude] for d in sub}
    else:
        sd={d:ar_all[d] for d in sub}
    t=TurboSimulator(sd, sub, prices, overheat_w=overheat_w); t._use_overlay=True; t._use_stored_growth=True
    patch_ca(t, sd)
    return t

def bt(t, sub, reg, vqgm, slots=(3,6)):
    v,q,g,m=vqgm; sl,ex=slots
    t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,ex,sl,sl,ex,sl,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)

PROD=(15,0,55,30); CAND=(20,0,55,25)
regF=calc_reg(dall)
print("="*70)
print(f"끝장 검증: CAND V20Q0G55M25  vs  PROD V15Q0G55M30 | recent_ca ON | full {dall[0]}~{dall[-1]}")
print("="*70)

# ---------- A. 인접 고원 ----------
print("\n[A] 인접 고원 (full 7.4년 Calmar) — 봉우리(spike)면 과적합, 고원(plateau)면 robust")
tF=build(dall)
Vs=[10,15,20,25]; Gs=[50,55,60]
print("        " + "  ".join(f"V{v}" for v in Vs))
for gg in Gs:
    row=[]
    for v in Vs:
        m=100-v-gg
        if m<15 or m>40: row.append("  -  "); continue
        c=bt(tF,dall,regF,(v,0,gg,m))[0]; row.append(f"{c:5.2f}")
    print(f"  G{gg}M*: "+"  ".join(row))
pc=bt(tF,dall,regF,PROD)[0]; cc=bt(tF,dall,regF,CAND)[0]
neigh=[bt(tF,dall,regF,(v,0,g,100-v-g))[0] for v,g in [(15,55),(20,55),(25,55),(20,50),(20,60),(15,60),(25,50)] if 15<=100-v-g<=40]
print(f"  PROD {pc:.3f}  CAND {cc:.3f}  | CAND 주변7개 평균 {np.mean(neigh):.2f} CV {np.std(neigh)/np.mean(neigh):.3f}")

# ---------- B. 워크포워드 (비중첩 폴드) ----------
print("\n[B] 워크포워드 — 비중첩 폴드별 CAND vs PROD (OOS, 두 후보 고정비교)")
FOLDS=[('19-20','20190102','20201231'),('21-22','20210101','20221231'),
       ('23-24','20230101','20241231'),('25-26','20250101','20261231')]
cwin=0
for nm,lo,hi in FOLDS:
    sub=[d for d in dall if lo<=d<=hi]; reg=calc_reg(sub); t=build(sub)
    p=bt(t,sub,reg,PROD); c=bt(t,sub,reg,CAND)
    win='CAND' if c[0]>p[0] else 'PROD'; cwin+= (c[0]>p[0])
    print(f"  {nm} ({len(sub)}일): PROD Cal {p[0]:.2f}/MDD{p[1]:.0f}%  CAND Cal {c[0]:.2f}/MDD{c[1]:.0f}%  → {win} (Δ{c[0]-p[0]:+.2f})")
print(f"  → CAND이 {cwin}/{len(FOLDS)} 폴드 우세")

# ---------- C. LOWO ----------
print("\n[C] LOWO — 승자 1종목씩 제외 후 full (단일종목 착시면 CAND 우위 사라짐)")
WINNERS={'033100':'제룡전기','000660':'SK하이닉스','080220':'제주반도체',
         '042700':'한미반도체','039030':'이오테크닉스','187870':'디바이스이엔지'}
base_p=pc; base_c=cc
print(f"  (제외없음) PROD {base_p:.2f}  CAND {base_c:.2f}  Δ{base_c-base_p:+.2f}")
csurv=0
for tk,nmn in WINNERS.items():
    t=build(dall, exclude={tk}); p=bt(t,dall,regF,PROD)[0]; c=bt(t,dall,regF,CAND)[0]
    survive=c>p; csurv+=survive
    print(f"  −{nmn:<8}: PROD {p:.2f}  CAND {c:.2f}  Δ{c-p:+.2f}  {'✅CAND유지' if survive else '❌역전'}")
print(f"  → CAND 우위가 {csurv}/{len(WINNERS)} 종목제외에서 생존")

# ---------- D. 과열캡 × 슬롯 ----------
print("\n[D] 과열캡 재최적(밸류 이중계산 점검) + 슬롯 — full")
for oh in [0.0,0.1,0.2,0.3]:
    t=build(dall, overheat_w=oh); p=bt(t,dall,regF,PROD)[0]; c=bt(t,dall,regF,CAND)[0]
    print(f"  과열캡 W={oh}: PROD {p:.2f}  CAND {c:.2f}  Δ{c-p:+.2f}")
print("   ※ 과열캡0에서 Δ가 커지면=밸류가 과열캡과 중복(이중계산), 비슷하면=독립효과")
for sl,ex in [(3,6),(3,4),(5,10)]:
    p=bt(tF,dall,regF,PROD,slots=(sl,ex))[0]; c=bt(tF,dall,regF,CAND,slots=(sl,ex))[0]
    print(f"  슬롯S{sl}/X{ex}: PROD {p:.2f}  CAND {c:.2f}  Δ{c-p:+.2f}")
print("\n[완료]")
