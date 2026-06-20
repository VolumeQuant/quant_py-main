# -*- coding: utf-8 -*-
"""섹터 내부 breadth 보강 (2026-06-20, 사용자가 바이오 착시 지적).
문제: 섹터'지수'가 200일선 위여도(바이오 +33%) 내부 종목은 8%만 건강 = 연초급등 잔상.
①진단: 섹터별 내부 breadth(구성종목 중 200일선 위 %) ②신호: 내부breadth 집계를 50%스케일 게이트로
백테스트해 배포한 섹터지수 신호(Cal 4.36)보다 나은지."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
sec = pd.read_parquet(sorted(glob.glob(P + '/data_cache/krx_sector_*.parquet'))[-1])
sec = sec.rename(columns={sec.columns[0]: 'ticker', sec.columns[1]: 'sector'})
ma200 = prices.rolling(200, min_periods=150).mean()
above = prices > ma200
valid = prices.notna() & ma200.notna()
# ① 진단: 섹터별 내부 breadth (오늘)
print("=== 섹터별 내부 breadth (구성종목 중 200일선 위 %) vs 섹터지수 ===")
ret = prices.pct_change(fill_method=None)
rows = []
for s, g in sec.groupby('sector')['ticker']:
    cols = [t for t in g if t in valid.columns]
    cols = [t for t in cols if valid[t].iloc[-1]]
    if len(cols) < 5: continue
    within = sum(1 for t in cols if above[t].iloc[-1]) / len(cols)
    sidx = (1 + ret[[t for t in g if t in ret.columns]].mean(axis=1).fillna(0)).cumprod()
    sgap = (sidx.iloc[-1] / sidx.rolling(200, min_periods=150).mean().iloc[-1] - 1) * 100
    rows.append((s, within * 100, sgap, len(cols)))
rows.sort(key=lambda x: -x[1])
print(f"{'섹터':<14}{'내부breadth':>10}{'섹터지수':>9}  진단")
print("-" * 52)
for s, w, sg, n in rows:
    flag = ""
    if sg > 5 and w < 30:
        flag = " ★착시(지수↑ 속병)"
    elif w >= 50:
        flag = " 🟢진짜건강"
    print(f"{s:<14}{w:>9.0f}%{sg:>+8.0f}%{flag}")
# 집계 비교
allv = valid.iloc[-1]; allhealthy = (above.iloc[-1] & allv).sum() / allv.sum()
sec_avg = np.mean([r[1] for r in rows]) / 100
print(f"\n집계: 전종목 내부 {allhealthy*100:.0f}% | 섹터평균 내부 {sec_avg*100:.0f}% | (섹터지수 breadth=35%)")

# ② 신호 백테스트: 섹터평균 내부breadth 50%스케일 vs 배포(섹터지수)
from turbo_simulator import TurboSimulator, _run_regime_inner
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days); dts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])
# 섹터평균 내부breadth 시계열
within_by_sector = {}
for s, g in sec.groupby('sector')['ticker']:
    cols = [t for t in g if t in above.columns]
    if len(cols) < 5: continue
    a = (above[cols] & valid[cols]).sum(axis=1); v = valid[cols].sum(axis=1).replace(0, np.nan)
    within_by_sector[s] = a / v
within_avg = pd.DataFrame(within_by_sector).mean(axis=1).reindex(dts).values
allstock_b = ((above & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)).reindex(dts).values
# MA regime + sim (재사용)
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
def rets_base():
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
rets = rets_base(); cash_d = 0.03/252
def defarr(series, thr, cf=3):
    out = np.zeros(len(days), bool); md = True; stk = 0; ss = None
    for i in range(len(days)):
        v = series[i]; s = (v > thr) if v == v else ss
        if s is None: out[i] = (not md); continue
        stk = stk+1 if s == ss else 1; ss = s
        if stk >= cf and md != s: md = s
        out[i] = (not md)
    return out
def metr(r, lo=None, hi=None):
    if lo: r = r[np.array([lo <= days[i] <= hi for i in range(len(days))])]
    eq = np.cumprod(1+r); cagr = eq[-1]**(252/len(r))-1; mdd = (eq/np.maximum.accumulate(eq)-1).min()
    return cagr/abs(mdd), mdd*100
def scaled(bdef, sc=0.5):
    r = rets.copy()
    for i in range(len(days)):
        if regA[i] and bdef[i]: r[i] = sc*rets[i]+(1-sc)*cash_d
    return r
print(f"\n=== 50%스케일 신호 비교 (baseline Cal {metr(rets)[0]:.2f}/MDD {metr(rets)[1]:.1f}%) ===")
for nm, series, thr in [('배포: 섹터지수<35%', None, None),
                        ('전종목 내부<25%', allstock_b, 0.25),
                        ('전종목 내부<30%', allstock_b, 0.30),
                        ('섹터평균내부<35%', within_avg, 0.35),
                        ('섹터평균내부<40%', within_avg, 0.40)]:
    if series is None:
        # 배포 섹터지수 신호 재계산
        idx2 = {}
        for s, g in sec.groupby('sector')['ticker']:
            cols = [tt for tt in g if tt in ret.columns]
            if len(cols) >= 5: idx2[s] = (1+ret[cols].mean(axis=1).fillna(0)).cumprod()
        sdf = pd.DataFrame(idx2); ma = sdf.rolling(200, min_periods=150).mean()
        vv = sdf.notna() & ma.notna(); sb_ = ((sdf > ma)&vv).sum(axis=1)/vv.sum(axis=1).replace(0, np.nan)
        bdef = defarr(sb_.reindex(dts).values, 0.35)
    else:
        bdef = defarr(series, thr)
    r = scaled(bdef); c = metr(r); bb = metr(r, '20220101', '20231231'); nn = metr(r, '20240101', '20261231')
    print(f"  {nm:<18} Cal {c[0]:.3f} MDD {c[1]:.1f}% | 약세 {bb[1]:.1f}% 협소 {nn[1]:.1f}% | 발동 {bdef.sum()}일")
