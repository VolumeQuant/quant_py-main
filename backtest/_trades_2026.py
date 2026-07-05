# -*- coding: utf-8 -*-
"""2026년 매매내역 — 현행 룰(E3 X5 S3 + 쿨다운10 + 브레드스) faithful 리플레이.
청산 완료 + 현재 보유(미실현) + 월별 요약. 가격 데이터 한도: 로컬 adj OHLCV 마지막일."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = 'C:/dev/claude-code/quant_py-main'
px = pd.read_parquet(R + '/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
parr = px.values
pcol = {c: i for i, c in enumerate(px.columns)}
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
def nm(t):
    v = NAMES.get(t, t)
    return v if isinstance(v, str) else t

port = {}; prev = None; trades = []; last_exit = {}
for i, d0 in enumerate(dts):
    if i < 2:
        prev = d0; continue
    if not reg.get(d0, True):
        for t, info in port.items():
            p = pxv(t, d0)
            trades.append({'t': t, 'ed': info['d'], 'ep': info['px'], 'xd': d0, 'xp': p, 'why': '국면전환'})
        port = {}; prev = d0; continue
    if reg.get(dts[i - 1], True) != reg.get(d0, True):
        for t, info in port.items():
            p = pxv(t, d0)
            trades.append({'t': t, 'ed': info['d'], 'ep': info['px'], 'xd': d0, 'xp': p, 'why': '국면전환'})
        port = {}
    a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
    wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
    for t in list(port.keys()):
        if wr(t) > 5:
            info = port.pop(t); last_exit[t] = i
            p = pxv(t, d0)
            trades.append({'t': t, 'ed': info['d'], 'ep': info['px'], 'xd': d0, 'xp': p, 'why': '순위이탈'})
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    # ★production 시맨틱스: verified 상위 ENTRY_RANK 슬라이스 (wr 절대게이트 없음) + 쿨다운 승격금지
    verified = sorted(t20(a0) & t20(a1) & t20(a2), key=lambda t: (wr(t), a0.get(t, 50)))
    for t in verified[:3]:
        if t in port: continue
        if len(port) >= 3: break
        if t in last_exit and i - last_exit[t] <= 10: continue
        p = pxv(t, d0)
        if p and p > 0:
            port[t] = {'d': d0, 'px': p}
    prev = d0

t26 = [t for t in trades if t['xd'] >= '20260101']
print(f"===== 2026년 청산 완료 거래 ({len(t26)}건) =====")
print(f"{'매수일':>10s} {'매도일':>10s} {'종목':14s} {'보유':>5s} {'매수가':>10s} {'매도가':>10s} {'수익률':>8s} {'사유':6s}")
wins = 0; rets = []
for t in sorted(t26, key=lambda x: x['xd']):
    r = t['xp'] / t['ep'] - 1 if (t['xp'] and t['ep']) else None
    hold = (pd.Timestamp(t['xd']) - pd.Timestamp(t['ed'])).days
    rs = f"{r*100:+.1f}%" if r is not None else '?'
    if r is not None:
        rets.append(r)
        if r > 0: wins += 1
    print(f"{t['ed']:>10s} {t['xd']:>10s} {nm(t['t'])[:12]:14s} {hold:>4d}d {t['ep']:>10,.0f} {t['xp']:>10,.0f} {rs:>8s} {t['why']}")
print(f"\n청산 요약: {len(rets)}건 · 승 {wins} 패 {len(rets)-wins} (승률 {wins/len(rets)*100:.0f}%) · 평균 {np.mean(rets)*100:+.1f}% · 합계(단순) {sum(rets)*100:+.1f}%p")

print(f"\n===== 현재 보유 중 (미청산, 가격은 {tdays[-1]} 기준) =====")
last_d = dts[-1]
for t, info in sorted(port.items(), key=lambda x: x[1]['d']):
    p_now = pxv(t, last_d)
    r = p_now / info['px'] - 1 if (p_now and info['px']) else None
    hold = (pd.Timestamp(last_d) - pd.Timestamp(info['d'])).days
    rs = f"{r*100:+.1f}%" if r is not None else '?'
    print(f"  {nm(t)[:12]:14s} 매수 {info['d']} ({hold}일 보유중) @ {info['px']:,.0f} → 현재 {p_now:,.0f} ({rs})")

# 월별 매매 횟수
print("\n===== 월별 매매 빈도 (2026) =====")
ev = {}
for t in t26:
    ev[t['ed'][:6]] = ev.get(t['ed'][:6], 0) + 1  # 매수
    ev[t['xd'][:6]] = ev.get(t['xd'][:6], 0) + 1  # 매도
for t, info in port.items():
    if info['d'] >= '20260101':
        ev[info['d'][:6]] = ev.get(info['d'][:6], 0) + 1
for m in sorted(k for k in ev if k >= '202601'):
    print(f"  {m[:4]}.{m[4:]}: {'█' * ev[m]} {ev[m]}회")
