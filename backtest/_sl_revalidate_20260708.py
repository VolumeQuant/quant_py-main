# -*- coding: utf-8 -*-
"""SL(손절) 재도입 사전 재검증 — 사용자 "제주 -25%, -30% 트리거 기다리면 늦다, 미리 재봐라" (2026-07-08).
현행 production 시맨틱스(X5 + 재진입쿨다운10 + 브레드스)에 SL 레벨 스윕.
과거 기각(v80.22 제거, 6/25 창의함정 SL 기각)은 X6·브레드스 이전 — 새 환경(2026 고상관 크래시)에서 재판정.
SL 체결 = 종가 기준(장중 갭 미반영 = SL에 관대한 가정), SL 이탈도 쿨다운 적용."""
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
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in json.load(open(f, encoding='utf-8'))['rankings']}
    dts.append(dt)
dts = sorted(dts)
sys.path.insert(0, R)
from breadth_diagnostic import breadth_scale_by_date as _bsbd
BRD = _bsbd(list(dts))
reg = {}; md = True; stk = 0; ss = None
for dd in dts:
    ts = pd.Timestamp(dd[:4]+'-'+dd[4:6]+'-'+dd[6:])
    if ts in kc.index and not pd.isna(ma80.get(ts, np.nan)):
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
    reg[dd] = md

def sim(sl, use_b=True):
    """sl: None 또는 음수(예 -0.10). 반환: daily 수익 + 거래별 수익 리스트."""
    port = {}  # ticker -> entry_price
    last_exit = {}; daily = []; prev = None; trades = []
    for i, d0 in enumerate(dts):
        avg = 0.0
        if port and prev:
            rr = [parr[tdi[d0], pcol[t]]/parr[tdi[prev], pcol[t]]-1 for t in port
                  if t in pcol and parr[tdi[prev], pcol[t]] > 0 and parr[tdi[d0], pcol[t]] > 0]
            avg = np.mean(rr) if rr else 0.0
        daily.append((d0, avg*(BRD.get(d0, 1.0) if use_b else 1.0)))
        if i < 2: continue
        if not reg.get(d0, True):
            for t, ep in port.items():
                p = parr[tdi[d0], pcol[t]]
                if p > 0 and ep > 0: trades.append(p/ep-1)
            port = {}; prev = d0; continue
        if reg.get(dts[i-1], True) != reg.get(d0, True):
            for t, ep in port.items():
                p = parr[tdi[d0], pcol[t]]
                if p > 0 and ep > 0: trades.append(p/ep-1)
            port.clear()
        a0, a1, a2 = CR[d0], CR[dts[i-1]], CR[dts[i-2]]
        def wr(t): return a0.get(t, 50)*0.4 + a1.get(t, 50)*0.35 + a2.get(t, 50)*0.25
        for t in list(port):
            p = parr[tdi[d0], pcol[t]]
            hit_sl = sl is not None and p > 0 and port[t] > 0 and (p/port[t]-1) <= sl
            if wr(t) > 5 or hit_sl:
                if p > 0 and port[t] > 0: trades.append(p/port[t]-1)
                del port[t]; last_exit[t] = i
        t20 = lambda a: {t for t, r in a.items() if r <= 20}
        for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
            if len(port) >= 3: break
            if wr(t) > 3: break
            if t in port: continue
            if t in last_exit and (i - last_exit[t]) <= 10: continue
            ep = parr[tdi[d0], pcol[t]]
            if t in pcol and ep > 0: port[t] = ep
        prev = d0
    return daily, trades

def st(daily, s0, s1='29991231'):
    a = np.array([r for dd, r in daily if s0 <= dd <= s1])
    eq = np.cumprod(1+a); peak = np.maximum.accumulate(eq)
    mdd = ((eq-peak)/peak).min()*100; cagr = (eq[-1]**(252/len(a))-1)*100
    return cagr/abs(mdd) if mdd < 0 else 0, mdd

print("[SL 재검증 — 현행 X5+쿨다운10 하니스, Calmar / (MDD)]  ※ 종가 기준 SL = 관대한 가정\n")
print(f"  {'SL':<10}{'전체':>14}{'약세22-23':>14}{'24-26':>14}{'2026~':>14}{'최악거래':>10}{'거래수':>8}")
for sl, lbl in [(None, '없음(현행)'), (-0.08, '-8%'), (-0.10, '-10%'), (-0.12, '-12%'),
                (-0.15, '-15%'), (-0.20, '-20%'), (-0.25, '-25%'), (-0.30, '-30%')]:
    daily, trades = sim(sl)
    c_all, m_all = st(daily, '20190102'); c_b, m_b = st(daily, '20220101', '20231231')
    c_r, m_r = st(daily, '20240101'); c_26, m_26 = st(daily, '20260101')
    worst = min(trades)*100 if trades else 0
    print(f"  {lbl:<10}{c_all:7.2f}({m_all:5.1f}){c_b:7.2f}({m_b:5.1f}){c_r:7.2f}({m_r:5.1f}){c_26:7.2f}({m_26:5.1f}){worst:9.1f}%{len(trades):7d}건")
print("\n[브레드스 무시(=현재 행동) 기준 — 전체 / 2026~]")
for sl, lbl in [(None, '없음(현행)'), (-0.10, '-10%'), (-0.15, '-15%'), (-0.20, '-20%')]:
    daily, trades = sim(sl, use_b=False)
    c_all, m_all = st(daily, '20190102'); c_26, m_26 = st(daily, '20260101')
    print(f"  {lbl:<10} 전체 {c_all:.2f}({m_all:.1f})  2026~ {c_26:.2f}({m_26:.1f})  최악 {min(trades)*100:.1f}%")
