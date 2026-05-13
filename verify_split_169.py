"""169종목 액면분할 의심 정밀 검증 (DART/외부 API 호출 0)

검증 방법:
1. 점프 비율이 정수배 패턴 (4, 5, 10 등) → 진짜 액면분할 가능성
2. 시가총액 데이터와 교차 검증 (있으면) — 액면분할이면 시총 유지
3. 점프 후 가격 안정성 (영구 변화 vs 단발 튀김)
4. 거래정지 → 재개 패턴 (점프 직전 NaN/0 다수)
"""
import sys, glob, os
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np
from collections import defaultdict

d = pd.read_parquet('C:/dev/data_cache/all_ohlcv_20170601_20260511.parquet')
weekdays = d[d.index.dayofweek < 5]
zero_pct = (weekdays == 0).sum(axis=1) / weekdays.shape[1]
trading = weekdays[zero_pct <= 0.8]

# 169 의심 종목 다시 추출 + 점프 상세 분석
print('[1] 점프 패턴 정밀 분석')
print(f'{"종목":<8}{"점프수":>4}  {"첫점프일":<12}{"점프비율":<15}{"점프직전 N일 0/NaN":<20}{"점프후 30일 변동":<15}')
print('-'*90)

results = []
for tk in trading.columns:
    series = trading[tk].replace(0, np.nan).dropna()
    if len(series) < 100: continue
    ratio = series / series.shift(1)
    extreme = ratio[(ratio > 10) | (ratio < 0.1)]
    if extreme.empty: continue

    # 점프 직전 N일에 0/NaN 비율 (거래정지 → 재개 시그널)
    first_jump_date = extreme.index[0]
    raw_series = trading[tk]
    jump_loc = raw_series.index.get_loc(first_jump_date)
    pre_window = raw_series.iloc[max(0,jump_loc-30):jump_loc]
    pre_invalid = ((pre_window == 0) | pre_window.isna()).sum()

    # 점프 비율들
    jump_ratios = extreme.values

    # 점프 후 30일 가격 변동 (안정 vs 더 큰 변동)
    post_window = raw_series.iloc[jump_loc:jump_loc+30].replace(0, np.nan).dropna()
    post_volatility = post_window.std() / post_window.mean() if len(post_window) > 5 and post_window.mean() != 0 else None

    # 분류
    # 모든 점프 비율이 정수배 ±5% 이내 → 액면분할 강한 신호
    is_clean_split = all(any(abs(abs(r) - n) < n*0.05 for n in [2,3,4,5,10,20]) for r in jump_ratios)

    # 거래정지 재개 패턴 (점프 직전 0/NaN 10일+)
    is_resume = pre_invalid >= 10

    results.append({
        'ticker': tk,
        'n_jumps': len(extreme),
        'first_date': first_jump_date.strftime('%Y-%m-%d'),
        'ratios': [round(r,2) for r in jump_ratios],
        'pre_invalid': pre_invalid,
        'post_volatility': round(post_volatility, 3) if post_volatility else None,
        'is_clean_split': is_clean_split,
        'is_resume': is_resume,
    })

# 카테고리별 분류
clean_splits = [r for r in results if r['is_clean_split'] and not r['is_resume']]
resumes = [r for r in results if r['is_resume']]
unclear = [r for r in results if not r['is_clean_split'] and not r['is_resume']]

print(f'\n[2] 분류 결과 ({len(results)}종목)')
print(f'  진짜 액면분할 의심 (정수배 + 거래정지 아님): {len(clean_splits)}')
print(f'  거래정지 재개 (점프 직전 0/NaN 10일+):       {len(resumes)}')
print(f'  불명확 (둘 다 아님 — 별도 검증):              {len(unclear)}')

print('\n[3] 진짜 액면분할 의심 (정밀 검증 필요) — 앞 20')
for r in clean_splits[:20]:
    print(f'  {r["ticker"]} {r["first_date"]} 비율={r["ratios"]} 점프수={r["n_jumps"]}')

print('\n[4] 거래정지 재개 (BT 영향 작음) — 앞 10')
for r in resumes[:10]:
    print(f'  {r["ticker"]} {r["first_date"]} 비율={r["ratios"]} pre_invalid={r["pre_invalid"]}')

print('\n[5] 불명확 — 앞 10')
for r in unclear[:10]:
    print(f'  {r["ticker"]} {r["first_date"]} 비율={r["ratios"]} pre_invalid={r["pre_invalid"]}')

# 저장
import json
with open('C:/dev/split_169_analysis.json', 'w', encoding='utf-8') as f:
    json.dump({
        'total': len(results),
        'clean_splits': clean_splits,
        'resumes': resumes,
        'unclear': unclear,
    }, f, ensure_ascii=False, indent=1)
print('\n저장: split_169_analysis.json')

# 액면분할 의심 종목 리스트 저장 (재수집 대상 또는 OHLCV 정정 대상)
with open('C:/dev/suspicious_split_tickers.txt', 'w') as f:
    for r in clean_splits:
        f.write(r['ticker'] + '\n')
print(f'저장: suspicious_split_tickers.txt ({len(clean_splits)}종목)')
