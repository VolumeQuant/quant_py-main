# -*- coding: utf-8 -*-
"""ROE_z 점수 가산(선택 레벨) 주입 스윕 — score' = score + W×roe_z → cr 재산출 → faithful 리플레이.
주입방식 = 가격민감도 연구 검증법(재생성 없이 state 내 재랭킹, 오차 0.014 검증됨).
한계: state 저장 종목(상위 ~65-190) 내 재랭킹이라 하위권→상위권 진입 케이스는 못 봄(보수적 근사)."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = 'C:/dev/claude-code/quant_py-main'
px = pd.read_parquet(R + '/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
parr = px.values
pcol = {c: i for i, c in enumerate(px.columns)}
kc = pd.read_parquet(R + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()

RAW = {}; dts = []
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    d = json.load(open(f, encoding='utf-8'))['rankings']
    RAW[dt] = [(x['ticker'], x.get('score'), x.get('roe'), x.get('composite_rank', x.get('rank', 999))) for x in d]
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

def build_cr(W):
    """W=0이면 저장 cr 그대로(하니스 정합 확인용), W>0이면 score+W×roe_z 재랭킹."""
    out = {}
    for dt in dts:
        rows = RAW[dt]
        if W == 0:
            out[dt] = {t: cr for t, sc, r, cr in rows}
            continue
        roes = np.array([r if r is not None else np.nan for _, _, r, _ in rows], dtype=float)
        m = np.nanmean(roes); s = np.nanstd(roes)
        z = (roes - m) / s if s > 0 else roes * 0
        z = np.clip(np.where(np.isnan(z), 0.0, z), -3, 3)
        scores = np.array([sc if sc is not None else -99 for _, sc, _, _ in rows], dtype=float) + W * z
        order = np.argsort(-scores)
        cr_map = {}
        for rank, idx in enumerate(order, 1):
            cr_map[rows[idx][0]] = rank
        out[dt] = cr_map
    return out

def sim(CR, sub=None):
    port = {}; prev = None; daily = []; last_exit = {}
    for i, d0 in enumerate(dts):
        r_day = 0.0
        if port and prev:
            rr = [pxv(t, d0) / pxv(t, prev) - 1 for t in port
                  if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
            r_day = np.mean(rr) if rr else 0.0
        daily.append((d0, r_day * BRD.get(d0, 1.0)))
        if i < 2: prev = d0; continue
        if not reg.get(d0, True): port = {}; prev = d0; continue
        if reg.get(dts[i - 1], True) != reg.get(d0, True): port = {}
        a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
        wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
        for t in list(port.keys()):
            if wr(t) > 5: port.pop(t); last_exit[t] = i
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
            if len(port) >= 3: break
            if t in port or wr(t) > 3: continue
            if t in last_exit and i - last_exit[t] <= 10: continue
            port[t] = 1
        prev = d0
    a = np.array([r for dd, r in daily if (not sub or sub[0] <= dd <= sub[1])])
    if len(a) < 20: return 0, 0, 0
    eq = np.cumprod(1 + a); pk = np.maximum.accumulate(eq)
    mdd = ((eq - pk) / pk).min() * 100
    cagr = (eq[-1] ** (252 / len(a)) - 1) * 100
    return cagr, mdd, cagr / abs(mdd) if mdd < 0 else 0

P1 = ('20190102', '20211231'); P2 = ('20220101', '20231231'); P3 = ('20240101', '20261231')
print("[ROE_z 점수가산 주입 스윕 — score + W×roe_z, cr 재랭킹, E3X5S3 K10 브레드스]")
print(f"  {'W':10s}{'전체Cal':>8s}{'MDD':>7s}{'CAGR':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}")
# 하니스 정합: W=0 저장cr vs W→0 재랭킹 둘 다
CR0 = build_cr(0)
c, m, cal = sim(CR0); _, _, p1 = sim(CR0, P1); _, _, p2 = sim(CR0, P2); _, _, p3 = sim(CR0, P3)
print(f"  {'0 (저장cr)':10s}{cal:>8.2f}{m:>7.1f}{c:>7.1f}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f} ←baseline")
CRe = build_cr(1e-9)
c, m, cal = sim(CRe)
print(f"  {'0 (재랭킹)':10s}{cal:>8.2f}{m:>7.1f}{c:>7.1f}   (주입 하니스 오차 확인용)")
for W in [0.03, 0.05, 0.08, 0.12, 0.2]:
    CRw = build_cr(W)
    c, m, cal = sim(CRw); _, _, p1 = sim(CRw, P1); _, _, p2 = sim(CRw, P2); _, _, p3 = sim(CRw, P3)
    print(f"  {W:<10.2f}{cal:>8.2f}{m:>7.1f}{c:>7.1f}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f}")
