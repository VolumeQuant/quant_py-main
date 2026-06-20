# -*- coding: utf-8 -*-
"""섹터브레드스 비대칭 확인일 (US: 발동3일/복귀15일) KR 검증 (2026-06-20, 사용자 지적).
"들어갈 땐 빠르게, 나올 땐 신중하게" — 복귀 느리게=하루반등 휩쏘 방지. NE=3 고정, NX 스윕.
50%스케일. Calmar/MDD/약세/협소 + ★전환횟수(휩쏘) + 발동일수."""
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
def defarr_asym(thr, NE, NX):
    """비대칭: 발동 NE일(아래), 복귀 NX일(위). returns (defense_bool[], 전환횟수)."""
    out = np.zeros(len(days), bool); md = True; below = 0; above = 0; trans = 0
    for i in range(len(days)):
        v = bseries[i]
        if v != v:
            out[i] = (not md); continue
        if v < thr: below += 1; above = 0
        else: above += 1; below = 0
        if md and below >= NE: md = False; trans += 1       # 발동
        elif (not md) and above >= NX: md = True; trans += 1  # 복귀
        out[i] = (not md)
    return out, trans
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
print(f"baseline: Calmar {cb:.3f} MDD {mb:.1f}%  (THRESH 35% 고정, 발동확인 NE=3 고정)\n")
print(f"{'복귀NX':>6}{'Cal':>8}{'MDD':>7}{'약세MDD':>8}{'협소MDD':>8}{'전환수':>7}{'발동%':>7}{'ex-bear':>8}")
print("-"*60)
best = None
for NX in [3, 5, 10, 15, 20, 30]:
    bdef, tr = defarr_asym(0.35, 3, NX); r = scaled(bdef)
    c, m = metr(r); _, bm = metr(r, bearmask); _, nm = metr(r, narrmask); ce, _ = metr(r, exbear)
    freq = bdef.sum()/len(days)*100
    if best is None or c > best[0]: best = (c, NX, m, tr, freq, ce, bm)
    print(f"{NX:>6}{c:>8.3f}{m:>6.1f}%{bm:>7.1f}%{nm:>7.1f}%{tr:>6}{freq:>6.0f}%{ce:>7.3f}")
print(f"\n현행 대칭(3/3)=위 NX=3행. ★최적 복귀: NX={best[1]} Cal {best[0]:.3f} MDD {best[2]:.1f}% 전환 {best[3]} 발동 {best[4]:.0f}% ex-bear {best[5]:.3f} 약세 {best[6]:.1f}%")
print("판정: 복귀 느릴수록 전환↓(휩쏘↓). KR 최적 NX 채택. US는 15.")
