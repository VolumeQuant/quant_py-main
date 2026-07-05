# -*- coding: utf-8 -*-
"""퀄리티(Q=0) 서브팩터 재활용 EDA — '선택'이 아니라 '상위권 내 차별화(비중/보유)' 축.
Q1: top65/top20/매수권 내에서 quality_s가 fwd 수익을 가르는가? (일별 rank IC + 코호트)
Q2: 다른 팩터 대비 상대적 크기는? (context)
Q3: 현재 score와의 직교성은? (겹치면 쓸모없음)
데이터: state ranking JSON의 quality_s/roe (필터가 쓴 그 값) + adj OHLCV fwd."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from scipy import stats as sps

R = 'C:/dev/claude-code/quant_py-main'
px = pd.read_parquet(R + '/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0, np.nan)
tdays = [d.strftime('%Y%m%d') for d in px.index]
tdi = {d: i for i, d in enumerate(tdays)}
parr = px.values
pcol = {c: i for i, c in enumerate(px.columns)}

rows = []
for f in sorted(glob.glob(R + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if not (dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi):
        continue
    i0 = tdi[dt]
    if i0 + 61 >= len(tdays):  # fwd60 확보
        i20ok = i0 + 21 < len(tdays)
        if not i20ok:
            continue
    d = json.load(open(f, encoding='utf-8'))['rankings']
    for x in d:
        t = x['ticker']
        if t not in pcol:
            continue
        p0 = parr[i0, pcol[t]]
        if not (p0 == p0 and p0 > 0):
            continue
        f20 = f60 = np.nan
        if i0 + 21 < len(tdays):
            p20 = parr[i0 + 21, pcol[t]]
            if p20 == p20 and p20 > 0: f20 = p20 / p0 - 1
        if i0 + 61 < len(tdays):
            p60 = parr[i0 + 61, pcol[t]]
            if p60 == p60 and p60 > 0: f60 = p60 / p0 - 1
        rows.append({'d': dt, 't': t, 'cr': x.get('composite_rank', 999),
                     'q': x.get('quality_s'), 'v': x.get('value_s'), 'g': x.get('growth_s'),
                     'm': x.get('momentum_s'), 'score': x.get('score'),
                     'roe': x.get('roe'), 'f20': f20, 'f60': f60})
df = pd.DataFrame(rows).dropna(subset=['q'])
print(f"표본: {len(df)}행, {df['d'].nunique()}일, 상위권 평균 {len(df)/df['d'].nunique():.0f}종목/일")

def daily_ic(sub, col, fwd):
    ics = []
    for d, g in sub.groupby('d'):
        g2 = g.dropna(subset=[col, fwd])
        if len(g2) >= 10 and g2[col].nunique() > 3:
            ic = sps.spearmanr(g2[col], g2[fwd]).statistic
            if ic == ic: ics.append(ic)
    ics = np.array(ics)
    if len(ics) == 0: return 0, 0, 0
    t = ics.mean() / (ics.std() / np.sqrt(len(ics))) if ics.std() > 0 else 0
    return ics.mean(), t, len(ics)

print("\n===== Q1/Q2: 상위권 內 일별 rank IC (fwd60) =====")
for scope, sub in [('top65 전체', df), ('top20', df[df['cr'] <= 20])]:
    print(f"  [{scope}]")
    for col, nm in [('q', '퀄리티'), ('roe', 'ROE(원값)'), ('v', '밸류'), ('g', '성장'), ('m', '모멘텀')]:
        s2 = sub.dropna(subset=[col])
        ic, t, n = daily_ic(s2, col, 'f60')
        sig = ' ★' if abs(t) > 3 else ''
        print(f"    {nm:10s} IC {ic:+.4f} (t={t:+.1f}, n={n}){sig}")

print("\n===== 매수권(cr≤3) 퀄리티 3분위 코호트 (fwd60) =====")
bz = df[(df['cr'] <= 3)].dropna(subset=['f60'])
bz = bz.copy()
# 일별이 아닌 전체 3분위 (일별론 3종목뿐이라 전체 pool)
terc = bz['q'].quantile([1/3, 2/3]).values
lo = bz[bz['q'] <= terc[0]]; mid = bz[(bz['q'] > terc[0]) & (bz['q'] <= terc[1])]; hi = bz[bz['q'] > terc[1]]
for nm, g in [('Q하위 1/3', lo), ('Q중위', mid), ('Q상위 1/3', hi)]:
    print(f"  {nm:10s}: n={len(g):5d}  fwd60 평균 {g['f60'].mean()*100:+.2f}%  중앙 {g['f60'].median()*100:+.2f}%  승률 {(g['f60']>0).mean()*100:.0f}%")

print("\n===== top20 內 퀄리티 5분위 (fwd60, 일별 z 아닌 pool) =====")
t20 = df[df['cr'] <= 20].dropna(subset=['f60']).copy()
t20['qq'] = pd.qcut(t20['q'], 5, labels=False, duplicates='drop')
for qq, g in t20.groupby('qq'):
    print(f"  Q{int(qq)+1}: fwd60 {g['f60'].mean()*100:+.2f}% / 승률 {(g['f60']>0).mean()*100:.0f}% (n={len(g)})")

print("\n===== Q3: 직교성 (top65 內) =====")
for col, nm in [('score', '멀티팩터 score'), ('g', '성장'), ('m', '모멘텀'), ('v', '밸류')]:
    c = df[['q', col]].dropna().corr(method='spearman').iloc[0, 1]
    print(f"  퀄리티 vs {nm:12s}: {c:+.3f}")
