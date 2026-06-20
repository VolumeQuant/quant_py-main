# -*- coding: utf-8 -*-
"""섹터 브레드스 50% 스케일 (US 최종추천: 저정밀신호=binary금지→스케일) — 2026-06-20.
US: 확실한 게이트(MA)=전량방어, 애매한 브레드스=절반만 방어(50% 노출). KR은 집중도 더 심해 더더욱 필수.
binary vs 50%스케일 vs baseline 비교 + 협소장(24-26) 비용 + leave-one-bear-out(2022 빼고)."""
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
# 섹터 브레드스 → 3일확인 regime
ret = prices.pct_change(fill_method=None)
idx = {}
for s, g in sec.groupby('sector')['ticker']:
    cols = [t for t in g if t in ret.columns]
    if len(cols) >= 5: idx[s] = (1 + ret[cols].mean(axis=1).fillna(0)).cumprod()
sdf = pd.DataFrame(idx); ma = sdf.rolling(200, min_periods=150).mean()
valid = sdf.notna() & ma.notna()
breadth = ((sdf > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
bser = breadth.reindex(dts).values
def breadth_def_array(thresh=0.35, cf=3):
    """True=브레드스 방어(축소). 3일확인 상태머신."""
    out = np.zeros(len(days), bool); md = True; stk = 0; ss = None
    for i in range(len(days)):
        v = bser[i]
        s = (v > thresh) if v == v else ss
        if s is None: out[i] = (not md); continue
        stk = stk + 1 if s == ss else 1; ss = s
        if stk >= cf and md != s: md = s
        out[i] = (not md)  # md=False(브레드스<thresh 확정)=방어
    return out
# MA regime
s_ = kc.rolling(20).mean(); l_ = kc.rolling(80).mean()
regA = np.zeros(len(days), bool); md = True; stk = 0; ss = None
for i, d in enumerate(days):
    ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
    if pd.isna(sv) or pd.isna(lv): regA[i] = md; continue
    s = bool(sv > lv); stk = stk+1 if s == ss else 1; ss = s
    if stk >= 5 and md != s: md = s
    regA[i] = md
# 기본 포트폴리오 일별수익 (MA게이트, 풀)
t = TurboSimulator(ar, days, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
for d in days:
    tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
    t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
flat = list(t._cached_flat); parr = t._price_arr; drows = t._date_row_indices
def base_rets():
    port = {}; prev = None; rets = np.zeros(len(days))
    for i in range(2, len(days)):
        cur = regA[i]
        if prev is not None and cur != prev: port = {}
        prev = cur
        if flat[i] is None or not cur:
            if i+1 < len(days) and port:
                cr = drows[i]; nr = drows[i+1]
                rr = [parr[nr,c]/parr[cr,c]-1 for c in port if parr[cr,c]==parr[cr,c] and parr[nr,c]==parr[nr,c] and parr[cr,c]>0]
                rets[i+1] = np.mean(rr) if rr else 0
            continue
        wr, cc, cp, cw = flat[i]
        for c in list(port):
            if wr[c] > 6: del port[c]
        slots = 3 - len(port)
        for k in range(len(cc)):
            if slots <= 0: break
            if cw[k] <= 3 and cc[k] not in port: port[cc[k]] = cp[k]; slots -= 1
        if i+1 < len(days) and port:
            cr = drows[i]; nr = drows[i+1]
            rr = [parr[nr,c]/parr[cr,c]-1 for c in port if parr[cr,c]==parr[cr,c] and parr[nr,c]==parr[nr,c] and parr[cr,c]>0]
            rets[i+1] = np.mean(rr) if rr else 0
    return rets
rets = base_rets()
cash_d = 0.03/252
def metrics(r, lo=None, hi=None):
    if lo is not None:
        m = np.array([(lo <= days[i] <= hi) for i in range(len(days))])
        r = r[m]
    eq = np.cumprod(1+r); yrs = len(r)/252
    cagr = eq[-1]**(1/yrs)-1; mdd = (eq/np.maximum.accumulate(eq)-1).min()
    return cagr/abs(mdd) if mdd < 0 else 0, cagr*100, mdd*100
bdef = breadth_def_array()
# 변형별 일별수익
def variant(scale):
    r = rets.copy()
    for i in range(len(days)):
        if regA[i] and bdef[i]:  # MA boost인데 브레드스 방어
            r[i] = scale*rets[i] + (1-scale)*cash_d  # scale=0이면 전량현금(binary), 0.5=절반
    return r
print(f"브레드스 방어발동 일수: {bdef.sum()} / {len(days)} ({bdef.sum()/len(days)*100:.0f}%)")
print(f"\n{'변형':<22}{'Calmar':>8}{'MDD':>8}{'CAGR':>8}  {'약세22-23 MDD':>13}{'협소24-26 MDD':>14}")
print("-"*78)
for nm, sc in [('baseline(무)', None), ('binary 전량방어', 0.0), ('★50% 스케일', 0.5), ('70% 스케일', 0.7)]:
    r = rets if sc is None else variant(sc)
    c = metrics(r); bb = metrics(r, '20220101', '20231231'); nn = metrics(r, '20240101', '20261231')
    print(f"{nm:<22}{c[0]:>8.3f}{c[2]:>7.1f}%{c[1]:>7.0f}%  {bb[2]:>12.1f}%{nn[2]:>13.1f}%")
# leave-one-bear-out: 2022-2023 제거하고 50% vs baseline
print("\n=== leave-one-bear-out (2022-23 약세 제거, 닷컴류 한 이벤트 의존 점검) ===")
mask = np.array([not ('20220101' <= days[i] <= '20231231') for i in range(len(days))])
for nm, sc in [('baseline', None), ('50% 스케일', 0.5)]:
    r = (rets if sc is None else variant(sc))[mask]
    eq = np.cumprod(1+r); yrs = len(r)/252; cagr = eq[-1]**(1/yrs)-1; mdd = (eq/np.maximum.accumulate(eq)-1).min()
    print(f"  {nm:<12} Calmar {cagr/abs(mdd):.3f} MDD {mdd*100:.1f}%")
print("\n[판정] 50%가 binary보다 협소장(24-26) 덜 다치고 약세 방어 유지 + bear제거후도 우위면 US결론 KR재현.")
