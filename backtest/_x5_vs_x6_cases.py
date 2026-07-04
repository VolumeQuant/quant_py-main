# -*- coding: utf-8 -*-
"""X5 vs X6 실제 분기 사례 전수 — X5가 wr 5~6 구간에서 먼저 판 종목의 이후 경로.
X5 매도일 가격 vs X6 매도일 가격 → X6이 더 들고가서 얻은/잃은 수익."""
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
    """일별 보유 + 거래로그(이탈만)"""
    port = {}; res = {}; exits = []
    for i, d0 in enumerate(dts):
        if i < 2: res[d0] = dict(port); continue
        if not reg.get(d0, True): port = {}; res[d0] = {}; continue
        if reg.get(dts[i - 1], True) != reg.get(d0, True): port = {}
        a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
        wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
        for t in list(port.keys()):
            if wr(t) > X:
                exits.append((t, port.pop(t), i))
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
            if len(port) >= 3: break
            if t not in port and wr(t) <= 3: port[t] = i
        res[d0] = dict(port)
    return res, exits

p5, ex5 = replay(5)
p6, ex6 = replay(6)

# X5가 판 시점에 X6은 아직 들고있던 에피소드: (t, entry_i 동일, X5 exit_i)
ex6_map = {}   # (t, entry_i) -> exit_i (X6)
for t, ei, xi in ex6:
    ex6_map[(t, ei)] = xi
rows = []
for t, ei, xi5 in ex5:
    xi6 = ex6_map.get((t, ei))
    if xi6 is None or xi6 <= xi5:  # X6도 같은날(or 더 먼저) 팔았으면 분기 아님
        continue
    px5 = pxv(t, dts[xi5]); px6 = pxv(t, dts[xi6])
    if not px5 or not px6: continue
    extra = (px6 / px5 - 1) * 100   # X6이 더 들고가서 얻은 수익(+면 X6 유리, -면 X5가 잘 판 것)
    rows.append({'t': t, 'name': name(t), 'sell5': dts[xi5], 'sell6': dts[xi6],
                 'extra_days': xi6 - xi5, 'extra': extra})
df = pd.DataFrame(rows)
print(f"분기 에피소드(X5 먼저 매도, X6 계속보유): {len(df)}건")
print(f"X6이 더 들고가서 얻은 수익: 평균 {df['extra'].mean():+.2f}% / 중앙 {df['extra'].median():+.2f}% / X5가 잘 판 비율 {(df['extra']<0).mean()*100:.0f}%")
print(f"합계: X5가 아낀 손실 {df[df['extra']<0]['extra'].sum():.1f}%p vs X5가 놓친 수익 {df[df['extra']>0]['extra'].sum():.1f}%p\n")
df = df.sort_values('extra')
print("[X5가 먼저 팔아서 아낀 사례 TOP10 (X6은 이만큼 더 떨어진 뒤 팔았음)]")
for _, r in df.head(10).iterrows():
    print(f"  {r['sell5']} {r['name'][:10]:12s} X5매도 → X6은 {r['extra_days']}일 더 들고 {r['extra']:+.1f}% 추가손실 후 매도({r['sell6']})")
print("\n[반대로 X5가 성급했던 사례 TOP10 (X6은 더 들고 벌었음)]")
for _, r in df.tail(10).iloc[::-1].iterrows():
    print(f"  {r['sell5']} {r['name'][:10]:12s} X5매도 → X6은 {r['extra_days']}일 더 들고 {r['extra']:+.1f}% 추가수익 후 매도({r['sell6']})")
print("\n[연도별 분기 결과]")
df['yr'] = df['sell5'].str[:4]
for y, g in df.groupby('yr'):
    print(f"  {y}: {len(g)}건, X6 추가보유 수익 합 {g['extra'].sum():+.1f}%p (음수=X5 우위)")
