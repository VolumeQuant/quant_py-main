# -*- coding: utf-8 -*-
"""사용자 제안: '1,2,3위 점수 격차를 비중에 반영하면?' — 점수비례 가중 vs 동일가중 vs 확신가중(현행 제안).
하니스 = _conviction_cap_validate.py 동일 (production top3 리플레이 + 국면게이트).
비교: ①동일가중 ②점수비례 ③점수비례(softmax) ④확신가중 cap3(현행) ⑤확신×점수 결합."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
pcol = {c: i for i, c in enumerate(prices.columns)}; parr = prices.values
tdays = [d.strftime('%Y%m%d') for d in prices.index]; tdi = {d: i for i, d in enumerate(tdays)}
kc = pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
cache = pickle.load(open(P+'/backtest/_earn_cache.pkl', 'rb'))
mc = pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh = {t: mc.loc[t, '상장주식수'] for t in mc.index}
ar = {}; SC = {}; dts = []
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi:
        r = json.load(open(f, encoding='utf-8'))['rankings']
        ar[dt] = sorted(r, key=lambda z: z.get('rank', 99))
        SC[dt] = {x['ticker']: x.get('score', x.get('멀티팩터_점수')) for x in r}
        dts.append(dt)
dts = sorted(dts)
reg = {}; md = True; stk = 0; ss = None
for d in dts:
    ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
    s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
    if stk >= 5 and md != s: md = s
    reg[d] = md
def ttm(t, d):
    dd = cache.get(t); s = dd.get('ni') if dd else None
    if s is None: return None
    v = s[1][s[0] <= np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))]
    return v[-4:].sum() if len(v) >= 4 else None
gw = {}; fp = {}
for d in dts:
    i = tdi[d]; d1 = tdays[min(i+250, len(tdays)-1)]
    for t in [x['ticker'] for x in ar[d][:3]]:
        p0 = parr[i, pcol[t]] if t in pcol else None; e0 = ttm(t, d); e1 = ttm(t, d1)
        if p0 and p0 > 0 and e0 and e0 > 0 and e1 and e1 > 0 and t in sh and sh[t] > 0:
            gw[(d, t)] = e1/e0; fp[(d, t)] = (p0*sh[t])/(e1*1e8)
def conv_w(d, t, CAP=3.0, K=2.0, GATE=20.0):
    g = gw.get((d, t)); f = fp.get((d, t))
    if g is None or f is None or f >= GATE: return 1.0
    return min(1.0+K*max(g-1.0, 0.0), CAP)
def sim(mode, lo=None, hi=None):
    held = []; daily = []; prev = None; pw = {}
    for d in dts:
        inseg = (lo is None) or (lo <= d <= hi); ret = 0.0
        if held and prev and inseg:
            num = 0; den = 0
            for t in held:
                if t in pcol and parr[tdi[prev], pcol[t]] > 0 and parr[tdi[d], pcol[t]] > 0:
                    w = pw.get(t, 1.0); num += w*(parr[tdi[d], pcol[t]]/parr[tdi[prev], pcol[t]]-1); den += w
            ret = num/den if den > 0 else 0.0
        if inseg: daily.append(ret)
        if not reg.get(d, True): held = []; pw = {}
        else:
            held = [x['ticker'] for x in ar[d][:3]]
            scs = {t: SC[d].get(t) for t in held}
            valid = all(s is not None and s == s and s > -900 for s in scs.values())
            if mode == 'equal': pw = {t: 1.0 for t in held}
            elif mode == 'score':   # 점수비례 (음수 방지 floor 0.1)
                pw = {t: max(scs[t], 0.1) for t in held} if valid else {t: 1.0 for t in held}
            elif mode == 'softmax':  # 격차 증폭 (tau=0.3)
                if valid:
                    e = {t: np.exp(scs[t]/0.3) for t in held}; pw = e
                else: pw = {t: 1.0 for t in held}
            elif mode == 'conv': pw = {t: conv_w(d, t) for t in held}
            elif mode == 'conv_x_score':
                pw = {t: conv_w(d, t)*max(scs[t], 0.1) for t in held} if valid else {t: conv_w(d, t) for t in held}
        prev = d
    a = np.array(daily); eq = np.cumprod(1+a); peak = np.maximum.accumulate(eq)
    mdd = ((eq-peak)/peak).min()*100; cagr = (eq[-1]**(252/max(len(a), 1))-1)*100
    return (cagr/abs(mdd) if mdd < 0 else 0), mdd
segs = [('전체', None, None), ('19-21', dts[0], '20211231'), ('22-23약세', '20220101', '20231231'), ('24-26', '20240101', dts[-1])]
print("[점수격차 비중 반영 실험 — Calmar (MDD)]  ※ 확신가중은 look-ahead proxy 상한, 상대비교용\n")
print(f"  {'비중방식':<16}" + "".join(f"{nm:>14s}" for nm, _, _ in segs))
for mode, lbl in [('equal', '동일가중'), ('score', '점수비례'), ('softmax', '점수softmax(증폭)'),
                  ('conv', '확신가중 cap3(현행)'), ('conv_x_score', '확신×점수 결합')]:
    row = f"  {lbl:<16}"
    for _, lo, hi in segs:
        c, m = sim(mode, lo, hi); row += f"  {c:6.2f}({m:5.1f})"
    print(row)
