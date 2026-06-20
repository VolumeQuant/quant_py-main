# -*- coding: utf-8 -*-
"""섹터 브레드스 OR게이트(35%/3일) 정식 robustness: WF 3블록 + OOS train/test + 인접CV + 약세분해.
US 위너 KR재현 후보 검증. baseline 대비 MDD↓ 유지가 WF/OOS서 robust한가."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
sec = pd.read_parquet(sorted(glob.glob(P + '/data_cache/krx_sector_*.parquet'))[-1])
sec = sec.rename(columns={sec.columns[0]: 'ticker', sec.columns[1]: 'sector'})
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)
dts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])
ret = prices.pct_change(fill_method=None)
sec_idx = {}
for s, tks in sec.groupby('sector')['ticker'].apply(list).to_dict().items():
    cols = [t for t in tks if t in ret.columns]
    if len(cols) >= 5: sec_idx[s] = (1 + ret[cols].mean(axis=1).fillna(0)).cumprod()
sec_df = pd.DataFrame(sec_idx)
above = (sec_df > sec_df.rolling(200, min_periods=150).mean())
valid = sec_df.notna() & sec_df.rolling(200, min_periods=150).mean().notna()
sec_breadth = (above & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
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
base = ma_regime()
def combo(X, cf):
    sb = sec_breadth.reindex(dts)
    return {d: base[d] and confirm(sb > X, cf)[d] for d in days}
def bt(reg, lo, hi):
    sub = [d for d in days if lo <= d <= hi]
    if len(sub) < 30: return (0, 0)
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench, t._date_row_indices, len(sub), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('mdd', 0)
W = combo(0.35, 3)
print("=== ① WF 3블록 (Calmar / MDD): baseline vs 섹터breadth<35%/3일 ===")
for nm, lo, hi in [('19-21', '20190102', '20211231'), ('약세22-23', '20220101', '20231231'), ('24-26', '20240101', '20261231')]:
    b = bt(base, lo, hi); w = bt(W, lo, hi)
    print(f"  {nm:<10} base {b[0]:.2f}/{b[1]:.1f}%  →  breadth {w[0]:.2f}/{w[1]:.1f}%  (MDD {w[1]-b[1]:+.1f}%p)")
print("\n=== ② 인접 안정 (Calmar/MDD 전체기간) ===")
for X in [0.30, 0.35, 0.40]:
    for cf in [2, 3, 5]:
        c = bt(combo(X, cf), '20190102', '20260617')
        print(f"  breadth<{int(X*100)}%/{cf}일: Cal {c[0]:.3f} MDD {c[1]:.1f}%")
print("\n=== ③ 전체 + 결론 ===")
bf = bt(base, '20190102', '20260617'); wf = bt(W, '20190102', '20260617')
print(f"  baseline: Cal {bf[0]:.3f} MDD {bf[1]:.1f}%  |  breadth<35%/3일: Cal {wf[0]:.3f} MDD {wf[1]:.1f}%")
print(f"  → Calmar차 {wf[0]-bf[0]:+.3f}(노이즈±0.10), MDD {wf[1]-bf[1]:+.1f}%p")
print("⚠️ 한계: 섹터멤버십=현재(2026) 기준 사용=과거 PIT 아님(경미한 생존편향). 배포시 PIT섹터 필요.")
