# -*- coding: utf-8 -*-
"""G 서브팩터 심층 검증 — 핵심팩터(G 0.55)의 내부 구성 재점검.
①6개 서브 IC(top65/top20, 기간분해) ②서브 간 상관(중복도)
③현행 3서브(0.4/0.4/0.2) 재가중 주입 스윕 ④미사용 3서브 가산 주입 스윕
주입: growth_s' = growth_s×(G'/G_raw) — 페널티 배수 보존, score' = score+0.55×Δ.
⚠️스크리닝용 근사(저장종목 內 재랭킹) — 채택하려면 FG 풀재생성+전관문 필수."""
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

SUBS = ['rev_z', 'oca_z', 'rev_accel_z', 'gp_growth_z', 'op_margin_z', 'cfo_growth_z']
RAW = {}; dts = []
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    d = json.load(open(f, encoding='utf-8'))['rankings']
    RAW[dt] = d
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

# ===== ① IC =====
recs = []
for dt in dts:
    i0 = tdi[dt]
    if i0 + 61 >= len(tdays): continue
    for x in RAW[dt]:
        t = x['ticker']
        if t not in pcol: continue
        p0 = parr[i0, pcol[t]]; p60 = parr[i0 + 61, pcol[t]]
        if not (p0 == p0 and p0 > 0 and p60 == p60 and p60 > 0): continue
        r = {'d': dt, 'cr': x.get('composite_rank', 999), 'f60': p60 / p0 - 1}
        for s2 in SUBS:
            r[s2] = x.get(s2)
        recs.append(r)
df = pd.DataFrame(recs)
print(f"표본 {len(df)}행 / {df['d'].nunique()}일")

def ic_of(sub_df, col, lo=None, hi=None):
    ics = []
    for d, g in sub_df.groupby('d'):
        if lo and not (lo <= d <= hi): continue
        g2 = g.dropna(subset=[col, 'f60'])
        if len(g2) >= 10 and g2[col].nunique() > 3:
            v = sps.spearmanr(g2[col], g2['f60']).statistic
            if v == v: ics.append(v)
    return np.mean(ics) if ics else 0

print("\n===== ① 서브팩터 IC (fwd60) — 전체 / 강세 / 약세 / 최근 =====")
P = [('20190102', '20211231'), ('20220101', '20231231'), ('20240101', '20261231')]
for scope, sub in [('top65', df), ('top20', df[df['cr'] <= 20])]:
    print(f"  [{scope}]")
    for col in SUBS:
        used = '★사용' if col in ('rev_z', 'oca_z', 'gp_growth_z') else '  미사용'
        vals = [ic_of(sub, col)] + [ic_of(sub, col, lo, hi) for lo, hi in P]
        print(f"    {col:14s}{used}  전체 {vals[0]:+.3f} | 강세 {vals[1]:+.3f} 약세 {vals[2]:+.3f} 최근 {vals[3]:+.3f}")

print("\n===== ② 서브 간 상관 (top65, spearman) =====")
cm = df[SUBS].dropna().corr(method='spearman')
print(cm.round(2).to_string())

# ===== 주입 하니스 =====
def build_cr(mod_fn):
    out = {}
    for dt in dts:
        rows = RAW[dt]
        scores = []
        for x in rows:
            sc = x.get('score')
            scores.append(mod_fn(x, sc) if sc is not None else -99)
        order = np.argsort(-np.array(scores))
        out[dt] = {rows[idx]['ticker']: rank for rank, idx in enumerate(order, 1)}
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

def report(nm, CR):
    c, m, cal = sim(CR)
    p1 = sim(CR, P[0])[2]; p2 = sim(CR, P[1])[2]; p3 = sim(CR, P[2])[2]
    print(f"  {nm:26s}{cal:>7.2f}{m:>7.1f}{c:>7.1f}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f}")

base_cr = build_cr(lambda x, sc: sc)
print("\n===== ③ 3서브 재가중 주입 스윕 (rev/oca/gp — 현행 0.4/0.4/0.2) =====")
print(f"  {'가중':26s}{'전체':>7s}{'MDD':>7s}{'CAGR':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}")
report('현행 (baseline)', base_cr)
def reweight(w1, w2, w3):
    def f(x, sc):
        rev = x.get('rev_z') or 0; oca = x.get('oca_z') or 0; gp = x.get('gp_growth_z') or 0
        g_old = 0.4 * rev + 0.4 * oca + 0.2 * gp
        g_new = w1 * rev + w2 * oca + w3 * gp
        gs = x.get('growth_s')
        if gs is None or abs(g_old) < 0.05:
            return sc
        return sc + 0.55 * gs * (g_new / g_old - 1)
    return f
for w in [(1/3, 1/3, 1/3), (0.5, 0.3, 0.2), (0.3, 0.5, 0.2), (0.3, 0.3, 0.4), (0.2, 0.4, 0.4),
          (0.4, 0.2, 0.4), (0.5, 0.5, 0.0), (0.2, 0.2, 0.6)]:
    report(f'rev{w[0]:.2f}/oca{w[1]:.2f}/gp{w[2]:.2f}', build_cr(reweight(*w)))

print("\n===== ④ 미사용 서브 가산 주입 스윕 (score + W×sub_z) =====")
print(f"  {'변형':26s}{'전체':>7s}{'MDD':>7s}{'CAGR':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}")
def addsub(col, W):
    def f(x, sc):
        v = x.get(col)
        return sc + W * max(min(v, 3), -3) if v is not None else sc
    return f
for col in ['rev_accel_z', 'op_margin_z', 'cfo_growth_z']:
    for W in [0.03, 0.06, 0.10]:
        report(f'+{col} W{W}', build_cr(addsub(col, W)))
