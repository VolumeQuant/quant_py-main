# -*- coding: utf-8 -*-
"""변동성/분산 계열 조기경보 게이트 (2026-06-20 자율). 리서치 후보:
RV term-structure(RV5/RV60), 하방반편차(downside dev), signed-jump(neg semivariance), 단면분산.
전부 게이트(MA AND not-stress)로 baseline 대비. vol타겟팅(사이징) 아닌 0/1 게이트 = 기각된 것과 다름."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)
dts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])
ret = np.log(kc / kc.shift(1))
# 신호들
rv5 = ret.rolling(5).std(); rv60 = ret.rolling(60).std()
ts_ratio = (rv5 / rv60).reindex(dts)                       # 높으면 단기변동성 급등(stress)
dd60 = ret.apply(lambda x: x).rolling(60).apply(lambda w: np.sqrt(np.mean(np.minimum(w, 0)**2)), raw=True)
dd_z = ((dd60 - dd60.rolling(252).mean()) / dd60.rolling(252).std()).reindex(dts)  # 하방변동성 z
neg = (ret**2 * (ret < 0)).rolling(20).sum(); pos = (ret**2 * (ret > 0)).rolling(20).sum()
sj = ((pos - neg) / (pos + neg)).reindex(dts)              # signed jump (음수=하락쏠림 stress)
# 단면분산 (하락쪽)
prc = prices.pct_change(fill_method=None)
negdisp = prc[prc < 0].std(axis=1)
nd_z = ((negdisp - negdisp.rolling(252).mean()) / negdisp.rolling(252).std()).reindex(dts)

def ma_regime():
    s_ = kc.rolling(20).mean(); l_ = kc.rolling(80).mean(); reg = {}; md = True; stk = 0; ss = None
    for d in days:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
        if pd.isna(sv) or pd.isna(lv): reg[d] = md; continue
        s = bool(sv > lv); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
def confirm(boolser, k):
    reg = {}; md = True; stk = 0; ss = None
    for i, d in enumerate(days):
        v = boolser.iloc[i]; s = (bool(v) if not pd.isna(v) else ss)
        if s is None: reg[d] = md; continue
        stk = stk+1 if s == ss else 1; ss = s
        if stk >= k and md != s: md = s
        reg[d] = md
    return reg
def bt(reg, lo='20190102', hi='20260617'):
    sub = [d for d in days if lo <= d <= hi]
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench, t._date_row_indices, len(sub), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0), sum(1 for d in sub if not reg[d])
base = ma_regime()
def show(nm, reg):
    c = bt(reg); bb = bt(reg, '20220101', '20231231')
    print(f"{nm:<44}{c[0]:>7.3f}{c[1]:>7.1f}%{c[2]:>7.1f}%{c[3]:>6}일  약세 {bb[0]:>5.2f}/{bb[2]:.1f}%")
print(f"현재값: TS(rv5/rv60) {ts_ratio.iloc[-1]:.2f} | dd_z {dd_z.iloc[-1]:+.2f} | SJ {sj.iloc[-1]:+.2f} | negdisp_z {nd_z.iloc[-1]:+.2f}")
print(f"\n{'전략':<44}{'Calmar':>7}{'CAGR':>8}{'MDD':>7}{'현금':>6}  약세 Cal/MDD\n"+"-"*94)
show("baseline MA20/80/5", base)
print("--- not-stress AND MA (조기방어) ---")
for X in [1.3, 1.5, 1.8]:
    show(f"MA & RV5/RV60<{X}", {d: base[d] and not confirm(ts_ratio > X, 3)[d] for d in days})
for X in [1.0, 1.5]:
    show(f"MA & dd_z<{X}", {d: base[d] and not confirm(dd_z > X, 5)[d] for d in days})
for X in [-0.3, -0.5]:
    show(f"MA & SJ>{X}", {d: base[d] and not confirm(sj < X, 5)[d] for d in days})
for X in [1.5, 2.0]:
    show(f"MA & negdisp_z<{X}", {d: base[d] and not confirm(nd_z > X, 5)[d] for d in days})
print("\n[판정] baseline MDD 25.9%/Cal 4.05 대비 MDD↓&Cal>3.9면 후속.")
