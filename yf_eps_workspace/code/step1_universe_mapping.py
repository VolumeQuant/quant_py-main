"""YF Step 1 — kr_yf_deep_results.csv (488종목) × v80.6 5/13 ranking universe 매핑

목표:
  1. CSV ticker (`005930.KS`) → KR 6자리 (`005930`) 변환
  2. v80.6 production ranking (5/13)에서 교집합
  3. 시총/시장/분석가 수 분포
  4. cliff 영역 (KOSDAQ 5천억~1조) 카운트

읽기 전용 — production state 무변경
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from pathlib import Path

CSV = Path(r'C:/dev/claude code/eps-momentum-us/research/kr_yf_deep_results.csv')
PROD_RANK = Path(r'C:/dev/state/ranking_20260513.json')  # production (read-only)
OUT = Path(r'C:/dev/yf_eps_workspace/results')
OUT.mkdir(parents=True, exist_ok=True)

# 1. CSV 로드
df = pd.read_csv(CSV)
print(f'CSV: {df.shape[0]}종목')
df['ticker'] = df['symbol'].str.replace(r'\.K[SQ]$', '', regex=True)
print(f'  symbol → ticker 변환: {df["ticker"].head(3).tolist()}')

# 2. Production ranking 로드
with open(PROD_RANK, encoding='utf-8') as f:
    prod = json.load(f)
prod_tics = set(r['ticker'] for r in prod['rankings'])
prod_by_tic = {r['ticker']: r for r in prod['rankings']}
print(f'\nv80.6 production 5/13 ranking: {len(prod_tics)}종목')

# 3. 교집합
yf_tics = set(df['ticker'].tolist())
intersect = prod_tics & yf_tics
only_prod = prod_tics - yf_tics
only_yf = yf_tics - prod_tics
print(f'\n[교집합]')
print(f'  교집합:      {len(intersect)}')
print(f'  Prod만:      {len(only_prod)}')
print(f'  YF만:        {len(only_yf)} (production universe 밖)')

# 4. 교집합 종목 yf 가용성 breakdown
yf_intersect = df[df['ticker'].isin(intersect)].copy()
print(f'\n[교집합 {len(yf_intersect)}종목 yf 가용성]')
print(f'  fy_complete_0y: {yf_intersect["fy_complete_0y"].sum()} ({yf_intersect["fy_complete_0y"].mean()*100:.0f}%)')
print(f'  fy_complete_1y: {yf_intersect["fy_complete_1y"].sum()} ({yf_intersect["fy_complete_1y"].mean()*100:.0f}%)')
print(f'  rev_ok_0y:      {yf_intersect["rev_ok_0y"].sum()} ({yf_intersect["rev_ok_0y"].mean()*100:.0f}%)')
print(f'  na>=3:          {(yf_intersect["na"]>=3).sum()} ({(yf_intersect["na"]>=3).mean()*100:.0f}%)')
print(f'  na>=5:          {(yf_intersect["na"]>=5).sum()} ({(yf_intersect["na"]>=5).mean()*100:.0f}%)')

# 5. 시장별 분포
print(f'\n[시장별 분포 (교집합)]')
for mkt in ['KS', 'KQ']:
    s = yf_intersect[yf_intersect['market'] == mkt]
    if len(s) == 0: continue
    print(f'  {mkt}: {len(s)}종목')
    print(f'    fy_complete:  {s["fy_complete_0y"].sum()} ({s["fy_complete_0y"].mean()*100:.0f}%)')
    print(f'    na>=3:        {(s["na"]>=3).sum()} ({(s["na"]>=3).mean()*100:.0f}%)')
    print(f'    평균 na:      {s["na"].mean():.1f}')

# 6. 시총 cliff
print(f'\n[시총 분포 (교집합, mc_krw)]')
buckets = [(10e12, 'inf', '10조+'), (5e12, 10e12, '5~10조'),
           (1e12, 5e12, '1~5조'), (5e11, 1e12, '5천억~1조'),
           (0, 5e11, '5천억 미만')]
for low, hi, label in buckets:
    if hi == 'inf':
        s = yf_intersect[yf_intersect['mc_krw'] >= low]
    else:
        s = yf_intersect[(yf_intersect['mc_krw'] >= low) & (yf_intersect['mc_krw'] < hi)]
    if len(s) == 0:
        print(f'  {label:<10} : 0')
        continue
    fy = (s["fy_complete_0y"]).mean() * 100
    na3 = (s["na"] >= 3).mean() * 100
    print(f'  {label:<10} : {len(s):<4} | fy {fy:.0f}% | na>=3 {na3:.0f}%')

# 7. yf 가용 + production universe + na>=3 (US 룰 호환)
us_compat = yf_intersect[(yf_intersect['fy_complete_0y']) & (yf_intersect['na'] >= 3)]
us_min = yf_intersect[(yf_intersect['fy_complete_0y'])]
print(f'\n[옵션 C 보조 신호 적용 가능 종목]')
print(f'  US 룰 호환 (fy_complete + na>=3): {len(us_compat)} ({len(us_compat)/len(prod_tics)*100:.0f}% of prod {len(prod_tics)})')
print(f'  최소 가용 (fy_complete만):         {len(us_min)} ({len(us_min)/len(prod_tics)*100:.0f}%)')

# 8. Only prod 종목 — yf 가용 안 됨
print(f'\n[v80.6 universe 중 yf 미가용 {len(only_prod)}종목]')
print('  ticker  name')
for tic in sorted(only_prod)[:10]:
    r = prod_by_tic.get(tic, {})
    nm = r.get('name', '')
    print(f'  {tic} {nm[:15]}')
print(f'  ... (총 {len(only_prod)}종목)')

# 9. Top 어닝 비트 (intersect에서 상위 12개월 90d→current 상향)
print(f'\n[교집합 종목 어닝 비트 (0y_current - 0y_90d) / 0y_90d Top 15]')
ws = yf_intersect[yf_intersect['fy_complete_0y']].copy()
ws['beat'] = (ws['0y_current'] - ws['0y_90d']) / ws['0y_90d'].abs()
ws = ws[ws['beat'].notna()].sort_values('beat', ascending=False).head(15)
print('  ticker  name           market  mc(조)  beat%  na')
for _, r in ws.iterrows():
    nm = (r.get('name') or '')[:14]
    print(f'  {r["ticker"]:<7} {nm:<15} {r["market"]:<7} {r["mc_krw"]/1e12:<7.1f} {r["beat"]*100:<6.0f} {int(r["na"]) if pd.notna(r["na"]) else 0}')

# 10. 저장
yf_intersect.to_csv(OUT / 'step1_intersect.csv', index=False, encoding='utf-8-sig')
summary = {
    'csv_total': len(df),
    'prod_total': len(prod_tics),
    'intersect': len(intersect),
    'only_prod': len(only_prod),
    'only_yf': len(only_yf),
    'fy_complete_in_intersect': int(yf_intersect['fy_complete_0y'].sum()),
    'na3_in_intersect': int((yf_intersect['na'] >= 3).sum()),
    'us_compat_count': len(us_compat),
    'us_compat_pct_of_prod': round(len(us_compat) / len(prod_tics) * 100, 1),
    'min_avail_count': len(us_min),
    'min_avail_pct_of_prod': round(len(us_min) / len(prod_tics) * 100, 1),
}
with open(OUT / 'step1_summary.json', 'w', encoding='utf-8') as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f'\n저장: {OUT / "step1_intersect.csv"}, {OUT / "step1_summary.json"}')
