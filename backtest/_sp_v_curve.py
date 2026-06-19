# -*- coding: utf-8 -*-
"""V별 best Calmar 곡선: annual(_sp0c) vs TTM(_sp3), 균등기준. V 올릴수록 좋아지나?
각 V에서 Q/G/모멘텀/슬롯 최적. → TTM이 V↑로 좋아지면 'V≥15 봐야', 나빠지면 'TTM value 안 씀'."""
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
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0, np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def load(folder):
    ar, dates = {}, []
    for f in sorted(glob.glob(os.path.join(PROJ, folder, 'ranking_*.json'))):
        dt = os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt) == 8: ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
MOMS = ['6m', '6m-1m', '12m', '12m-1m']; SLOTS = [(3,3,6),(5,5,10),(10,10,20)]
ar0, d0 = load('_sp0c'); ar3, d3 = load('_sp3')
common = sorted(set(d0) & set(d3)); reg = calc_reg(common)
print(f"[{common[0]}~{common[-1]} {len(common)}일] V별 best Calmar (각 V서 Q/G/모멘텀/슬롯 최적)")
print(f"\n{'V':>4}{'annual-균등 best':>20}{'TTM-균등 best':>20}")
for ar, lbl, res in [(ar0,'annual',{}), (ar3,'TTM',{})]:
    t = TurboSimulator({d:ar[d] for d in common}, common, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    for V in [10,15,20,25,30]:
        best=-9; bc=None
        for q in [0,5,10]:
            for g in range(15,70,5):
                m=100-V-q-g
                if not(10<=m<=60): continue
                for mm in MOMS:
                    t._ensure_cache(V/100,q/100,g/100,m/100,0.4,20,mm,*G3[:3],*G3[3:])
                    flat=list(t._cached_flat)
                    for sl,e,x in SLOTS:
                        c=_run_regime_inner(flat,flat,0,x,sl,e,x,sl,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
                        if c>best: best=c; bc=(q,g,m,mm,sl)
        res[V]=(best,bc)
    globals()[lbl+'_res']=res
for V in [10,15,20,25,30]:
    a=annual_res[V]; tt=TTM_res[V]
    print(f"{V:>4}{f'{a[0]:.2f} Q{a[1][0]}G{a[1][1]}M{a[1][2]} {a[1][3]} S{a[1][4]}':>20}{f'{tt[0]:.2f} Q{tt[1][0]}G{tt[1][1]}M{tt[1][2]} {tt[1][3]} S{tt[1][4]}':>20}")
print("\n→ annual은 V↑로 어디서 정점? TTM은? TTM이 V↑로 나빠지면 옵티마이저가 TTM value를 안 원하는 것(V≥10 floor에 붙음).")
