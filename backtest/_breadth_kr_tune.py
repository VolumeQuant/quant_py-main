# -*- coding: utf-8 -*-
"""KR 섹터브레드스 임계/확인일 정밀 튜닝 (2026-06-20, US 지적: KR 미검증·과발동 위험).
50%스케일 고정. 임계×확인일 스윕 → Calmar/MDD/약세/협소 + ★발동빈도 + leave-one-bear-out.
목표: 과발동(헛방어) 적으면서 약세방어 유지하는 KR고유 임계 찾기. 거래일 정합(주말 제거)."""
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
# 섹터지수 브레드스 (거래일 = state dates로 reindex = 주말제거)
ret = prices.pct_change(fill_method=None)
idx = {}
for s, g in sec.groupby('sector')['ticker']:
    cols = [t for t in g if t in ret.columns]
    if len(cols) >= 5: idx[s] = (1 + ret[cols].mean(axis=1).fillna(0)).cumprod()
sdf = pd.DataFrame(idx); ma = sdf.rolling(200, min_periods=150).mean()
valid = sdf.notna() & ma.notna()
bseries = (((sdf > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)).reindex(dts).values
# MA regime + base rets
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
def defarr(thr, cf):
    out = np.zeros(len(days), bool); md = True; stk = 0; ss = None
    for i in range(len(days)):
        v = bseries[i]; s = (v > thr) if v == v else ss
        if s is None: out[i] = (not md); continue
        stk = stk+1 if s == ss else 1; ss = s
        if stk >= cf and md != s: md = s
        out[i] = (not md)
    return out
def scaled(bdef, sc=0.5):
    r = rets.copy()
    for i in range(len(days)):
        if regA[i] and bdef[i]: r[i] = sc*rets[i]+(1-sc)*cash_d
    return r
def metr(r, mask=None):
    if mask is not None: r = r[mask]
    eq = np.cumprod(1+r); cagr = eq[-1]**(252/len(r))-1; mdd = (eq/np.maximum.accumulate(eq)-1).min()
    return cagr/abs(mdd), mdd*100
bearmask = np.array(['20220101' <= d <= '20231231' for d in days])
narrmask = np.array(['20240101' <= d <= '20261231' for d in days])
exbear = ~bearmask
cb, mb = metr(rets)
print(f"baseline(무): Calmar {cb:.3f} MDD {mb:.1f}%\n")
print(f"{'임계×확인':<12}{'Cal':>7}{'MDD':>7}{'약세MDD':>8}{'협소MDD':>8}{'발동%':>7}{'ex-bear Cal':>11}")
print("-"*62)
best = None
for thr in [0.25, 0.30, 0.35, 0.40, 0.45]:
    for cf in [2, 3, 5]:
        bdef = defarr(thr, cf); r = scaled(bdef)
        c, m = metr(r); _, bm = metr(r, bearmask); _, nm = metr(r, narrmask); ce, _ = metr(r, exbear)
        freq = bdef.sum()/len(days)*100
        tag = ""
        if best is None or (c > best[0] and freq < 40): best = (c, thr, cf, m, freq, ce)
        print(f"<{int(thr*100)}%/{cf}일      {c:>6.3f}{m:>6.1f}%{bm:>7.1f}%{nm:>7.1f}%{freq:>6.0f}%{ce:>10.3f}")
print(f"\n현재배포 <35%/3일 발동빈도 {defarr(0.35,3).sum()/len(days)*100:.0f}% (US지적: KR 상시협소라 과발동 위험 점검)")
print(f"★후보(Cal최고·발동<40%·ex-bear robust): <{int(best[1]*100)}%/{best[2]}일 Cal {best[0]:.3f} MDD {best[3]:.1f}% 발동 {best[4]:.0f}% ex-bear {best[5]:.3f}")
print("판정: 발동빈도 낮으면서 Cal·약세MDD·ex-bear 다 좋은 임계 = KR고유 최적. 현행 35%/3일과 비교.")
