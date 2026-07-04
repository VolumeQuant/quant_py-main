# -*- coding: utf-8 -*-
"""재진입 쿨다운 최종 관문: 2-fold WF + 인접CV + 라이브 영향 표본."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = 'C:/dev/claude-code/quant_py-main'
px = pd.read_parquet(R + '/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)
pcol = {c: i for i, c in enumerate(px.columns)}
parr = px.values
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
kc = pd.read_parquet(R + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
CR = {}; dts = []
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    r = json.load(open(f, encoding='utf-8'))['rankings']
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in r}
    dts.append(dt)
dts = sorted(dts)
sys.path.insert(0, R)
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

def daily_series(K):
    E, X, S = 3, 5, 3
    port = {}; prev = None; daily = []
    last_exit = {}
    for i, d0 in enumerate(dts):
        avg = 0.0
        if port and prev:
            rr = [pxv(t, d0) / pxv(t, prev) - 1 for t in port
                  if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
            avg = np.mean(rr) if rr else 0.0
        daily.append((d0, avg * BRD.get(d0, 1.0)))
        if i < 2:
            prev = d0; continue
        if not reg.get(d0, True):
            port = {}; prev = d0; continue
        if reg.get(dts[i - 1], True) != reg.get(d0, True):
            port = {}
        a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
        wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
        for t in list(port.keys()):
            if wr(t) > X:
                port.pop(t); last_exit[t] = i
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
            if len(port) >= S: break
            if t in port or wr(t) > E: continue
            if t in last_exit and i - last_exit[t] <= K: continue
            port[t] = 1
        prev = d0
    return daily

def cal_of(daily, lo, hi):
    a = np.array([r for dd, r in daily if lo <= dd <= hi])
    if len(a) < 20: return 0
    eq = np.cumprod(1 + a); pk = np.maximum.accumulate(eq)
    mdd = ((eq - pk) / pk).min() * 100
    cagr = (eq[-1] ** (252 / len(a)) - 1) * 100
    return cagr / abs(mdd) if mdd < 0 else 0

KS = [0, 3, 5, 8, 10, 13, 15, 20, 30]
series = {K: daily_series(K) for K in KS}
A = ('20190102', '20221231'); B = ('20230101', '20261231')
print("[2-fold WF]")
print(f"  {'K':6s}{'foldA(19-22)':>14s}{'foldB(23-26)':>14s}")
for K in KS:
    print(f"  K={K:<4d}{cal_of(series[K],*A):>14.2f}{cal_of(series[K],*B):>14.2f}")
bestA = max(KS, key=lambda K: cal_of(series[K], *A))
bestB = max(KS, key=lambda K: cal_of(series[K], *B))
print(f"  → foldA 승자 K={bestA} → foldB OOS {cal_of(series[bestA],*B):.2f} (K0 {cal_of(series[0],*B):.2f}, Δ{cal_of(series[bestA],*B)-cal_of(series[0],*B):+.2f})")
print(f"  → foldB 승자 K={bestB} → foldA OOS {cal_of(series[bestB],*A):.2f} (K0 {cal_of(series[0],*A):.2f}, Δ{cal_of(series[bestB],*A)-cal_of(series[0],*A):+.2f})")

import statistics as st
vals = [cal_of(series[K], '20190102', '20261231') for K in [8, 10, 13]]
print(f"\n[인접 CV K8/10/13 전체: {[round(v,2) for v in vals]}, CV={st.pstdev(vals)/st.mean(vals):.3f}]")

# 라이브 영향: 최근 60일 리플레이에서 K=10이 바꾼 날
print("\n[라이브 영향 — 최근 40거래일 K0 vs K10 보유 차이]")
d0s = [dd for dd, _ in series[0]][-40:]
def ports_of(K):
    E, X, S = 3, 5, 3
    port = {}; res = {}; last_exit = {}
    for i, d0 in enumerate(dts):
        if i < 2: continue
        if not reg.get(d0, True): port = {}; res[d0] = set(); continue
        if reg.get(dts[i - 1], True) != reg.get(d0, True): port = {}
        a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
        wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
        for t in list(port.keys()):
            if wr(t) > X: port.pop(t); last_exit[t] = i
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
            if len(port) >= S: break
            if t in port or wr(t) > E: continue
            if t in last_exit and i - last_exit[t] <= K: continue
            port[t] = 1
        res[d0] = set(port)
    return res
p0 = ports_of(0); p10 = ports_of(10)
ndiff = 0
for d in d0s:
    if p0.get(d) != p10.get(d):
        ndiff += 1
        print(f"    {d}: K0 {sorted(p0.get(d,[]))} vs K10 {sorted(p10.get(d,[]))}")
print(f"  차이일수: {ndiff}/40  (오늘 {d0s[-1]} K0 {sorted(p0.get(d0s[-1],[]))} / K10 {sorted(p10.get(d0s[-1],[]))})")
