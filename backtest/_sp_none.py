# -*- coding: utf-8 -*-
"""corpaction 효과 격리: production(state/) vs _sp0b(corp ON) vs _sp0b_none(corp OFF). 같은 config V15Q0G55M30 12m E3X6S3.
corp+penalty OFF가 _sp0b를 production(3.83) 쪽으로 올리면 → corpaction이 gap 원인."""
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
arP, dP = load('state'); ar0, d0 = load('_sp0b'); arN, dN = load('_sp0b_none')
common = sorted(set(dP) & set(d0) & set(dN)); reg = calc_reg(common)
print(f"[{common[0]}~{common[-1]} {len(common)}일]")
def cal(ar):
    t = TurboSimulator({d: ar[d] for d in common}, common, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
cP=cal(arP); c0=cal(ar0); cN=cal(arN)
print(f"\n=== 고정 config V15Q0G55M30 12m E3X6S3 (같은 harness) ===")
print(f"  production(state/)            : {cP:.3f}")
print(f"  _sp0b (corpaction ON, 1.6)    : {c0:.3f}")
print(f"  _sp0b_none (corp+penalty OFF, 1.6): {cN:.3f}")
print(f"\n  corpaction 효과 (OFF−ON): {cN-c0:+.3f}")
print(f"  OFF가 production에 얼마나 근접: {cN:.2f} vs {cP:.2f} (남은 gap {cP-cN:+.3f})")
print(f"\n→ cN이 cP(3.83)로 확 오르면 corpaction이 gap 주범. 여전히 낮으면 corpaction 아님(다음=페널티 OFF 테스트).")
