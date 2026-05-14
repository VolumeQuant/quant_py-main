"""Step 3 결과 분석 — 시총 cliff 정밀 + v80.6 universe 매핑"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from pathlib import Path

US = Path(r'C:/dev/claude code/eps-momentum-us/research/kr_yf_deep_results.csv')
EXT = Path(r'C:/dev/yf_eps_workspace/results/kr_yf_extension_results.csv')
PROD_RANK = Path(r'C:/dev/state/ranking_20260513.json')  # read-only
OUT = Path(r'C:/dev/yf_eps_workspace/results')

# 1. US + Extension 통합
us = pd.read_csv(US, dtype={'symbol': str})
us['ticker'] = us['symbol'].str.replace(r'\.K[SQ]$', '', regex=True).str.zfill(6)
us['source'] = 'US (5천억+)'
ext = pd.read_csv(EXT, dtype={'symbol': str})
ext['ticker'] = ext['symbol'].str.replace(r'\.K[SQ]$', '', regex=True).str.zfill(6)
ext['source'] = 'Ext (1천억~5천억)'

# 컬럼 정렬
common_cols = [c for c in us.columns if c in ext.columns]
all_df = pd.concat([us[common_cols], ext[common_cols]], ignore_index=True)
print(f'통합 universe: {len(all_df)}종목 (US {len(us)} + Ext {len(ext)})')

# 2. 시총 cliff (전체 universe 시총별 가용성)
print(f'\n[전체 시총별 가용성]')
buckets = [(1e13, None, '10조+'), (5e12, 1e13, '5~10조'),
           (1e12, 5e12, '1~5조'), (5e11, 1e12, '5천억~1조'),
           (3e11, 5e11, '3~5천억'), (2e11, 3e11, '2~3천억'),
           (1e11, 2e11, '1~2천억')]
print(f'  {"시총":<10} {"종목":<6} {"et_ok":<10} {"fy_0y":<10} {"rev_ok":<10} {"na>=3":<10} {"na>=5":<10}')
print('  ' + '-' * 78)
for low, hi, label in buckets:
    if hi: s = all_df[(all_df.mc_krw >= low) & (all_df.mc_krw < hi)]
    else: s = all_df[all_df.mc_krw >= low]
    n = len(s)
    if n == 0:
        print(f'  {label:<10} 0')
        continue
    et = s['eps_trend_ok'].sum()
    fy = s['fy_complete_0y'].sum()
    rv = s['rev_ok_0y'].sum()
    na3 = (s['na'] >= 3).sum()
    na5 = (s['na'] >= 5).sum()
    print(f'  {label:<10} {n:<6} {et}({et/n*100:.0f}%)   {fy}({fy/n*100:.0f}%)   {rv}({rv/n*100:.0f}%)   {na3}({na3/n*100:.0f}%)   {na5}({na5/n*100:.0f}%)')

# 3. v80.6 production universe 매핑
with open(PROD_RANK, encoding='utf-8') as f:
    prod = json.load(f)
prod_tics = set(r['ticker'] for r in prod['rankings'])
prod_by_tic = {r['ticker']: r for r in prod['rankings']}

intersect = set(all_df['ticker']) & prod_tics
intersect_df = all_df[all_df['ticker'].isin(intersect)].copy()
print(f'\n[v80.6 production 5/13 ranking (299종목) × 통합 universe]')
print(f'  교집합: {len(intersect)}/{len(prod_tics)} ({len(intersect)/len(prod_tics)*100:.0f}%)')
print(f'  교집합 내 et_ok:   {intersect_df["eps_trend_ok"].sum()} ({intersect_df["eps_trend_ok"].mean()*100:.0f}%)')
print(f'  교집합 내 fy_0y:   {intersect_df["fy_complete_0y"].sum()} ({intersect_df["fy_complete_0y"].mean()*100:.0f}%)')
print(f'  교집합 내 rev_ok:  {intersect_df["rev_ok_0y"].sum()} ({intersect_df["rev_ok_0y"].mean()*100:.0f}%)')
print(f'  교집합 내 na>=3:   {(intersect_df["na"]>=3).sum()} ({(intersect_df["na"]>=3).mean()*100:.0f}%)')

# 4. v80.6 universe 중 통합 universe에 없는 종목 (시총 1천억 미만? 또는 우선주?)
only_prod = prod_tics - set(all_df['ticker'])
print(f'\n[v80.6 종목 중 yf probe 안 된 종목 ({len(only_prod)}개)]')
print(f'  → 시총 1천억 미만 또는 우선주/특수 종목')
for tic in sorted(only_prod)[:15]:
    r = prod_by_tic.get(tic, {})
    nm = r.get('name', '')
    print(f'  {tic} {nm[:15]}')
if len(only_prod) > 15:
    print(f'  ... 외 {len(only_prod)-15}종목')

# 5. v80.6 교집합 시총별 cliff
print(f'\n[v80.6 교집합 종목 시총별 가용성]')
print(f'  {"시총":<10} {"종목":<6} {"fy_0y":<10} {"rev_ok":<10} {"na>=3":<10}')
for low, hi, label in buckets:
    if hi: s = intersect_df[(intersect_df.mc_krw >= low) & (intersect_df.mc_krw < hi)]
    else: s = intersect_df[intersect_df.mc_krw >= low]
    n = len(s)
    if n == 0:
        print(f'  {label:<10} 0')
        continue
    fy = s['fy_complete_0y'].sum()
    rv = s['rev_ok_0y'].sum()
    na3 = (s['na'] >= 3).sum()
    print(f'  {label:<10} {n:<6} {fy}({fy/n*100:.0f}%)   {rv}({rv/n*100:.0f}%)   {na3}({na3/n*100:.0f}%)')

# 6. KOSPI vs KOSDAQ
print(f'\n[전체 통합 시장별]')
for mkt in ['KS', 'KQ']:
    s = all_df[all_df.market == mkt]
    if len(s) == 0: continue
    fy = s['fy_complete_0y'].sum()
    na3 = (s['na'] >= 3).sum()
    avg_na = s['na'].mean()
    print(f'  {mkt}: 총 {len(s)}종목, fy {fy} ({fy/len(s)*100:.0f}%), na>=3 {na3} ({na3/len(s)*100:.0f}%), 평균 na {avg_na:.1f}')

# 7. 옵션 C 보조 신호 적용 가능 종목 (v80.6 universe 기반)
print(f'\n[옵션 C 보조 신호 적용 가능 종목 (v80.6 prod 299종목 기준)]')
for filter_name, mask in [
    ('et_ok',                       intersect_df['eps_trend_ok']),
    ('fy_complete_0y',              intersect_df['fy_complete_0y']),
    ('fy_complete + na>=3 (US 룰)', intersect_df['fy_complete_0y'] & (intersect_df['na'] >= 3)),
    ('fy_complete + na>=5',         intersect_df['fy_complete_0y'] & (intersect_df['na'] >= 5)),
    ('et_ok + rev_ok',              intersect_df['eps_trend_ok'] & intersect_df['rev_ok_0y']),
]:
    n = mask.sum()
    pct = n / len(prod_tics) * 100
    print(f'  {filter_name:<35}: {n} ({pct:.0f}%)')

# 8. 통합 저장
all_df.to_csv(OUT / 'kr_yf_combined.csv', index=False, encoding='utf-8-sig')
print(f'\n저장: {OUT / "kr_yf_combined.csv"} ({len(all_df)} rows)')
