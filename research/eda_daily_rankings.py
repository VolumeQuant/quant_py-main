# -*- coding: utf-8 -*-
"""일자별 boost 랭킹 파일 EDA (2026). state/ranking_YYYYMMDD.json."""
import sys, io, glob, json, os
from collections import defaultdict, Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd

files = sorted(glob.glob('state/ranking_2026*.json'))
recs = []
for f in files:
    d = json.load(open(f, encoding='utf-8'))
    date = d['date']
    r = sorted(d['rankings'], key=lambda x: (x['weighted_rank'], x['composite_rank']))
    for i, x in enumerate(r, 1):
        recs.append(dict(date=date, pos=i, ticker=x['ticker'], name=x['name'],
            sector=x['sector'], wr=x['weighted_rank'], score=x.get('score'),
            V=x.get('value_s'), Q=x.get('quality_s'), G=x.get('growth_s'), M=x.get('momentum_s'),
            per=x.get('per'), pbr=x.get('pbr')))
df = pd.DataFrame(recs)
dates = sorted(df.date.unique())
print(f'기간: {dates[0]} ~ {dates[-1]} ({len(dates)}일), 일평균 {df.groupby("date").size().mean():.0f}종목')

# 1. Top3 / Top20 회전율
print('\n=== 1. 진입권(Top3) 회전율 ===')
top3 = {dt: set(df[(df.date==dt)&(df.pos<=3)].ticker) for dt in dates}
top20 = {dt: set(df[(df.date==dt)&(df.pos<=20)].ticker) for dt in dates}
ch3 = [len(top3[dates[i]]-top3[dates[i-1]]) for i in range(1,len(dates))]
ch20 = [len(top20[dates[i]]-top20[dates[i-1]]) for i in range(1,len(dates))]
print(f'Top3 일평균 교체: {sum(ch3)/len(ch3):.2f}종목/일 (0=그대로). 변동 없는 날 {ch3.count(0)}/{len(ch3)}일')
print(f'Top20 일평균 교체: {sum(ch20)/len(ch20):.2f}종목/일')

# 2. 진입권 체류 (Top3에 며칠 등장)
print('\n=== 2. Top3 누적 등장일수 (올해 진입권 단골) ===')
c3 = Counter()
for dt in dates: c3.update(top3[dt])
nm = df.drop_duplicates('ticker').set_index('ticker')['name'].to_dict()
for t,c in c3.most_common(12): print(f'  {nm[t]:<12}({t}) {c}일')

# 3. Top20 체류
print('\n=== 3. Top20 누적 등장일수 ===')
c20 = Counter()
for dt in dates: c20.update(top20[dt])
for t,c in c20.most_common(15): print(f'  {nm[t]:<12}({t}) {c}일 ({100*c/len(dates):.0f}%)')

# 4. 섹터 구성 추이 (월별 Top20)
print('\n=== 4. 월별 Top20 섹터 구성 ===')
df['mon'] = df.date.str[:6]
for mon in sorted(df.mon.unique()):
    sub = df[(df.mon==mon)&(df.pos<=20)]
    sc = sub.sector.value_counts(normalize=True)
    top = ' '.join(f'{s}{100*v:.0f}%' for s,v in sc.head(4).items())
    print(f'  {mon}: {top}')

# 5. 1등 score 추이 (월별)
print('\n=== 5. 1등 멀티팩터 score 추이 (강도) ===')
for mon in sorted(df.mon.unique()):
    sub = df[(df.mon==mon)&(df.pos==1)]
    print(f'  {mon}: 1등 score 평균 {sub.score.mean():.2f} (min {sub.score.min():.2f} max {sub.score.max():.2f})')

# 6. 진입권 팩터 성향 (Top3의 V/Q/G/M 평균)
print('\n=== 6. 진입권(Top3) 팩터 성향 — 월별 ===')
for mon in sorted(df.mon.unique()):
    sub = df[(df.mon==mon)&(df.pos<=3)]
    print(f'  {mon}: V{sub.V.mean():+.2f} Q{sub.Q.mean():+.2f} G{sub.G.mean():+.2f} M{sub.M.mean():+.2f} | PER평균 {sub.per.mean():.0f} PBR {sub.pbr.mean():.1f}')

# 7. 최근 20일 Top3 궤적
print('\n=== 7. 최근 15일 진입권(Top3) 종목 ===')
for dt in dates[-15:]:
    t3 = df[(df.date==dt)&(df.pos<=3)].sort_values('pos')
    print(f'  {dt}: ' + ' / '.join(f'{r["name"]}' for _,r in t3.iterrows()))
