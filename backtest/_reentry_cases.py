# -*- coding: utf-8 -*-
"""이탈 후 10일 내 재진입 거래 실사례 전수 — 날짜/종목명/보유기간/수익률."""
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
    nm = json.load(open(R + '/data_cache/ticker_names_cache.json', encoding='utf-8'))
    NAMES = nm if isinstance(nm, dict) else {}
except Exception:
    NAMES = {}
def name(t):
    v = NAMES.get(t, t)
    return v if isinstance(v, str) else t

# 현행 그대로 리플레이(쿨다운 없음), 재진입 거래에 직전 이탈 정보 기록
E, X, S = 3, 5, 3
port = {}; prev = None; trades = []
last_exit = {}   # t -> (exit_i, 직전거래 수익)
for i, d0 in enumerate(dts):
    if i < 2:
        prev = d0; continue
    if not reg.get(d0, True):
        port = {}; prev = d0; continue
    if reg.get(dts[i - 1], True) != reg.get(d0, True):
        port = {}
    a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
    wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
    for t in list(port.keys()):
        if wr(t) > X:
            info = port.pop(t)
            p = pxv(t, d0)
            ret = (p / info['px'] - 1) if (p and info['px']) else np.nan
            trades.append({'t': t, 'ein': info['i'], 'xin': i, 'ret': ret, 'gap': info['gap']})
            last_exit[t] = (i, ret)
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
        if len(port) >= S: break
        if t in port or wr(t) > E: continue
        gap = i - last_exit[t][0] if t in last_exit else 9999
        port[t] = {'i': i, 'px': pxv(t, d0), 'gap': gap}
    prev = d0

tdf = pd.DataFrame(trades).dropna(subset=['ret'])
re10 = tdf[tdf['gap'] <= 10].sort_values('ein')
print(f"이탈 후 10일 내 재진입 거래 전수: {len(re10)}건 (평균 {re10['ret'].mean()*100:+.2f}%, 승률 {(re10['ret']>0).mean()*100:.0f}%)\n")
print(f"{'재매수일':10s} {'종목':14s} {'며칠만에 되삼':>6s} {'보유':>4s} {'수익률':>8s}")
for _, r in re10.iterrows():
    print(f"{dts[int(r['ein'])]:10s} {name(r['t'])[:12]:14s} {int(r['gap']):>4d}일 {int(r['xin']-r['ein']):>3d}일 {r['ret']*100:>+8.2f}%")
print(f"\n손실 거래 합계: {re10[re10['ret']<0]['ret'].sum()*100:.1f}%p / 이익 거래 합계: {re10[re10['ret']>0]['ret'].sum()*100:.1f}%p")
