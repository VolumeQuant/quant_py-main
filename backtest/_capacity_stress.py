# -*- coding: utf-8 -*-
"""용량(capacity) 스트레스 테스트 — 퀀트 sleeve 규모별 알파 감소 곡선.
질문: 자본이 5억→18억으로 커질 때(퀀트 35% = 1.75억→6.3억) 이 전략이 버티는가?

방법:
1) 현행 룰(X5+K10, production 시맨틱스) 리플레이 → 전체 매매(진입+청산) 추출
2) 각 매매일의 종목 ADV20(직전 20거래일 평균 거래대금) 대비 주문 참여율 p = (sleeve/3) / ADV20
3) 시장충격 모델: 편도 비용 ≈ k·σ_da일·√p (square-root impact, k=1 보수적)
   + 참여율 10% 초과분은 체결 자체가 며칠 걸림(추가 위험)
4) sleeve 규모별: 참여율 분포 / 연간 슬리피지 드래그 / 보정 CAGR"""
import sys, os, glob, json
import numpy as np, pandas as pd
from pathlib import Path

R = Path('C:/dev/claude-code/quant_py-main')
px = pd.read_parquet(R / 'data_cache' / 'all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)
vol = pd.read_parquet(R / 'data_cache' / 'all_volume_20150331_20260622.parquet').replace(0, np.nan)
# ★all_volume 파일은 이미 거래대금(원) — 가격 곱하지 않음 (표본검증: 삼성전자 5.9조/일)
val = vol
adv20 = val.rolling(20, min_periods=10).mean()
ret_d = px.pct_change(fill_method=None)
sig20 = ret_d.rolling(20, min_periods=10).std()

pcol = {c: i for i, c in enumerate(px.columns)}
parr = px.values
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
kc = pd.read_parquet(R / 'data_cache' / 'kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
CR = {}; dts = []
for f in sorted(glob.glob(str(R / 'state' / 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    r = json.load(open(f, encoding='utf-8'))['rankings']
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in r}
    dts.append(dt)
dts = sorted(dts)
sys.path.insert(0, str(R))
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

# 리플레이 (E3 X5 S3 K10) — 매매 이벤트 수집
E, X, S, K = 3, 5, 3, 10
port = {}; prev = None; daily = []; events = []; last_exit = {}
for i, d0 in enumerate(dts):
    avg = 0.0
    if port and prev:
        rr = [pxv(t, d0) / pxv(t, prev) - 1 for t in port
              if pxv(t, prev) and pxv(t, d0) and pxv(t, prev) > 0 and pxv(t, d0) > 0]
        avg = np.mean(rr) if rr else 0.0
    daily.append((d0, avg * BRD.get(d0, 1.0)))
    if i < 2:
        prev = d0; continue
    if not reg.get(d0, True):
        for t in port: events.append((d0, t, 'sell'))
        port = {}; prev = d0; continue
    if reg.get(dts[i - 1], True) != reg.get(d0, True):
        for t in port: events.append((d0, t, 'sell'))
        port = {}
    a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
    wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
    for t in list(port.keys()):
        if wr(t) > X:
            port.pop(t); last_exit[t] = i; events.append((d0, t, 'sell'))
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    for t in sorted(t20(a0) & t20(a1) & t20(a2), key=wr):
        if len(port) >= S: break
        if t in port or wr(t) > E: continue
        if t in last_exit and i - last_exit[t] <= K: continue
        port[t] = 1; events.append((d0, t, 'buy'))
    prev = d0

print(f"매매 이벤트: {len(events)}건 (진입 {sum(1 for e in events if e[2]=='buy')} / 청산 {sum(1 for e in events if e[2]=='sell')})")

# 이벤트별 ADV20·σ 수집
ev = []
for d, t, side in events:
    ts = pd.Timestamp(d)
    if t not in adv20.columns: continue
    try:
        a_series = adv20[t].loc[:ts]
        a = a_series.iloc[-2] if len(a_series) >= 2 else np.nan  # 전일까지 ADV (당일 제외)
        sg = sig20[t].loc[:ts].iloc[-2] if len(sig20[t].loc[:ts]) >= 2 else np.nan
    except Exception:
        continue
    if a == a and a > 0 and sg == sg:
        ev.append({'d': d, 't': t, 'side': side, 'adv': a, 'sig': sg})
ev = pd.DataFrame(ev)
print(f"ADV 매칭: {len(ev)}건, ADV20 중앙값 {ev['adv'].median()/1e8:.0f}억 / 10분위 {ev['adv'].quantile(0.1)/1e8:.0f}억")

# baseline 수익률
a = np.array([r for _, r in daily])
eq = np.cumprod(1 + a)
years = len(a) / 252
base_cagr = (eq[-1] ** (1 / years) - 1) * 100

print(f"\nbaseline CAGR {base_cagr:.1f}% (비용 전)")
print(f"\n{'sleeve':>8s} {'포지션':>7s} {'참여율중앙':>9s} {'p>10%':>7s} {'p>25%':>7s} {'연드래그':>8s} {'보정CAGR':>9s}")
K_IMPACT = 1.0
for sleeve_uk in [0.5, 1.0, 1.75, 3.0, 6.3, 10.0, 20.0]:
    pos = sleeve_uk * 1e8 / 3
    p = (pos / ev['adv']).clip(upper=3.0)
    cost = K_IMPACT * ev['sig'] * np.sqrt(p)          # 편도 충격 (비율)
    cost = np.minimum(cost, 0.10)                       # 상한 10% (극단 방지)
    # 포트 임팩트: 각 이벤트 비용 × (1/3 슬롯 비중), 연간화
    total_drag = (cost.sum() / 3) / years * 100         # %p per year
    over10 = (p > 0.10).mean() * 100
    over25 = (p > 0.25).mean() * 100
    adj = base_cagr - total_drag
    print(f"{sleeve_uk:>7.2f}억 {pos/1e8:>6.2f}억 {p.median()*100:>8.1f}% {over10:>6.0f}% {over25:>6.0f}% {total_drag:>7.1f}%p {adj:>8.1f}%")

# 어느 종목 유형에서 걸리나 — sleeve 6.3억 기준 참여율 상위
print("\n[sleeve 6.3억 기준 참여율 상위 10 이벤트 — 어떤 종목이 병목인가]")
ev2 = ev.copy(); ev2['p'] = (6.3e8 / 3) / ev2['adv']
try:
    NAMES = json.load(open(R / 'data_cache' / 'ticker_names_cache.json', encoding='utf-8'))
except Exception:
    NAMES = {}
for _, r in ev2.nlargest(10, 'p').iterrows():
    n = NAMES.get(r['t'], r['t'])
    n = n if isinstance(n, str) else r['t']
    print(f"  {r['d']} {n[:10]:12s} {r['side']:4s} ADV20 {r['adv']/1e8:6.1f}억 → 참여율 {r['p']*100:5.0f}%")
# 연도별 병목 추이 (최근일수록 대형주?)
ev2['yr'] = ev2['d'].str[:4]
print("\n[연도별 ADV20 중앙값 (매매 종목의 유동성 추이)]")
for y, g in ev2.groupby('yr'):
    print(f"  {y}: 중앙 {g['adv'].median()/1e8:6.0f}억 / 최소 {g['adv'].min()/1e8:5.1f}억 (n={len(g)})")
