# -*- coding: utf-8 -*-
"""staging(_do_boost) down-only state 검증: 저장 recent_ca로 페널티 재현 → Calmar ~4.05 기대.
+ 6/17 top8 + recent_ca 발동 종목 확인."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.abspath(__file__)); DC = os.path.join(PROJ, 'data_cache')
SD = sys.argv[1] if len(sys.argv) > 1 else '_do_boost'
prices = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
kc = pd.read_parquet(os.path.join(DC, 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
ar, days = {}, []
for f in sorted(glob.glob(os.path.join(PROJ, SD, 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days); reg = calc_reg(days)
print(f"[{SD}] {len(days)}일 ({days[0]}~{days[-1]})")
t = TurboSimulator(ar, days, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
for d in days:
    tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
    t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)
                                  +0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
t._cached_key = None
t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
flat = list(t._cached_flat)
r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, days, t._price_arr, t._bench_arr, t._has_bench,
                      t._date_row_indices, len(days), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
print(f"down-only Calmar {r.get('calmar',0):.3f} CAGR {r.get('cagr',0)*100:.0f}% MDD {r.get('mdd',0)*100:.1f}% (기대 ~4.05)")
nrc = sum(1 for d in days for x in ar[d] if x.get('recent_ca'))
print(f"recent_ca 저장 종목-일: {nrc}")
# 최신일 top8
last = days[-1]; d8 = sorted(ar[last], key=lambda x: (x.get('weighted_rank', x['rank']), x.get('composite_rank', x['rank'])))[:8]
print(f"\n{last} boost top8 (wr):")
for i, x in enumerate(d8, 1):
    print(f"  {i} {x['name']:<14} wr{round(x.get('weighted_rank',0),2)} cr{x.get('composite_rank')}" + ("  [CA감점]" if x.get('recent_ca') else ""))
