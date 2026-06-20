# -*- coding: utf-8 -*-
"""복귀일 2022 과적합 검증 (2026-06-20, 사용자/US 지적): 복귀=단일약세 반등모양에 최민감 파라미터.
①복귀 전환(defense→100%) 몇번·언제 ②3일 우위가 블록별 일관인가 vs 2022에만 몰렸나.
NE=3 고정, 복귀 NX={3,5,10,15} × 블록(19-21코로나/22-23약세/24-26협소)."""
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
days = sorted(days); dts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])
ret = prices.pct_change(fill_method=None)
idx = {}
for s, g in sec.groupby('sector')['ticker']:
    cols = [t for t in g if t in ret.columns]
    if len(cols) >= 5: idx[s] = (1 + ret[cols].mean(axis=1).fillna(0)).cumprod()
sdf = pd.DataFrame(idx); ma = sdf.rolling(200, min_periods=150).mean()
valid = sdf.notna() & ma.notna()
bseries = (((sdf > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)).reindex(dts).values
s_ = kc.rolling(20).mean(); l_ = kc.rolling(80).mean()
regA = np.zeros(len(days), bool); md = True; stk = 0; ss = None
for i, d in enumerate(days):
    ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
    if pd.isna(sv) or pd.isna(lv): regA[i] = md; continue
    sb = bool(sv > lv); stk = stk+1 if sb == ss else 1; ss = sb
    if stk >= 5 and md != sb: md = sb
    regA[i] = md
t = TurboSimulator(ar, days, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
for d in days:
    tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
    t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
flat = list(t._cached_flat); parr = t._price_arr; drows = t._date_row_indices
def base_rets():
    port = {}; prev = None; r = np.zeros(len(days))
    for i in range(2, len(days)):
        cur = regA[i]
        if prev is not None and cur != prev: port = {}
        prev = cur
        if flat[i] is None or not cur:
            if i+1 < len(days) and port:
                cr = drows[i]; nr = drows[i+1]; rr = [parr[nr,c]/parr[cr,c]-1 for c in port if parr[cr,c]==parr[cr,c] and parr[nr,c]==parr[nr,c] and parr[cr,c]>0]; r[i+1] = np.mean(rr) if rr else 0
            continue
        wr, cc, cp, cw = flat[i]
        for c in list(port):
            if wr[c] > 6: del port[c]
        slots = 3-len(port)
        for k in range(len(cc)):
            if slots <= 0: break
            if cw[k] <= 3 and cc[k] not in port: port[cc[k]] = cp[k]; slots -= 1
        if i+1 < len(days) and port:
            cr = drows[i]; nr = drows[i+1]; rr = [parr[nr,c]/parr[cr,c]-1 for c in port if parr[cr,c]==parr[cr,c] and parr[nr,c]==parr[nr,c] and parr[cr,c]>0]; r[i+1] = np.mean(rr) if rr else 0
    return r
rets = base_rets(); cash_d = 0.03/252
def defarr_asym(NE, NX):
    out = np.zeros(len(days), bool); md = True; below = 0; above = 0; fires = []; recovers = []
    for i in range(len(days)):
        v = bseries[i]
        if v != v: out[i] = (not md); continue
        if v < 0.35: below += 1; above = 0
        else: above += 1; below = 0
        if md and below >= NE: md = False; fires.append(days[i])
        elif (not md) and above >= NX: md = True; recovers.append(days[i])
        out[i] = (not md)
    return out, fires, recovers
def scaled(bdef):
    r = rets.copy()
    for i in range(len(days)):
        if regA[i] and bdef[i]: r[i] = 0.5*rets[i]+0.5*cash_d
    return r
def cal(r, lo, hi):
    m = np.array([lo <= days[i] <= hi for i in range(len(days))]); r = r[m]
    if len(r) < 30: return 0
    eq = np.cumprod(1+r); cg = eq[-1]**(252/len(r))-1; mdd = (eq/np.maximum.accumulate(eq)-1).min()
    return cg/abs(mdd) if mdd < 0 else 0

# ① 복귀 전환 횟수·시점
bd3, fires, recs = defarr_asym(3, 3)
print(f"=== 복귀(defense→100%) 전환: 총 {len(recs)}회 ===")
print("발동일:", fires)
print("복귀일:", recs)
# 연도별 복귀 카운트
from collections import Counter
print("연도별 복귀:", dict(Counter(r[:4] for r in recs)))

# ② 블록별 3 vs 15 (2022 집중인가)
blocks = [('19-21(코로나)', '20190102', '20211231'), ('22-23(약세)', '20220101', '20231231'),
          ('24-26(협소)', '20240101', '20261231')]
print(f"\n=== 블록별 복귀NX 비교 (Calmar) — 3일 우위가 2022집중인가 ===")
print(f"{'복귀NX':>7}" + "".join(f"{b[0]:>14}" for b in blocks) + f"{'전체':>9}")
for NX in [3, 5, 10, 15]:
    bdef, _, _ = defarr_asym(3, NX); r = scaled(bdef)
    full = cal(r, '20190102', '20260617')
    print(f"{NX:>7}" + "".join(f"{cal(r, b[1], b[2]):>14.3f}" for b in blocks) + f"{full:>9.3f}")
print("\n[판정] 3일이 모든 블록서 ≥이면 robust. 22-23만 우위·딴블록 열위면 2022과적합=낮은신뢰.")
