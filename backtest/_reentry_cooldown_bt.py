# -*- coding: utf-8 -*-
"""이탈 후 재진입 EDA + 쿨다운 BT.
Q1: rank_exit 후 K일 내 재진입 거래가 fresh 진입보다 나쁜가?
Q2: 재진입 쿨다운(이탈 후 K일 진입금지)이 성과 개선하나?
하니스 = faithful E3X5S3 + 브레드스."""
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

def run(cooldown=0, collect_trades=False):
    E, X, S = 3, 5, 3
    port = {}; prev = None; daily = []; trades = []
    last_exit = {}   # ticker -> date index of last rank_exit
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
                p = pxv(t, d0); info = port.pop(t)
                if collect_trades:
                    trades.append({'t': t, 'entry_i': info['i'], 'exit_i': i,
                                   'ret': (p / info['px'] - 1) if (p and info['px']) else np.nan,
                                   'reentry_gap': info['gap']})
                last_exit[t] = i
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
            if len(port) >= S: break
            if t in port or wr(t) > E: continue
            gap = i - last_exit[t] if t in last_exit else 9999
            if gap <= cooldown: continue   # 쿨다운 차단
            port[t] = {'i': i, 'px': pxv(t, d0), 'gap': gap}
        prev = d0
    a = np.array([r for _, r in daily])
    eq = np.cumprod(1 + a); peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min() * 100
    cagr = (eq[-1] ** (252 / len(a)) - 1) * 100
    # 기간별
    def sub(lo, hi):
        m = [(dd >= lo) & (dd <= hi) for dd, _ in daily]
        aa = a[np.array(m)]
        if len(aa) < 20: return 0
        e = np.cumprod(1 + aa); p = np.maximum.accumulate(e)
        md_ = ((e - p) / p).min() * 100; cg = (e[-1] ** (252 / len(aa)) - 1) * 100
        return cg / abs(md_) if md_ < 0 else 0
    return (cagr / abs(mdd) if mdd < 0 else 0, mdd, sub('20190102', '20211231'),
            sub('20220101', '20231231'), sub('20240101', '20261231'), trades)

# Q1: 재진입 거래 특성
cal, mdd, p1, p2, p3, trades = run(0, collect_trades=True)
tdf = pd.DataFrame(trades).dropna(subset=['ret'])
print(f"baseline Cal {cal:.2f} MDD {mdd:.1f} | 거래 {len(tdf)}건")
for lo, hi, lbl in [(1, 3, '이탈후 1~3일 재진입'), (4, 10, '4~10일'), (11, 30, '11~30일'), (31, 9998, '31일+'), (9999, 99999, 'fresh(첫진입)')]:
    g = tdf[(tdf['reentry_gap'] >= lo) & (tdf['reentry_gap'] <= hi)]
    if len(g):
        print(f"  {lbl:22s}: {len(g):3d}건 승률 {(g['ret']>0).mean()*100:3.0f}% 평균 {g['ret'].mean()*100:+6.2f}% 중앙 {g['ret'].median()*100:+6.2f}%")

# Q2: 쿨다운 BT
print("\n[쿨다운 BT — 이탈 후 K일 진입금지]")
print(f"  {'K':6s}{'전체':>7s}{'MDD':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}")
for K in [0, 1, 2, 3, 5, 10]:
    cal, mdd, p1, p2, p3, _ = run(K)
    star = ' ←현행' if K == 0 else ''
    print(f"  K={K:<4d}{cal:>7.2f}{mdd:>7.1f}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f}{star}")
