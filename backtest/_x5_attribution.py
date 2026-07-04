# -*- coding: utf-8 -*-
"""X5 vs X6 분기 에피소드의 포트폴리오 레벨 귀속 — 판 종목 경로가 아니라
그 기간 X5 포트 수익 vs X6 포트 수익 차이(대체종목 효과 포함)."""
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
try:
    NAMES = json.load(open(R + '/data_cache/ticker_names_cache.json', encoding='utf-8'))
except Exception:
    NAMES = {}
def name(t):
    v = NAMES.get(t, t)
    return v if isinstance(v, str) else t

def replay(X):
    port = {}; prev = None; hold = {}; ret = {}
    for i, d0 in enumerate(dts):
        avg = 0.0
        if port and prev:
            rr = [pxv(t, d0) / pxv(t, prev) - 1 for t in port
                  if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
            avg = np.mean(rr) if rr else 0.0
        ret[d0] = avg * BRD.get(d0, 1.0)
        if i < 2:
            hold[d0] = set(port); prev = d0; continue
        if not reg.get(d0, True):
            port = {}; hold[d0] = set(); prev = d0; continue
        if reg.get(dts[i - 1], True) != reg.get(d0, True): port = {}
        a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
        wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
        port = {t: 1 for t in port if wr(t) <= X}
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
            if len(port) >= 3: break
            if t not in port and wr(t) <= 3: port[t] = 1
        hold[d0] = set(port); prev = d0
    return hold, ret

h5, r5 = replay(5)
h6, r6 = replay(6)

# 보유 다른 날들 → 연속 구간 = 분기 에피소드, 그 구간 일수익 차 합
diff_days = [d for d in dts if h5[d] != h6[d]]
print(f"보유 다른 날: {len(diff_days)}일 / {len(dts)}일")
epis = []
cur = None
for d in dts:
    if h5[d] != h6[d]:
        if cur is None: cur = [d, d]
        else: cur[1] = d
    else:
        if cur: epis.append(tuple(cur)); cur = None
if cur: epis.append(tuple(cur))
rows = []
for lo, hi in epis:
    seg = [d for d in dts if lo <= d <= hi]
    dd = sum(r5[d] - r6[d] for d in seg) * 100
    # 그 구간 대표 차이종목
    only6 = set(); only5 = set()
    for d in seg:
        only6 |= (h6[d] - h5[d]); only5 |= (h5[d] - h6[d])
    rows.append({'lo': lo, 'hi': hi, 'days': len(seg), 'diff': dd,
                 'x6held': ','.join(name(t)[:6] for t in list(only6)[:3]),
                 'x5held': ','.join(name(t)[:6] for t in list(only5)[:3])})
df = pd.DataFrame(rows)
print(f"에피소드 {len(df)}건, 포트수익차 합 {df['diff'].sum():+.1f}%p (양수=X5 우위), X5 우위 비율 {(df['diff']>0).mean()*100:.0f}%")
df = df.sort_values('diff', ascending=False)
print("\n[X5가 크게 이긴 에피소드 TOP8 — X6이 뭘 들고있었고 X5는 뭘 대신 들었나]")
for _, r in df.head(8).iterrows():
    print(f"  {r['lo']}~{r['hi']} ({r['days']}일) Δ{r['diff']:+.1f}%p | X6만 보유: {r['x6held']} / X5만 보유: {r['x5held'] or '(현금)'}")
print("\n[X5가 크게 진 에피소드 TOP8]")
for _, r in df.tail(8).iloc[::-1].iterrows():
    print(f"  {r['lo']}~{r['hi']} ({r['days']}일) Δ{r['diff']:+.1f}%p | X6만 보유: {r['x6held']} / X5만 보유: {r['x5held'] or '(현금)'}")
print("\n[연도별 포트수익차 합 (양수=X5 우위)]")
df['yr'] = df['lo'].str[:4]
for y, g in df.groupby('yr'):
    print(f"  {y}: {g['diff'].sum():+.1f}%p ({len(g)}건)")
