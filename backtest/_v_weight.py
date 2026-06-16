# -*- coding: utf-8 -*-
"""④ V(밸류) 비중 재검토 — 형 질문: PER 거의 죽었으면 V=0.15도 과한 것 아닌가?
corp-OFF baseline(_sp0b_co)서 V 스윕(0~25), Q=0, 빠진 비중은 G:M 55:30 비율 유지 재배분.
고정 12m E3X6S3. 전체 + WF 3블록. V=0이 전블록 일관 우위면 'V 줄여라', 노이즈면 신중."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
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
def load(folder):
    ar,dates={}, []
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
    return ar,sorted(dates)
OFF,dOFF=load('_sp0b_co'); common=sorted(dOFF); reg=calc_reg(common)
t=TurboSimulator({d:OFF[d] for d in common}, common, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
def cal(V, sub):
    g=(100-V)*55/85/100; m=(100-V)*30/85/100; v=V/100
    t._cached_key=None
    t._ensure_cache(v,0.0,g,m,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
# 주의: _ensure_cache는 common 전체 기준 flat 생성 → WF는 sub 슬라이스 위해 flat 재사용 불가, sub별 재계산
def cal_sub(V, lo, hi):
    sub=[d for d in common if lo<=d<=hi]
    ts={d:OFF[d] for d in sub}
    tt=TurboSimulator(ts, sub, prices, overheat_w=0.2); tt._use_overlay=True; tt._use_stored_growth=True
    g=(100-V)*55/85/100; m=(100-V)*30/85/100; v=V/100
    tt._ensure_cache(v,0.0,g,m,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(tt._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,tt._price_arr,tt._bench_arr,tt._has_bench,tt._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
print(f"[{common[0]}~{common[-1]} {len(common)}일] V 비중 스윕 (corp-OFF baseline, Q0, G:M=55:30 유지)")
print(f"\n{'V':>4}{'G':>5}{'M':>5}{'전체Cal':>9}{'19-21':>8}{'22-23':>8}{'24-26':>8}")
for V in [0,5,10,15,20,25]:
    g=round((100-V)*55/85); m=round((100-V)*30/85)
    c=cal(V,common)
    w1=cal_sub(V,'20190102','20211231'); w2=cal_sub(V,'20220101','20231231'); w3=cal_sub(V,'20240101','20261231')
    star=' ←현행' if V==15 else ''
    print(f"{V:>4}{g:>5}{m:>5}{c:>9.3f}{w1:>8.2f}{w2:>8.2f}{w3:>8.2f}{star}")
print(f"\n→ V=0이 전체+전블록(특히 약세장 22-23) 일관 우위면 'V 줄이고 G/M에 재배분' 지지. 일부만 우위/노이즈면 신중(현행 V15는 과거 12시나리오 우승, max-selection 편향 주의).")
