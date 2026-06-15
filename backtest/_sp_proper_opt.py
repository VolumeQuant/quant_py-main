# -*- coding: utf-8 -*-
"""제대로 된 TTM 최적화 (2026-06-16) — ★효율판: TurboSim 폴더당 1회 생성 + _ensure_cache 슬롯간 재사용.
밸류 강제사용(V>=10) + 멀티팩터×슬롯 동시 최적. 같은배치 _sp0b(annual) vs _sp2b(TTM)."""
import sys, io, os, glob, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50:s2.loc[s2.index<d]*=f
    return s2
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)):reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss:stk+=1
        else:stk=1;ss=s
        if stk>=5 and md!=s:md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def load(folder):
    ar,dates={},[]
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8:ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dates.append(dt)
    return ar,sorted(dates)
combos=[(v,q,g,100-v-q-g) for v in [10,15,20,25,30] for q in [0,5,10] for g in range(15,70,5) if 10<=100-v-q-g<=60]
# (slots, entry, exit) — exit>entry. S3/E3/X6=production
SLOTS=[(3,3,6),(5,5,10),(10,10,20),(15,15,30)]
_LO=os.environ.get('OPT_LO','20190102'); _HI=os.environ.get('OPT_HI','20261231')
ar0,d0=load('_sp0b');ar2,d2=load('_sp2b')
common=sorted([d for d in (set(d0)&set(d2)) if _LO<=d<=_HI]);reg=calc_reg(common)
print(f"[기간 {common[0]}~{common[-1]} {len(common)}일]")
arc0={d:ar0[d] for d in common};arc2={d:ar2[d] for d in common}
print(f"밸류강제 V>=10 멀티팩터 {len(combos)}조합 × 슬롯{len(SLOTS)}종 (★TurboSim 폴더당1회+캐시재사용)\n")
# ★핵심: 폴더당 TurboSim 1번 생성, 멀티팩터 _ensure_cache 1번 → 슬롯 4종 flat 재사용
results={}  # folder -> {slots: best}
for ar,lbl in [(arc0,'annual'),(arc2,'TTM')]:
    t0=time.time()
    t=TurboSimulator(ar,common,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    best={s[0]:(None,-9) for s in SLOTS}   # key=slots
    for v,q,g,m in combos:
        t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])  # 1회/가중치
        flat=list(t._cached_flat)
        for slots,entry,exit_ in SLOTS:   # ★(slots,entry,exit) 올바른 순서, exit>entry
            cal=_run_regime_inner(flat,flat,0,exit_,slots,entry,exit_,slots,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
            if cal>best[slots][1]: best[slots]=((v,q,g,m),cal)
    results[lbl]=best
    print(f"  [{lbl}] 완료 {time.time()-t0:.0f}초")
print(f"\n{'슬롯(E/X)':<14}{'annual best (V>=10)':<26}{'TTM best (V>=10)':<26}{'TTM-ann':>8}")
for slots,entry,exit_ in SLOTS:
    a=results['annual'][slots];tt=results['TTM'][slots]
    av,ac=a;tv,tc=tt
    print(f"{('S'+str(slots)+'(E'+str(entry)+'X'+str(exit_)+')'):<14}V{av[0]}Q{av[1]}G{av[2]}M{av[3]}={ac:.2f}{'':<8}V{tv[0]}Q{tv[1]}G{tv[2]}M{tv[3]}={tc:.2f}{'':<8}{tc-ac:>+7.2f}")
print("\n→ 밸류 강제사용. TTM best가 annual best보다 일관 크면 'TTM 밸류 우월'. 슬롯 클수록(노이즈↓) 신뢰.")
