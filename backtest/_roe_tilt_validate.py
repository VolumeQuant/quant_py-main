# -*- coding: utf-8 -*-
"""ROE 단독 신호 검증 — ①기간분해 IC ②매수권 코호트 ③사이징 BT(선택불변, 비중만).
사이징: 보유 3종목을 그날 ROE 순으로 w_hi/w_mid/w_lo 배분 (동일가중 대비)."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from scipy import stats as sps

R = 'C:/dev/claude-code/quant_py-main'
px = pd.read_parquet(R + '/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
parr = px.values
pcol = {c: i for i, c in enumerate(px.columns)}
kc = pd.read_parquet(R + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()

CR = {}; ROE = {}; dts = []
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    d = json.load(open(f, encoding='utf-8'))['rankings']
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in d}
    ROE[dt] = {x['ticker']: x.get('roe') for x in d}
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

# ===== ① 기간분해 IC (top20 內 ROE vs fwd60) =====
print("===== ① ROE IC 기간분해 (top20 內, fwd60) =====")
for lo, hi, nm in [('20190102', '20211231', '강세 19-21'), ('20220101', '20231231', '약세 22-23'),
                   ('20240101', '20261231', '최근 24-26')]:
    ics = []
    for dt in dts:
        if not (lo <= dt <= hi): continue
        i0 = tdi[dt]
        if i0 + 61 >= len(tdays): continue
        rows = []
        for t, cr in CR[dt].items():
            if cr > 20 or t not in pcol: continue
            r = ROE[dt].get(t)
            p0 = parr[i0, pcol[t]]; p60 = parr[i0 + 61, pcol[t]]
            if r is None or not (p0 == p0 and p0 > 0 and p60 == p60 and p60 > 0): continue
            rows.append((r, p60 / p0 - 1))
        if len(rows) >= 10:
            a = np.array(rows)
            ic = sps.spearmanr(a[:, 0], a[:, 1]).statistic
            if ic == ic: ics.append(ic)
    ics = np.array(ics)
    print(f"  {nm}: IC {ics.mean():+.4f} (일수 {len(ics)}, 양수비율 {(ics>0).mean()*100:.0f}%)")

# ===== ② 매수권(cr<=3) ROE 코호트 =====
print("\n===== ② 매수권 ROE 3분위 (fwd60, pool) =====")
rows = []
for dt in dts:
    i0 = tdi[dt]
    if i0 + 61 >= len(tdays): continue
    for t, cr in CR[dt].items():
        if cr > 3 or t not in pcol: continue
        r = ROE[dt].get(t)
        p0 = parr[i0, pcol[t]]; p60 = parr[i0 + 61, pcol[t]]
        if r is None or not (p0 == p0 and p0 > 0 and p60 == p60 and p60 > 0): continue
        rows.append({'d': dt, 'roe': r, 'f60': p60 / p0 - 1})
bz = pd.DataFrame(rows)
q = bz['roe'].quantile([1/3, 2/3]).values
for nm, g in [('ROE하위', bz[bz['roe'] <= q[0]]), ('중위', bz[(bz['roe'] > q[0]) & (bz['roe'] <= q[1])]), ('ROE상위', bz[bz['roe'] > q[1]])]:
    print(f"  {nm:8s}: n={len(g):5d} 경계 {g['roe'].min():.0f}~{g['roe'].max():.0f}%  fwd60 {g['f60'].mean()*100:+.2f}% / 중앙 {g['f60'].median()*100:+.2f}% / 승률 {(g['f60']>0).mean()*100:.0f}%")

# ===== ③ ROE 사이징 BT (선택 불변) =====
def sim(wts=None, sub=None):
    """wts: 보유 3종목 ROE 내림차순 가중 (None=동일). faithful E3X5S3 K10 브레드스."""
    port = {}; prev = None; daily = []; last_exit = {}
    for i, d0 in enumerate(dts):
        r_day = 0.0
        if port and prev:
            rr = {}
            for t in port:
                pp, cp = pxv(t, prev), pxv(t, d0)
                if pp and cp and pp > 0 and cp > 0:
                    rr[t] = cp / pp - 1
            if rr:
                if wts is None or len(rr) < 2:
                    r_day = np.mean(list(rr.values()))
                else:
                    # 전일 기준 ROE로 가중 (look-ahead 방지: prev일 ranking의 roe)
                    roes = {t: (ROE.get(prev, {}).get(t) if ROE.get(prev, {}).get(t) is not None else -999) for t in rr}
                    order = sorted(rr, key=lambda t: -roes[t])
                    w = wts[:len(order)]
                    w = [x / sum(w) for x in w]
                    r_day = sum(rr[t] * w[k] for k, t in enumerate(order))
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
print("\n===== ③ ROE 사이징 BT (선택·매매 불변, 보유 비중만) =====")
print(f"  {'가중':22s}{'전체Cal':>8s}{'MDD':>7s}{'CAGR':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}")
for wts, nm in [(None, '동일가중 (현행)'), ([45, 33, 22], 'ROE순 45/33/22'), ([50, 30, 20], 'ROE순 50/30/20'),
                ([40, 33, 27], 'ROE순 40/33/27'), ([22, 33, 45], '역방향 22/33/45 (대조)')]:
    c, m, cal = sim(wts)
    _, _, p1 = sim(wts, P1); _, _, p2 = sim(wts, P2); _, _, p3 = sim(wts, P3)
    print(f"  {nm:22s}{cal:>8.2f}{m:>7.1f}{c:>7.1f}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f}")
