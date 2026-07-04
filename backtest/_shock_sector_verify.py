# -*- coding: utf-8 -*-
"""쇼크브레이크 과적합 검증 + 섹터쏠림 제대로 재측정.
1) 쇼크(-8%) 발동일 전수 나열 + 에피소드별 기여 + leave-2026-out
2) ksic_to_sector 매핑으로 섹터쏠림(3/3, 2/3) 빈도 + 스케일 BT
3) 급락일 KOSPI 비교(시장 vs 리더 급락 구분)"""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = 'C:/dev/claude-code/quant_py-main'
sys.path.insert(0, R); sys.path.insert(0, R + '/backtest')
from fast_generate_rankings_v2 import ksic_to_sector

px = pd.read_parquet(R + '/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)
pcol = {c: i for i, c in enumerate(px.columns)}
parr = px.values
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
kc = pd.read_parquet(R + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
kret = kc.pct_change()

CR = {}; dts = []
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    r = json.load(open(f, encoding='utf-8'))['rankings']
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in r}
    dts.append(dt)
dts = sorted(dts)

from breadth_diagnostic import breadth_scale_by_date as _bsbd
BRD = _bsbd(list(dts))

reg = {}; md = True; stk = 0; ss = None
for dd in dts:
    ts = pd.Timestamp(dd[:4] + '-' + dd[4:6] + '-' + dd[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)):
        reg[dd] = md; continue
    s = bool(ma20[ts] > ma80[ts]); stk = stk + 1 if s == ss else 1; ss = s
    if stk >= 5 and md != s: md = s
    reg[dd] = md

def pxv(t, d):
    return parr[tdi[d], pcol[t]] if (t in pcol and d in tdi) else None

sm = pd.read_parquet(R + '/data_cache/ksic_sector_map.parquet')
SEC = {str(t).zfill(6): ksic_to_sector(str(c)) or 'NA' for t, c in zip(sm['ticker'], sm['induty_code'])}
print("매핑 예:", [(t, SEC[t]) for t in ['000660', '006910', '089970'] if t in SEC])

# 리플레이
E, X, S = 3, 5, 3
port = set(); prev = None; rows = []
for i, d0 in enumerate(dts):
    avg = 0.0
    if port and prev:
        rr = [pxv(t, d0) / pxv(t, prev) - 1 for t in port
              if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
        avg = np.mean(rr) if rr else 0.0
    rows.append([d0, avg, BRD.get(d0, 1.0), tuple(sorted(port)), reg.get(d0, True)])
    if i < 2:
        prev = d0; continue
    d1, d2 = dts[i - 1], dts[i - 2]
    if not reg.get(d0, True):
        port = set(); prev = d0; continue
    if reg.get(dts[i - 1], True) != reg.get(d0, True):
        port.clear()
    a0, a1, a2 = CR[d0], CR[d1], CR[d2]
    wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
    port = {t for t in port if wr(t) <= X}
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
        if len(port) >= S: break
        if wr(t) <= E: port.add(t)
    prev = d0

D = pd.DataFrame(rows, columns=['d', 'raw', 'brd', 'hold', 'boost'])
pr = (D['raw'] * D['brd']).values
dates = D['d'].values

def perf(rets, sub=None):
    a = np.asarray(rets, dtype=float)
    if sub is not None:
        mask = (dates >= sub[0]) & (dates <= sub[1]); a = a[mask]
    if len(a) < 20: return 0, 0, 0
    eq = np.cumprod(1 + a); peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min() * 100
    cagr = (eq[-1] ** (252 / len(a)) - 1) * 100
    return cagr, mdd, (cagr / abs(mdd) if mdd < 0 else 0)

P1 = ('20190102', '20211231'); P2 = ('20220101', '20231231'); P3 = ('20240101', '20261231')
def report(name, rets):
    c, m, cal = perf(rets)
    _, _, a = perf(rets, P1); _, _, b = perf(rets, P2); _, _, cc = perf(rets, P3)
    print(f"  {name:36s} Cal {cal:5.2f}  강세 {a:5.2f}  약세 {b:5.2f}  최근 {cc:5.2f}  MDD {m:6.1f}  CAGR {c:6.1f}")

# ===== 1) 쇼크 발동일 전수 =====
print("\n===== 1) 쇼크브레이크 발동일 전수 (전일 포트수익<-8%) =====")
trig = [(dates[i], pr[i - 1] * 100, pr[i] * 100) for i in range(1, len(D)) if pr[i - 1] < -0.08]
print(f"  발동 {len(trig)}회")
for d, y, t in trig:
    k = kret.get(pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:]), np.nan)
    print(f"    {d}: 전일 {y:6.2f}% → 당일(스케일전) {t:6.2f}%  KOSPI당일 {k*100 if k==k else float('nan'):5.2f}%")

# 에피소드 기여: 발동 다음날 수익 절약분(당일 ret×0.5 회피)
print("\n  [발동시 절약/손실 (당일수익×0.5 = 회피분, 음수면 이득)]")
saved = [(d, -t * 0.5) for d, y, t in trig]
for d, s in saved:
    print(f"    {d}: 노출50%로 회피한 수익 {-s:+.2f}%p")

# leave-2026-out
print("\n  [기간 분해 — 2026 제외시 쇼크브레이크 효과]")
for N in [1, 3]:
    scale = np.ones(len(D)); cool = 0
    for i in range(1, len(D)):
        if pr[i - 1] < -0.08: cool = N
        if cool > 0: scale[i] = 0.5; cool -= 1
    r2 = D['raw'].values * D['brd'].values * scale
    _, _, cal_ex = perf(r2, ('20190102', '20251231'))
    _, _, base_ex = perf(pr, ('20190102', '20251231'))
    print(f"    N={N}: 2019~2025만 base {base_ex:.2f} vs shock {cal_ex:.2f} (Δ{cal_ex-base_ex:+.2f})")

# ===== 2) 섹터쏠림 (제대로 매핑) =====
print("\n===== 2) 섹터쏠림 빈도 (ksic_to_sector 매핑) =====")
def conc(h):
    if len(h) < 3: return 0
    secs = [SEC.get(t, 'NA') for t in h]
    from collections import Counter
    return Counter(secs).most_common(1)[0][1]
D['conc'] = D['hold'].apply(conc)
full = D[D['hold'].apply(len) == 3]
print(f"  3슬롯일 {len(full)}일 중: 3/3 동일 {int((full['conc']==3).sum())}일({(full['conc']==3).mean()*100:.0f}%), 2/3 동일 {int((full['conc']==2).sum())}일({(full['conc']==2).mean()*100:.0f}%)")
sig3 = (D['conc'] == 3).shift(1).fillna(False).values.astype(bool)
sig2 = (D['conc'] >= 2).shift(1).fillna(False).values.astype(bool)
print()
report('baseline', pr)
for sig, lbl in [(sig3, '3/3동일섹터'), (sig2, '2/3+동일섹터')]:
    for sc in [0.75, 0.5]:
        scale = np.where(sig, sc, 1.0)
        report(f'{lbl}→×{sc}', D['raw'].values * D['brd'].values * scale)

# 쏠림일 vs 비쏠림일 수익 특성
print("\n  [3/3 쏠림일 다음날 수익 특성]")
nx = pd.Series(pr).shift(-1)
m3 = (D['conc'] == 3).values
m_other = (D['conc'] < 3).values & (D['hold'].apply(len) == 3).values
print(f"    쏠림일 다음날: 평균 {nx[m3].mean()*100:+.3f}% std {nx[m3].std()*100:.2f}% (n={m3.sum()})")
print(f"    비쏠림 3슬롯일 다음날: 평균 {nx[m_other].mean()*100:+.3f}% std {nx[m_other].std()*100:.2f}% (n={m_other.sum()})")
