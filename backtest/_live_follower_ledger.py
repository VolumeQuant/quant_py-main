# -*- coding: utf-8 -*-
"""진짜 메시지 팔로워 원장 — 진입: picks 등장 시 매수 / 청산: picks 이탈 시 매도.
당시 발송된 신호 그대로 (룰 진화 포함) = 라이브 실경험. + 현재룰 리플레이 동기간 비교.
★2026-07-10 수정: 구버전은 web_data 'exited'를 청산신호로 썼으나 그 필드는 top30
'표시목록' 이탈이지 매도신호가 아님 — picks에서 빠져도 top30 안에 머물면 영영 안 팔려
포지션이 누적(평균 10종목, 3슬롯 시스템인데)되는 버그. 청산 = picks 이탈로 교체."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 레포 루트 (PC별 경로 상이)
px = pd.read_parquet(sorted(glob.glob(R + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
k = pd.read_parquet(R + '/data_cache/kospi_yf.parquet').iloc[:, 0].dropna()
try:
    NM = json.load(open(R + '/data_cache/ticker_names_cache.json', encoding='utf-8'))
except Exception:
    NM = {}
def nm(t):
    v = NM.get(t, t); return v if isinstance(v, str) else t

picks = {}
for f in sorted(glob.glob(R + '/state/web_data_*.json')):
    dt = os.path.basename(f)[9:17]
    try:
        picks[dt] = [p['ticker'] for p in json.load(open(f, encoding='utf-8')).get('picks', [])]
    except Exception:
        continue
days = sorted(picks)

def pxat(t, d):
    try:
        s = px[t].loc[:pd.Timestamp(d)].dropna()
        return float(s.iloc[-1]) if len(s) else None
    except Exception:
        return None

port = {}; trades = []; daily = []
for i, d0 in enumerate(days):
    # 일수익 (전일 보유 기준)
    if i >= 1 and port:
        rr = []
        for t in port:
            p0 = pxat(t, days[i - 1]); p1 = pxat(t, d0)
            if p0 and p1 and p0 > 0: rr.append(p1 / p0 - 1)
        daily.append((d0, np.mean(rr) if rr else 0.0, len(port)))
    else:
        daily.append((d0, 0.0, len(port)))
    # 청산: 보유 종목이 당일 picks에서 빠지면 매도 (메시지에서 매수 후보가 사라짐 = 매도 신호)
    cur_picks = set(picks[d0])
    for t in list(port):
        if t not in cur_picks:
            p = pxat(t, d0)
            trades.append({'t': t, 'ed': port[t]['d'], 'xd': d0,
                           'ret': p / port[t]['px'] - 1 if (p and port[t]['px']) else np.nan})
            port.pop(t)
    # 진입: picks에 새로 등장
    for t in picks[d0]:
        if t not in port:
            p = pxat(t, d0)
            if p and p > 0:
                port[t] = {'d': d0, 'px': p}

D = pd.DataFrame(daily, columns=['d', 'ret', 'n'])
eq = (1 + D['ret']).cumprod()
mdd = (eq / eq.cummax() - 1).min() * 100
kk = k[(k.index >= days[0]) & (k.index <= days[-1])]
print(f"===== 진짜 팔로워 원장 ({days[0]}~{days[-1]}, 당시 발송 신호 그대로) =====")
print(f"  누적: {(eq.iloc[-1]-1)*100:+.1f}% / MDD {mdd:.1f}% / 평균 보유 {D['n'].mean():.1f}종목")
print(f"  KOSPI 동기간: {(kk.iloc[-1]/kk.iloc[0]-1)*100:+.1f}%")

tdf = pd.DataFrame(trades).dropna(subset=['ret'])
print(f"\n  청산 완료 {len(tdf)}건 승률 {(tdf['ret']>0).mean()*100:.0f}% 평균 {tdf['ret'].mean()*100:+.1f}%")
print("  [전 거래]")
for _, x in tdf.sort_values('ed').iterrows():
    print(f"    {x['ed']}→{x['xd']} {nm(x['t'])[:10]:12s} {x['ret']*100:+7.1f}%")
print("  [현재 보유 (원장 기준)]")
for t, info in port.items():
    p = pxat(t, days[-1])
    print(f"    {nm(t)[:10]:12s} {info['d']} 매수 {(p/info['px']-1)*100:+.1f}%")

# 현재룰 리플레이 동기간 (state 기반, X5+K10+브레드스) — 비교용
sys.path.insert(0, R)
from breadth_diagnostic import breadth_scale_by_date as _bsbd
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
CR = {}; dts = []
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    r = json.load(open(f, encoding='utf-8'))['rankings']
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in r}
    dts.append(dt)
dts = sorted(dts)
BRD = _bsbd(list(dts))
ma20 = k.rolling(20).mean(); ma80 = k.rolling(80).mean()
reg = {}; md = True; stk = 0; ss = None
for dd in dts:
    ts = pd.Timestamp(dd[:4] + '-' + dd[4:6] + '-' + dd[6:])
    if ts not in k.index or pd.isna(ma80.get(ts, np.nan)):
        reg[dd] = md; continue
    s = bool(ma20[ts] > ma80[ts]); stk = stk + 1 if s == ss else 1; ss = s
    if stk >= 5 and md != s: md = s
    reg[dd] = md
pcol = {c: i for i, c in enumerate(px.columns)}
parr = px.values
def pxv(t, d):
    return parr[tdi[d], pcol[t]] if (t in pcol and d in tdi) else None
port2 = {}; prev = None; d2 = []; last_exit = {}
for i, d0 in enumerate(dts):
    r_day = 0.0
    if port2 and prev:
        rr = [pxv(t, d0)/pxv(t, prev)-1 for t in port2 if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
        r_day = np.mean(rr) if rr else 0.0
    d2.append((d0, r_day * BRD.get(d0, 1.0)))
    if i < 2: prev = d0; continue
    if not reg.get(d0, True): port2 = {}; prev = d0; continue
    if reg.get(dts[i-1], True) != reg.get(d0, True): port2 = {}
    a0, a1, a2 = CR[d0], CR[dts[i-1]], CR[dts[i-2]]
    wr = lambda t: a0.get(t, 50)*0.4 + a1.get(t, 50)*0.35 + a2.get(t, 50)*0.25
    for t in list(port2.keys()):
        if wr(t) > 5: port2.pop(t); last_exit[t] = i
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    verified = sorted(t20(a0)&t20(a1)&t20(a2), key=lambda t: (wr(t), a0.get(t, 50)))
    for t in verified[:3]:
        if t in port2: continue
        if len(port2) >= 3: break
        if t in last_exit and i - last_exit[t] <= 10: continue
        p = pxv(t, d0)
        if p and p > 0: port2[t] = 1
    prev = d0
D2 = pd.DataFrame(d2, columns=['d', 'ret'])
D2 = D2[(D2['d'] >= days[0]) & (D2['d'] <= days[-1])]
eq2 = (1 + D2['ret']).cumprod()
mdd2 = (eq2/eq2.cummax()-1).min()*100
print(f"\n===== 비교: 현재룰(X5+쿨다운+SL제외) 리플레이 동기간 =====")
print(f"  누적: {(eq2.iloc[-1]-1)*100:+.1f}% / MDD {mdd2:.1f}%")
