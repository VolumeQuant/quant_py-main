# -*- coding: utf-8 -*-
"""2018-07~현재 전체 매매내역 (production 시맨틱스, 현행 룰 X5+K10+브레드스) + 인사이트 분석.
CSV 저장: research/trades_full_2018_2026.csv
분석: 연도별/분포/집중도/보유기간/이탈사유/브레드스발동중 진입/연속손실/국면전환청산."""
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
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20180702' and dt in tdi):
        continue
    r = json.load(open(f, encoding='utf-8'))['rankings']
    CR[dt] = {x['ticker']: x.get('composite_rank', x.get('rank', 999)) for x in r}
    dts.append(dt)
dts = sorted(dts)
sys.path.insert(0, R)
from breadth_diagnostic import breadth_scale_by_date as _bsbd
try:
    BRD = _bsbd(list(dts))
except Exception:
    BRD = {}
reg = {}; md = False; stk = 0; ss = None   # 2018 시작 = 약세 가정 (7월 데드크로스권)
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
            trades.append({**info, 't': t, 'xd': d0, 'xp': p, 'why': '국면전환'})
        port = {}; prev = d0; continue
    if reg.get(dts[i - 1], True) != reg.get(d0, True):
        for t, info in port.items():
            p = pxv(t, d0)
            trades.append({**info, 't': t, 'xd': d0, 'xp': p, 'why': '국면전환'})
        port = {}
    a0, a1, a2 = CR[d0], CR[dts[i - 1]], CR[dts[i - 2]]
    wr = lambda t: a0.get(t, 50) * 0.4 + a1.get(t, 50) * 0.35 + a2.get(t, 50) * 0.25
    for t in list(port.keys()):
        if wr(t) > 5:
            info = port.pop(t); last_exit[t] = i
            p = pxv(t, d0)
            trades.append({**info, 't': t, 'xd': d0, 'xp': p, 'why': '순위이탈'})
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    verified = sorted(t20(a0) & t20(a1) & t20(a2), key=lambda t: (wr(t), a0.get(t, 50)))
    for t in verified[:3]:
        if t in port: continue
        if len(port) >= 3: break
        if t in last_exit and i - last_exit[t] <= 10: continue
        p = pxv(t, d0)
        if p and p > 0:
            gap = i - last_exit[t] if t in last_exit else 9999
            port[t] = {'ed': d0, 'ep': p, 'brd_at_entry': BRD.get(d0, 1.0),
                       'reentry_gap': gap, 'entry_wr': round(wr(t), 1)}
    prev = d0

df = pd.DataFrame(trades)
df['ret'] = df.apply(lambda r: r['xp'] / r['ep'] - 1 if (r['xp'] and r['ep']) else np.nan, axis=1)
df = df.dropna(subset=['ret']).copy()
df['name'] = df['t'].map(nm)
df['hold_d'] = (pd.to_datetime(df['xd']) - pd.to_datetime(df['ed'])).dt.days
df['yr'] = df['xd'].str[:4]
df = df.sort_values('ed').reset_index(drop=True)
out = df[['ed', 'xd', 'name', 't', 'hold_d', 'ep', 'xp', 'ret', 'why', 'brd_at_entry', 'reentry_gap', 'entry_wr']]
out.to_csv(R + '/research/trades_full_2018_2026.csv', index=False, encoding='utf-8-sig')
print(f"전체 거래 {len(df)}건 → research/trades_full_2018_2026.csv 저장")

# 미청산 보유
print("\n[현재 보유 (미청산)]")
last_d = dts[-1]
for t, info in port.items():
    p = pxv(t, last_d)
    r = p / info['ep'] - 1 if p else None
    print(f"  {nm(t)}: {info['ed']} 매수 @{info['ep']:,.0f} → {p:,.0f} ({r*100:+.1f}%)")

print("\n===== 연도별 =====")
print(f"{'년':6s}{'건수':>5s}{'승률':>6s}{'평균':>8s}{'중앙':>8s}{'합계':>9s}{'최악':>8s}")
for y, g in df.groupby('yr'):
    print(f"{y:6s}{len(g):>5d}{(g['ret']>0).mean()*100:>5.0f}%{g['ret'].mean()*100:>+7.1f}%{g['ret'].median()*100:>+7.1f}%{g['ret'].sum()*100:>+8.0f}%p{g['ret'].min()*100:>+7.1f}%")

print("\n===== 전체 분포 =====")
r = df['ret']
print(f"  n={len(r)} 승률 {(r>0).mean()*100:.0f}% 평균 {r.mean()*100:+.2f}% 중앙 {r.median()*100:+.2f}%")
print(f"  분위: 5% {r.quantile(0.05)*100:+.1f} / 25% {r.quantile(0.25)*100:+.1f} / 75% {r.quantile(0.75)*100:+.1f} / 95% {r.quantile(0.95)*100:+.1f}")
pos = r[r > 0].sum()
top5 = r.nlargest(max(1, len(r)//20)).sum()
top10 = r.nlargest(max(1, len(r)//10)).sum()
print(f"  수익 집중: 상위 5% 거래가 총이익의 {top5/pos*100:.0f}%, 상위 10%가 {top10/pos*100:.0f}%")
print(f"  손익비: 승평균 {r[r>0].mean()*100:+.1f}% / 패평균 {r[r<=0].mean()*100:+.1f}% = {abs(r[r>0].mean()/r[r<=0].mean()):.2f}")

print("\n===== 보유기간 버킷 =====")
for lo, hi, lbl in [(0, 3, '1~3일'), (4, 7, '4~7일'), (8, 15, '8~15일'), (16, 40, '16~40일'), (41, 120, '41~120일'), (121, 9999, '121일+')]:
    g = df[(df['hold_d'] >= lo) & (df['hold_d'] <= hi)]
    if len(g):
        print(f"  {lbl:9s}: {len(g):3d}건 승률 {(g['ret']>0).mean()*100:3.0f}% 평균 {g['ret'].mean()*100:+7.2f}% 합계 {g['ret'].sum()*100:+8.0f}%p")

print("\n===== 이탈 사유 =====")
for w, g in df.groupby('why'):
    print(f"  {w}: {len(g)}건 평균 {g['ret'].mean()*100:+.2f}% 합계 {g['ret'].sum()*100:+.0f}%p")

print("\n===== 브레드스 발동 중 진입 vs 평시 진입 =====")
for cond, lbl in [(df['brd_at_entry'] < 1.0, '발동중(50%축소) 진입'), (df['brd_at_entry'] >= 1.0, '평시 진입')]:
    g = df[cond]
    if len(g):
        print(f"  {lbl:18s}: {len(g):3d}건 승률 {(g['ret']>0).mean()*100:3.0f}% 평균 {g['ret'].mean()*100:+7.2f}% 중앙 {g['ret'].median()*100:+6.2f}%")

print("\n===== 국면전환 청산 이벤트 =====")
rg = df[df['why'] == '국면전환']
print(f"  {len(rg)}건 평균 {rg['ret'].mean()*100:+.2f}%")
for _, x in rg.iterrows():
    print(f"    {x['ed']}→{x['xd']} {x['name'][:10]:12s} {x['ret']*100:+7.1f}%")

print("\n===== 최고/최악 거래 TOP7 =====")
for _, x in df.nlargest(7, 'ret').iterrows():
    print(f"  🏆 {x['ed']}→{x['xd']} {x['name'][:10]:12s} {x['hold_d']:>4d}일 {x['ret']*100:+8.1f}%")
for _, x in df.nsmallest(7, 'ret').iterrows():
    print(f"  💀 {x['ed']}→{x['xd']} {x['name'][:10]:12s} {x['hold_d']:>4d}일 {x['ret']*100:+8.1f}%")

print("\n===== 연속 손실 스트릭 =====")
seq = (df.sort_values('xd')['ret'] <= 0).astype(int).values
best = cur = 0
for v in seq:
    cur = cur + 1 if v else 0
    best = max(best, cur)
print(f"  최장 연속 손실: {best}건")
# 진입 wr별
print("\n===== 진입 시점 wr별 =====")
for lo, hi, lbl in [(0, 1.5, 'wr≤1.5'), (1.5, 2.5, '1.5~2.5'), (2.5, 3.5, '2.5~3.5'), (3.5, 99, '3.5+')]:
    g = df[(df['entry_wr'] > lo) & (df['entry_wr'] <= hi)]
    if len(g):
        print(f"  {lbl:9s}: {len(g):3d}건 승률 {(g['ret']>0).mean()*100:3.0f}% 평균 {g['ret'].mean()*100:+7.2f}%")
