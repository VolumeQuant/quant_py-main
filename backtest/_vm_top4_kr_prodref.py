# -*- coding: utf-8 -*-
"""VM top4 핸드오프 — 같은 하니스(가격/국면/stats)로 production top3(정직, look-ahead 0) 참조행."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
prices = prices[prices.notna().any(axis=1)]
pcol = {c: i for i, c in enumerate(prices.columns)}; parr = prices.values
tdays = [d.strftime('%Y%m%d') for d in prices.index]; tdi = {d: i for i, d in enumerate(tdays)}
kc = pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
ar = {}
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi:
        ar[dt] = sorted(json.load(open(f, encoding='utf-8'))['rankings'], key=lambda z: z.get('rank', 99))
dts = sorted(ar.keys())
reg = {}; md = True; stk = 0; ss = None
for d in dts:
    ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts in kc.index and not pd.isna(ma80.get(ts, np.nan)):
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
    reg[d] = md
held = []; rets = []; prev = None
for d in dts:
    r = 0.0
    if held and prev:
        vs = [parr[tdi[d], pcol[t]]/parr[tdi[prev], pcol[t]]-1 for t in held
              if t in pcol and parr[tdi[prev], pcol[t]] > 0 and parr[tdi[d], pcol[t]] > 0]
        r = float(np.mean(vs)) if vs else 0.0
    rets.append((d, r))
    held = [] if not reg.get(d, True) else [x['ticker'] for x in ar[d][:3]]
    prev = d
def stats(sub=None):
    a = np.array([r for d, r in rets if (not sub or sub[0] <= d <= sub[1])])
    eq = np.cumprod(1+a); peak = np.maximum.accumulate(eq)
    mdd = ((eq-peak)/peak).min()*100; cagr = (eq[-1]**(252/len(a))-1)*100
    return cagr, mdd, cagr/abs(mdd) if mdd < 0 else 0
print("[production top3 참조 (동일 하니스, look-ahead 0 = 정직)]")
for nm, sub in [('전체', None), ('강세19-21', ('20190102', '20211231')),
                ('약세22-23', ('20220101', '20231231')), ('최근24-26', ('20240101', '20991231'))]:
    c, m, cal = stats(sub)
    print(f"  {nm:<10} CAGR {c:+7.0f}% / MDD {m:5.1f}% / Calmar {cal:.2f}")
