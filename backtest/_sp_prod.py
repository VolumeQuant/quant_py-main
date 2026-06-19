# -*- coding: utf-8 -*-
"""3-way: production(state/) vs 1.6-annual(_sp0b) vs 균등-annual(_sp0c). 같은 harness·config(V15Q0G55M30 12m E3X6S3).
production≈_sp0b면 재생성 충실(Q1 +0.87 신뢰). 균등>production이면 1.6→균등이 실제 개선."""
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
        if dt.isdigit() and len(dt) == 8 and dt >= '20190102': ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
arP, dP = load('state'); ar0, d0 = load('_sp0b'); arC, dC = load('_sp0c')
common = sorted(set(dP) & set(d0) & set(dC)); reg = calc_reg(common)
# state/ overheat_pen 있나 체크
has_oh = 'overheat_pen' in arP[common[len(common)//2]][0]
print(f"[{common[0]}~{common[-1]} {len(common)}일] state overheat_pen 저장={has_oh}")
def cal(ar):
    t = TurboSimulator({d: ar[d] for d in common}, common, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
cP=cal(arP); c0=cal(ar0); cC=cal(arC)
print(f"\n=== 고정 운영config(V15Q0G55M30 12m E3X6S3), 같은 harness ===")
print(f"  production(state/, 실제배포)   : {cP:.3f}")
print(f"  1.6-annual (_sp0b 재생성)      : {c0:.3f}   (production과 차이 {c0-cP:+.3f} → 작으면 재생성 충실)")
print(f"  균등-annual (_sp0c)            : {cC:.3f}   (production 대비 {cC-cP:+.3f}, 1.6대비 {cC-c0:+.3f})")
print(f"\n→ production≈1.6면 재생성 충실. 균등>production이면 1.6→균등이 실제 개선폭.")
