# -*- coding: utf-8 -*-
"""재진입 쿨다운 확장스윕 — CAGR/노출(평균슬롯)/진입수 동반 확인 (착시 판별)."""
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

def run2(K):
    E, X, S = 3, 5, 3
    port = {}; prev = None; daily = []; occ = []; ntr = 0
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
        d1, d2 = dts[i - 1], dts[i - 2]
        if not reg.get(d0, True):
            port = {}; prev = d0; continue
        if reg.get(dts[i - 1], True) != reg.get(d0, True):
            port = {}
        a0, a1, a2 = CR[d0], CR[d1], CR[d2]
        wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
        for t in list(port.keys()):
            if wr(t) > X:
                port.pop(t); last_exit[t] = i
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
            if len(port) >= S: break
            if t in port or wr(t) > E: continue
            if t in last_exit and i - last_exit[t] <= K: continue
            port[t] = 1; ntr += 1
        if reg.get(d0, True): occ.append(len(port))
        prev = d0
    a = np.array([r for _, r in daily])
    eq = np.cumprod(1 + a); pk = np.maximum.accumulate(eq)
    mdd = ((eq - pk) / pk).min() * 100
    cagr = (eq[-1] ** (252 / len(a)) - 1) * 100
    # 연도별 수익
    yr = {}
    for (dd, r0) in daily:
        yr.setdefault(dd[:4], []).append(r0)
    yret = {y: (np.prod([1 + x for x in v]) - 1) * 100 for y, v in yr.items()}
    return cagr, mdd, cagr / abs(mdd), np.mean(occ), ntr, yret

print(f"{'K':6s}{'CAGR':>8s}{'MDD':>7s}{'Cal':>7s}{'평균슬롯':>9s}{'진입수':>7s}")
base_y = None
for K in [0, 10, 20, 30, 45, 60, 90]:
    c, m, cal, o, n, yret = run2(K)
    if K == 0: base_y = yret
    print(f"K={K:<4d}{c:>8.1f}{m:>7.1f}{cal:>7.2f}{o:>9.2f}{n:>7d}")
print("\n[연도별 수익률 K=0 vs K=10 vs K=30]")
_, _, _, _, _, y10 = run2(10)
_, _, _, _, _, y30 = run2(30)
for y in sorted(base_y):
    print(f"  {y}: K0 {base_y[y]:+8.1f}%  K10 {y10[y]:+8.1f}%  K30 {y30[y]:+8.1f}%")
