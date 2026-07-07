# -*- coding: utf-8 -*-
"""사용자 질문: '작년(2025)이랑 올해(2026)만 놓고 보면 X5가 나았어 X6이 나았어?'
_fastexit_faithful.py 하니스 재사용 (현재 경로/최신 parquet), wr 이탈 5 vs 6, 브레드스 ON/OFF, 연도별."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
R = 'C:/dev'
px = pd.read_parquet(sorted(glob.glob(R+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
px = px[px.notna().any(axis=1)]
pcol = {c: i for i, c in enumerate(px.columns)}; parr = px.values
tdays = [d.strftime('%Y%m%d') for d in px.index]; tdi = {d: i for i, d in enumerate(tdays)}
kc = pd.read_parquet(R+'/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
CR = {}; dts = []
for f in sorted(glob.glob(R+'/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi): continue
    r = json.load(open(f, encoding='utf-8'))['rankings']
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in r}
    dts.append(dt)
dts = sorted(dts)
sys.path.insert(0, R)
from breadth_diagnostic import breadth_scale_by_date as _bsbd
BRD = _bsbd(list(dts))
print(f"브레드스 스케일: {sum(1 for v in BRD.values() if v < 1.0)}일 발동 / {len(dts)}일")
reg = {}; md = True; stk = 0; ss = None
for dd in dts:
    ts = pd.Timestamp(dd[:4]+'-'+dd[4:6]+'-'+dd[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[dd] = md; continue
    s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
    if stk >= 5 and md != s: md = s
    reg[dd] = md
def pxv(t, d): return parr[tdi[d], pcol[t]] if (t in pcol and d in tdi) else None

def sim(exit_rank, use_breadth):
    port = set(); prev = None; daily = []
    for i, d0 in enumerate(dts):
        avg = 0.0
        if port and prev:
            rr = [pxv(t, d0)/pxv(t, prev)-1 for t in port
                  if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
            avg = np.mean(rr) if rr else 0.0
        sc = BRD.get(d0, 1.0) if use_breadth else 1.0
        daily.append((d0, avg*sc))
        if i < 2: continue
        d1, d2 = dts[i-1], dts[i-2]
        if not reg.get(d0, True): port = set(); prev = d0; continue
        if reg.get(dts[i-1], True) != reg.get(d0, True): port.clear()
        a0, a1, a2 = CR[d0], CR[d1], CR[d2]
        def wr(t): return a0.get(t, 50)*0.4 + a1.get(t, 50)*0.35 + a2.get(t, 50)*0.25
        port = {t for t in port if wr(t) <= exit_rank}
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        common = t20(a0) & t20(a1) & t20(a2)
        for t in sorted(common, key=wr):
            if len(port) >= 3: break
            if wr(t) <= 3: port.add(t)
        prev = d0
    return daily

def stats(daily, sub):
    a = np.array([r for dd, r in daily if sub[0] <= dd <= sub[1]])
    if len(a) < 20: return None
    eq = np.cumprod(1+a); peak = np.maximum.accumulate(eq)
    mdd = ((eq-peak)/peak).min()*100
    tot = (eq[-1]-1)*100
    return tot, mdd

SUBS = [('2025', ('20250101', '20251231')), ('2026(~7/7)', ('20260101', '20991231')),
        ('25+26 합산', ('20250101', '20991231'))]
print(f"\n[{'구성':<26}] " + "".join(f"{nm:>22}" for nm, _ in SUBS) + "   (누적% / MDD%)")
for use_b, blbl in [(True, '브레드스 지킴'), (False, '브레드스 무시(=현재 행동)')]:
    for er in [5, 6]:
        d = sim(er, use_b)
        row = f"  X{er} + {blbl:<18}"
        for _, sub in SUBS:
            s = stats(d, sub)
            row += f" {s[0]:+9.1f}%/{s[1]:6.1f}%" if s else f" {'—':>17}"
        print(row)
