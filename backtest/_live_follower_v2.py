# -*- coding: utf-8 -*-
"""팔로워 원장 v2 — 진입: 당시 발송 picks / 청산: 당시 룰의 wr 기준선(state 저장 wr 사용).
시대별 이탈: ~0524 X6 / 0525~0607 X4 / 0608~0703 X6 / 0704~ X5(+SL-15%).
= '그때 그 신호'를 충실히 따른 사람의 실제 경험."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

R = 'C:/dev/claude-code/quant_py-main'
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
WR = {}
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20260201'):
        continue
    try:
        d = json.load(open(f, encoding='utf-8'))['rankings']
        WR[dt] = {x['ticker']: x.get('weighted_rank', 99) for x in d}
    except Exception:
        continue
days = sorted(picks)

def era_exit(d):
    if d < '20260525': return 6, None
    if d < '20260608': return 4, None
    if d < '20260704': return 6, None
    return 5, -0.15

def pxat(t, d):
    try:
        s = px[t].loc[:pd.Timestamp(d)].dropna()
        return float(s.iloc[-1]) if len(s) else None
    except Exception:
        return None

port = {}; trades = []; daily = []
for i, d0 in enumerate(days):
    if i >= 1 and port:
        rr = []
        for t in port:
            p0 = pxat(t, days[i-1]); p1 = pxat(t, d0)
            if p0 and p1 and p0 > 0: rr.append(p1/p0 - 1)
        daily.append((d0, np.mean(rr) if rr else 0.0, len(port)))
    else:
        daily.append((d0, 0.0, len(port)))
    X, SL = era_exit(d0)
    wrm = WR.get(d0, {})
    for t in list(port):
        w = wrm.get(t, 99)
        p = pxat(t, d0)
        sl_hit = SL is not None and p and port[t]['px'] and (p/port[t]['px'] - 1) <= SL
        if w > X or sl_hit:
            trades.append({'t': t, 'ed': port[t]['d'], 'xd': d0,
                           'ret': p/port[t]['px'] - 1 if (p and port[t]['px']) else np.nan,
                           'why': 'SL' if sl_hit and w <= X else f'wr>{X}'})
            port.pop(t)
    for t in picks[d0]:
        if t not in port:
            p = pxat(t, d0)
            if p and p > 0: port[t] = {'d': d0, 'px': p}

D = pd.DataFrame(daily, columns=['d', 'ret', 'n'])
eq = (1 + D['ret']).cumprod()
mdd = (eq/eq.cummax() - 1).min()*100
kk = k[(k.index >= days[0]) & (k.index <= days[-1])]
print(f"===== 팔로워 원장 v2 ({days[0]}~{days[-1]}) — 당시 신호+당시 이탈룰 =====")
print(f"  누적 {(eq.iloc[-1]-1)*100:+.1f}% / MDD {mdd:.1f}% / 평균 보유 {D['n'].mean():.1f}종목 (최대 {D['n'].max()})")
print(f"  KOSPI 동기간 {(kk.iloc[-1]/kk.iloc[0]-1)*100:+.1f}%")
tdf = pd.DataFrame(trades).dropna(subset=['ret'])
print(f"  청산 {len(tdf)}건 승률 {(tdf['ret']>0).mean()*100:.0f}% 평균 {tdf['ret'].mean()*100:+.1f}% 합 {tdf['ret'].sum()*100:+.0f}%p")
w5 = tdf.nsmallest(5, 'ret'); b5 = tdf.nlargest(5, 'ret')
print("  최악:", ' / '.join(f"{nm(x['t'])[:6]}{x['ret']*100:+.0f}%" for _, x in w5.iterrows()))
print("  최고:", ' / '.join(f"{nm(x['t'])[:6]}{x['ret']*100:+.0f}%" for _, x in b5.iterrows()))
print("  현재 보유:", ', '.join(f"{nm(t)[:6]}({(pxat(t,days[-1])/port[t]['px']-1)*100:+.0f}%)" for t in port))
# 월별
D['ym'] = D['d'].str[:6]
print("\n  [월별]")
for ym, g in D.groupby('ym'):
    print(f"    {ym}: {((1+g['ret']).prod()-1)*100:+.1f}%")
