# -*- coding: utf-8 -*-
"""EDA M1 — 브레드스 발동 에피소드 원장 (에피소드별 50% 스케일이 벌었나 잃었나)
+ M7 월별 수익 히트맵/요일 (기대관리용 descriptive, 매매 함의 없음)."""
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

# production 시맨틱스 리플레이 — raw 수익(스케일 전) 시리즈
port = {}; prev = None; rows = []; last_exit = {}
for i, d0 in enumerate(dts):
    r_raw = 0.0
    if port and prev:
        rr = [pxv(t, d0)/pxv(t, prev)-1 for t in port if pxv(t, prev) and pxv(t, d0) and pxv(t, prev)>0 and pxv(t, d0)>0]
        r_raw = np.mean(rr) if rr else 0.0
    rows.append([d0, r_raw, BRD.get(d0, 1.0), reg.get(d0, True)])
    if i < 2: prev = d0; continue
    if not reg.get(d0, True): port = {}; prev = d0; continue
    if reg.get(dts[i-1], True) != reg.get(d0, True): port = {}
    a0, a1, a2 = CR[d0], CR[dts[i-1]], CR[dts[i-2]]
    wr = lambda t: a0.get(t,50)*0.4 + a1.get(t,50)*0.35 + a2.get(t,50)*0.25
    for t in list(port.keys()):
        if wr(t) > 5: port.pop(t); last_exit[t] = i
    t20 = lambda a: {t for t, r in a.items() if r <= 20}
    verified = sorted(t20(a0)&t20(a1)&t20(a2), key=lambda t: (wr(t), a0.get(t,50)))
    for t in verified[:3]:
        if t in port: continue
        if len(port) >= 3: break
        if t in last_exit and i - last_exit[t] <= 10: continue
        p = pxv(t, d0)
        if p and p > 0: port[t] = 1
    prev = d0

D = pd.DataFrame(rows, columns=['d', 'raw', 'brd', 'boost'])
CASH_D = 0.03/252

# ===== M1: 브레드스 에피소드 원장 =====
print("===== M1. 브레드스 발동 에피소드 원장 =====")
D['fire'] = (D['brd'] < 1.0) & D['boost']
epis = []
cur = None
for i, r in D.iterrows():
    if r['fire']:
        if cur is None: cur = [i, i]
        else: cur[1] = i
    else:
        if cur: epis.append(tuple(cur)); cur = None
if cur: epis.append(tuple(cur))
print(f"발동 에피소드 {len(epis)}건, 총 {int(D['fire'].sum())}일")
print(f"{'시작':>10s} {'끝':>10s} {'일수':>4s} {'그동안 raw수익':>12s} {'50%스케일 효과':>12s} {'판정':6s}")
tot_save = 0
good = 0
for st, en in epis:
    seg = D.iloc[st:en+1]
    raw_cum = (1 + seg['raw']).prod() - 1
    # 스케일 효과 = (0.5raw+0.5cash 누적) - raw 누적
    half = (1 + 0.5*seg['raw'] + 0.5*CASH_D).prod() - 1
    eff = half - raw_cum
    tot_save += eff
    v = '✅방어' if eff > 0 else '❌비용'
    if eff > 0: good += 1
    print(f"{seg['d'].iloc[0]:>10s} {seg['d'].iloc[-1]:>10s} {len(seg):>4d} {raw_cum*100:>+11.1f}% {eff*100:>+11.1f}%p {v}")
print(f"\n합계: {len(epis)}건 중 방어성공 {good}건 ({good/len(epis)*100:.0f}%), 누적 효과 {tot_save*100:+.1f}%p (단순합)")

# ===== M7: 월별 수익 (스케일 포함 실제) =====
print("\n===== M7. 월별 수익률 (실제 시스템, %) — 기대관리용 =====")
D['ret'] = np.where(D['boost'] & (D['brd'] < 1), 0.5*D['raw'] + 0.5*CASH_D, D['raw'])
D['ym'] = D['d'].str[:6]
mret = D.groupby('ym')['ret'].apply(lambda x: ((1+x).prod()-1)*100)
mm = mret.reset_index()
mm['y'] = mm['ym'].str[:4]; mm['m'] = mm['ym'].str[4:]
pv = mm.pivot(index='y', columns='m', values='ret')
print(pv.round(0).fillna('').to_string())
mon_avg = mm.groupby('m')['ret'].agg(['mean', lambda x: (x>0).mean()*100])
mon_avg.columns = ['평균%', '양수비율%']
print("\n[월별 평균 (7.4년)] ※ 표본 7~8개/월 = 통계적 의미 약함, 매매 함의 없음")
print(mon_avg.round(1).to_string())
neg_months = (mret < 0).mean()*100
print(f"\n월 단위 손실 확률: {neg_months:.0f}% (월 {len(mret)}개 중 {(mret<0).sum()}개 마이너스)")
print(f"최악의 달: {mret.idxmin()} ({mret.min():.1f}%) / 최고의 달: {mret.idxmax()} (+{mret.max():.1f}%)")
