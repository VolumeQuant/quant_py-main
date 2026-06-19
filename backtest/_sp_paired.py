# -*- coding: utf-8 -*-
"""강건성 결정판: 동일 config끼리 paired 비교 (annual-균등 _sp0c vs TTM-균등 _sp3).
1740 config 각각 annual vs TTM → annual 승률% + 평균/중앙 Δ + V별 분해. + 밸류 IC.
max-selection 편향 없음(같은 config 양쪽). config 무관 annual 우위면 robust."""
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
COMBOS = [(v, q, g, 100-v-q-g) for v in [10,15,20,25,30] for q in [0,5,10] for g in range(15,70,5) if 10 <= 100-v-q-g <= 60]
ar0, d0 = load('_sp0c'); ar3, d3 = load('_sp3')
common = sorted(set(d0) & set(d3)); reg = calc_reg(common)
a0 = {d: ar0[d] for d in common}; a3 = {d: ar3[d] for d in common}
t0 = TurboSimulator(a0, common, prices, overheat_w=0.2); t0._use_overlay=True; t0._use_stored_growth=True
t3 = TurboSimulator(a3, common, prices, overheat_w=0.2); t3._use_overlay=True; t3._use_stored_growth=True
def cal(t, v, q, g, m, mm, sl, e, x):
    t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,mm,*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,x,sl,e,x,sl,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
print(f"[{common[0]}~{common[-1]} {len(common)}일] paired: {len(COMBOS)}w×{len(MOMS)}mom×{len(SLOTS)}slot = {len(COMBOS)*len(MOMS)*len(SLOTS)} config 동일끼리 annual vs TTM")
deltas=[]; by_v={v:[] for v in [10,15,20,25,30]}
for v,q,g,m in COMBOS:
    for mm in MOMS:
        for sl,e,x in SLOTS:
            a=cal(t0,v,q,g,m,mm,sl,e,x); tt=cal(t3,v,q,g,m,mm,sl,e,x)
            d=tt-a; deltas.append(d); by_v[v].append(d)
deltas=np.array(deltas)
print(f"\n=== paired Δ (TTM−annual), 동일 config {len(deltas)}개 ===")
print(f"  annual 승률(Δ<0): {(deltas<0).mean()*100:.1f}%  | TTM 승률(Δ>0): {(deltas>0).mean()*100:.1f}%")
print(f"  평균 Δ {deltas.mean():+.3f}  중앙 Δ {np.median(deltas):+.3f}  (음수=annual 우위)")
print(f"\n=== V별 평균 Δ (TTM−annual) — V 올릴수록 TTM 좋아지나? ===")
for v in [10,15,20,25,30]:
    arr=np.array(by_v[v])
    print(f"  V{v}: 평균Δ {arr.mean():+.3f}, annual승률 {(arr<0).mean()*100:.0f}% (n={len(arr)})")
# 밸류 IC
def value_ic(ar, fwd=20):
    di={d:i for i,d in enumerate(prices.index.strftime('%Y%m%d'))}; arr=prices.values; cols={c:i for i,c in enumerate(prices.columns)}
    ics=[]
    for d in common:
        if not reg.get(d,True) or d not in di: continue
        i0=di[d]; i1=i0+fwd
        if i1>=len(arr): continue
        vs,fr=[],[]
        for s in ar[d]:
            ci=cols.get(s['ticker'])
            if ci is None: continue
            p0,p1=arr[i0,ci],arr[i1,ci]
            if p0>0 and p1>0 and s.get('value_s') is not None: vs.append(s['value_s']); fr.append(p1/p0-1)
        if len(vs)>30:
            c=np.corrcoef(vs,fr)[0,1]
            if not np.isnan(c): ics.append(c)
    return np.mean(ics) if ics else float('nan')
print(f"\n=== 밸류팩터 IC (value_s vs fwd 20d, boost일) ===")
print(f"  annual-균등 {value_ic(a0):.4f}  vs  TTM-균등 {value_ic(a3):.4f}")
print(f"\n→ annual 승률 높고 평균Δ 음수면 config 무관 annual robust 우위. V올려도 Δ 음수면 'TTM에 V↑ 무익'.")
