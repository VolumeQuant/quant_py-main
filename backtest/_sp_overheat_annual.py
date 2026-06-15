# -*- coding: utf-8 -*-
"""과열캡 ON(0.2) vs OFF(0.0) — annual(프로덕션 state) 검증 (2026-06-15).
사용자 의심: TTM이 과열캡과 충돌해 나쁜가? 먼저 annual에서 과열캡 효과 isolate.
재생성 불요(state에 overheat_pen 저장됨, TurboSim _overheat_w로 토글)."""
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
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_*_2026061*.parquet')))[0]).replace(0,np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
def calc_reg(dsub):
    reg={};md=True;stk=0;ss=None
    for d in dsub:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
ar,dates={},[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and '20190102'<=dt<='20261231':
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
dates=sorted(dates)
reg=calc_reg(dates)
def regbt(tsim,v,q,g,m):
    tsim._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(tsim._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,dates,tsim._price_arr,tsim._bench_arr,
        tsim._has_bench,tsim._date_row_indices,len(dates),None,None,None,None,
        stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
combos=[(v,q,g,100-v-q-g) for v in range(0,45,5) for q in range(0,45,5) for g in range(10,75,5) if 10<=100-v-q-g<=60]
print(f'[annual/프로덕션 state] {dates[0]}~{dates[-1]} {len(dates)}일\n')
for ow,lbl in [(0.2,'과열캡 ON (0.2, 현행)'),(0.0,'과열캡 OFF (0.0)')]:
    tsim=TurboSimulator(ar,dates,prices,overheat_w=ow); tsim._use_overlay=True; tsim._use_stored_growth=True
    prod=regbt(tsim,15,0,55,30)
    res=sorted([(v,q,g,m,regbt(tsim,v,q,g,m).get('calmar',0)) for v,q,g,m in combos],key=lambda x:-x[4])
    b=res[0]
    print(f'=== {lbl} ===')
    print(f'  production V15Q0G55M30: Cal {prod["calmar"]:.3f} (CAGR {prod["cagr"]:.0f} MDD {prod["mdd"]:.0f})')
    print(f'  재최적 best: V{b[0]}Q{b[1]}G{b[2]}M{b[3]} Cal {b[4]:.3f}')
    print(f'  상위3: '+' / '.join(f'V{r[0]}Q{r[1]}G{r[2]}M{r[3]}={r[4]:.2f}' for r in res[:3]))
