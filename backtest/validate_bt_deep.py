"""BT 파일 심화 분석
1. BT 날짜 분포 (요일, 월별)
2. 종목수 시계열 (언제 많고 언제 적은지)
3. G 서브팩터 0 비율 심화 (특정 날짜? 특정 종목?)
4. 랭킹 상위에도 0이 많은지
"""
import sys, os, json, glob
from pathlib import Path
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np

BT_EXT = Path('C:/dev/backtest/bt_extended')

files = sorted(BT_EXT.glob('ranking_*.json'))
print(f'파일 총: {len(files)}\n')

# 1. 날짜 분포
dates = [fp.stem.replace('ranking_', '') for fp in files]
ts = pd.to_datetime(dates, format='%Y%m%d')
dow_count = Counter(ts.day_name())
print('=== 요일 분포 ===')
for d in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']:
    print(f'  {d}: {dow_count.get(d,0)}')

# 월별 파일 수
print('\n=== 월별 파일 수 (2018-07부터) ===')
monthly = Counter(ts.strftime('%Y-%m'))
for m in sorted(monthly)[:12]:
    print(f'  {m}: {monthly[m]}')
print('  ...')
for m in sorted(monthly)[-6:]:
    print(f'  {m}: {monthly[m]}')

# 2. 종목수 시계열
n_list = []
rev_z_zero_ratio = []
score_top5 = []
for fp in files:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    r = d['rankings']
    n = len(r)
    n_list.append(n)
    if n > 0:
        rev_zero = sum(1 for x in r if x.get('rev_z', 0) == 0)
        rev_z_zero_ratio.append(rev_zero / n)
        score_top5.append(np.mean([x['score'] for x in r[:5]]) if n >= 5 else np.nan)
    else:
        rev_z_zero_ratio.append(1.0); score_top5.append(np.nan)

df = pd.DataFrame({
    'date': dates, 'n': n_list,
    'rev_z_zero_ratio': rev_z_zero_ratio, 'top5_score': score_top5,
})
df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
df['year'] = df['date'].dt.year

# 3. 연도별 통계
print('\n=== 연도별 통계 ===')
print(df.groupby('year').agg(
    n_files=('n', 'count'),
    n_stocks_mean=('n', 'mean'),
    n_stocks_min=('n', 'min'),
    n_stocks_max=('n', 'max'),
    rev_zero_pct=('rev_z_zero_ratio', 'mean'),
    top5_score=('top5_score', 'mean'),
).round(2).to_string())

# 4. 종목수 < 30인 파일 샘플 (극단)
low = df[df['n'] < 30].sort_values('n').head(10)
print(f'\n=== 종목수 < 30 파일 (극단 case) ===')
print(low[['date', 'n']].to_string(index=False))

# 5. rev_z 0 비율 > 50% 파일 샘플
high_zero = df[df['rev_z_zero_ratio'] > 0.5].sort_values('rev_z_zero_ratio', ascending=False).head(10)
print(f'\n=== rev_z 0 비율 > 50% 파일 샘플 ===')
print(high_zero[['date', 'n', 'rev_z_zero_ratio']].round(3).to_string(index=False))

# 6. 최근 30일 상세
print(f'\n=== 최근 30개 파일 ===')
print(df.tail(30)[['date', 'n', 'rev_z_zero_ratio', 'top5_score']].round(3).to_string(index=False))

# 7. 랭킹 Top 10에 rev_z=0인 종목 있는지 (신호 훼손)
print(f'\n=== Top 10에 rev_z=0 포함된 날짜 샘플 ===')
corrupted_days = []
for fp in files:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    r = d['rankings'][:10]
    zero_top = [x['ticker'] for x in r if x.get('rev_z', 0) == 0]
    if zero_top:
        corrupted_days.append((fp.stem.replace('ranking_',''), len(zero_top), zero_top[:3]))
print(f'  총 {len(corrupted_days)}/{len(files)} 파일 = {len(corrupted_days)*100//len(files)}%')
for dt, n, ts_ in corrupted_days[:10]:
    print(f'  {dt}: {n}개 rev_z=0 (samples {ts_})')

# 8. rev_z == 0인 종목의 다른 필드는?
print(f'\n=== rev_z=0 종목의 값 샘플 (최근 파일) ===')
with open(files[-1], 'r', encoding='utf-8') as f:
    d = json.load(f)
zero_recs = [x for x in d['rankings'] if x.get('rev_z', 0) == 0][:5]
for x in zero_recs:
    print(f'  rank={x["rank"]} ticker={x["ticker"]} name={x["name"]} score={x["score"]:.3f}')
    print(f'    rev_z={x.get("rev_z")} oca_z={x.get("oca_z")} rev_accel_z={x.get("rev_accel_z")} '
          f'gp_growth_z={x.get("gp_growth_z")} op_margin_z={x.get("op_margin_z")}')
