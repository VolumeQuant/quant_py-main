# -*- coding: utf-8 -*-
"""주범 격리: 같은 config V15Q0G55M30 12m E3X6S3, 같은 harness(overlay+stored_growth, ba prices).
_sp0b(전부ON,1.74) / _sp0b_none(전부OFF,4.14) 사이에서 한 놈씩만 OFF한 3개를 끼워 측정.
  _sp0b_co: corpaction만 OFF  → (_sp0b_co - _sp0b) = corpaction이 죽인 양
  _sp0b_oo: oneoff만 OFF       → oneoff가 죽인 양
  _sp0b_vo: vtrap만 OFF        → vtrap이 죽인 양
세 상승폭 합이 ~(_sp0b_none - _sp0b)면 가법적. 한 놈이 압도하면 그놈이 주범."""
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
FOLDERS = {'production(state/)':'state', '_sp0b 전부ON':'_sp0b', '_sp0b_none 전부OFF':'_sp0b_none',
           'corpaction만OFF':'_sp0b_co', 'oneoff만OFF':'_sp0b_oo', 'vtrap만OFF':'_sp0b_vo'}
loaded = {}
for lbl, fld in FOLDERS.items():
    if os.path.isdir(os.path.join(PROJ, fld)):
        ar, d = load(fld); loaded[lbl] = (ar, d)
    else:
        print(f"[skip] {lbl} ({fld}) 폴더 없음")
common = sorted(set.intersection(*[set(d) for _, d in loaded.values()]))
reg = calc_reg(common)
print(f"[{common[0]}~{common[-1]} {len(common)}일]")
def cal(ar):
    t = TurboSimulator({d: ar[d] for d in common}, common, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r = _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0), r.get('cagr',0), r.get('mdd',0)
res = {}
print(f"\n=== 고정 config V15Q0G55M30 12m E3X6S3 (같은 harness) ===")
print(f"{'변형':<22}{'Calmar':>9}{'CAGR':>9}{'MDD':>9}")
for lbl, (ar, d) in loaded.items():
    c, cg, md = cal(ar); res[lbl] = c
    print(f"{lbl:<22}{c:>9.3f}{cg*100:>8.1f}%{md*100:>8.1f}%")
base = res.get('_sp0b 전부ON'); none = res.get('_sp0b_none 전부OFF')
print(f"\n=== 한 놈씩 OFF한 상승폭 (vs _sp0b 전부ON={base:.3f}) ===")
for lbl in ['corpaction만OFF','oneoff만OFF','vtrap만OFF']:
    if lbl in res: print(f"  {lbl:<18}: {res[lbl]:.3f}  (상승 {res[lbl]-base:+.3f})")
if none is not None:
    s = sum(res[l]-base for l in ['corpaction만OFF','oneoff만OFF','vtrap만OFF'] if l in res)
    print(f"\n  단일OFF 상승폭 합 {s:+.3f}  vs  전부OFF 총상승 {none-base:+.3f}  (합≈총이면 가법적, 차이=상호작용)")
print("\n→ 상승폭 가장 큰 놈 = 7.4년 production-gap 주범.")
