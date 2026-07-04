# -*- coding: utf-8 -*-
"""재진입 쿨다운 robust 검증: K 확장스윕 / LOWO / 차단거래 전수 / 연도분해."""
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

NAMES = {}
try:
    nm = json.load(open(R + '/data_cache/ticker_names.json', encoding='utf-8'))
    NAMES = {k: v for k, v in nm.items()} if isinstance(nm, dict) else {}
except Exception:
    pass

def run(cooldown=0, exclude=None, collect_blocked=False):
    E, X, S = 3, 5, 3
    port = {}; prev = None; daily = []; blocked = []
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
            if t in port or wr(t) > E or t == exclude: continue
            gap = i - last_exit[t] if t in last_exit else 9999
            if gap <= cooldown:
                if collect_blocked and (not blocked or blocked[-1][0] != t or i - blocked[-1][1] > 1):
                    # 차단 시작점만 기록 (연속차단 중복 제거), fwd20 수익
                    p0 = pxv(t, d0)
                    i20 = min(i + 20, len(dts) - 1)
                    p20 = pxv(t, dts[i20])
                    blocked.append((t, i, d0, (p20 / p0 - 1) * 100 if (p0 and p20) else np.nan))
                continue
            port[t] = 1
        prev = d0
    a = np.array([r for _, r in daily])
    eq = np.cumprod(1 + a); peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min() * 100
    cagr = (eq[-1] ** (252 / len(a)) - 1) * 100
    def sub(lo, hi):
        m = np.array([(dd >= lo) & (dd <= hi) for dd, _ in daily])
        aa = a[m]
        if len(aa) < 20: return 0
        e = np.cumprod(1 + aa); p = np.maximum.accumulate(e)
        md_ = ((e - p) / p).min() * 100; cg = (e[-1] ** (252 / len(aa)) - 1) * 100
        return cg / abs(md_) if md_ < 0 else 0
    return (cagr / abs(mdd) if mdd < 0 else 0, mdd,
            sub('20190102', '20211231'), sub('20220101', '20231231'), sub('20240101', '20261231'), blocked)

print("[K 확장 스윕 — 절벽/plateau 확인]")
print(f"  {'K':6s}{'전체':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}")
vals = {}
for K in [0, 3, 5, 8, 10, 13, 15, 20, 30]:
    cal, mdd, p1, p2, p3, _ = run(K)
    vals[K] = cal
    print(f"  K={K:<4d}{cal:>7.2f}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f}")

print("\n[LOWO — 슈퍼위너 제외 시 K=10 vs K=0]")
for ex, nm2 in [('000660', 'SK하이닉스'), ('080220', '제주반도체'), ('089970', '브이엠'), ('042700', '한미반도체'), ('006910', '보성파워텍')]:
    c0 = run(0, exclude=ex)[0]; c10 = run(10, exclude=ex)[0]
    print(f"  −{nm2:10s}: K0 {c0:5.2f} → K10 {c10:5.2f}  Δ{c10-c0:+.2f}")

print("\n[K=10이 차단한 재진입 전수 — 만약 샀다면 fwd20 수익]")
_, _, _, _, _, blocked = run(10, collect_blocked=True)
bdf = pd.DataFrame(blocked, columns=['t', 'i', 'd', 'fwd20'])
bdf = bdf.drop_duplicates(subset=['t', 'd'])
print(f"  차단 에피소드 {len(bdf)}건, fwd20 평균 {bdf['fwd20'].mean():+.2f}% 중앙 {bdf['fwd20'].median():+.2f}% 승률 {(bdf['fwd20']>0).mean()*100:.0f}%")
for _, r in bdf.iterrows():
    print(f"    {r['d']} {r['t']} {NAMES.get(r['t'],'')[:8]:8s} fwd20 {r['fwd20']:+7.2f}%")
