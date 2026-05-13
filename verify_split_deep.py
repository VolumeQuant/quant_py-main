"""의심 종목 정밀 검증 — 시가총액 cross check (액면분할이면 시총 유지)

DART/외부 API 호출 0. 캐시만 사용:
- market_cap_*.parquet 활용
- 점프 전/후 시가총액 비교
"""
import sys, glob, os
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np

# OHLCV
d = pd.read_parquet('C:/dev/data_cache/all_ohlcv_20170601_20260511.parquet')
weekdays = d[d.index.dayofweek < 5]
zero_pct = (weekdays == 0).sum(axis=1) / weekdays.shape[1]
trading = weekdays[zero_pct <= 0.8]

# 시가총액 파일
mc_files = sorted(glob.glob('C:/dev/data_cache/market_cap_*.parquet'))
print(f'market_cap 파일: {len(mc_files)}')
if mc_files:
    print(f'  최신: {mc_files[-1]}')
    print(f'  최초: {mc_files[0]}')

# 의심 10종목
candidates = [
    ('001790','2019-06-03'), ('003200','2019-06-03'),
    ('031820','2026-05-06'), ('064520','2022-03-22'),
    ('065170','2025-01-07'), ('078860','2023-12-27'),
    ('086960','2021-01-04'), ('241820','2025-10-17'),
    ('244460','2024-10-30'), ('405000','2025-05-09'),
]

# 2021-01-04 점프 표본 (거래정지 재개 그룹)
candidates_resume = [
    ('009730','2021-01-04'),('016670','2021-01-04'),
    ('016790','2021-01-04'),('021045','2021-01-04'),
]

# 2019-06-03 점프 표본 (불명확)
candidates_unclear = [
    ('000040','2019-06-03'),('000670','2019-06-03'),
    ('001440','2023-05-16'),('001460','2019-06-03'),
]

print('\n[진짜 액면분할 의심 10종목 — 점프 전/후 가격 패턴]')
print(f'{"종목":<8}{"점프일":<12}{"점프 직전 5일":<35}{"점프 직후 5일":<35}{"판정"}')
print('-'*100)

for tk, jump_date_str in candidates:
    series = trading[tk].replace(0, np.nan)
    jump_date = pd.Timestamp(jump_date_str)
    if jump_date not in series.index:
        print(f'  {tk}: {jump_date_str} 인덱스 없음')
        continue
    loc = series.index.get_loc(jump_date)
    pre = series.iloc[max(0,loc-5):loc].dropna().tolist()
    post = series.iloc[loc:loc+5].dropna().tolist()
    pre_str = ' '.join(f'{int(x):>7}' for x in pre[-5:])
    post_str = ' '.join(f'{int(x):>7}' for x in post[:5])

    # 점프 비율
    if pre and post and post[0] > 0:
        ratio = post[0] / pre[-1] if pre[-1] > 0 else 0
        # 정확한 액면분할 비율인지 (1/2, 1/3, 1/4, 1/5, 1/10, 1/20)
        is_split = any(abs(ratio - n) < 0.1 for n in [2,3,4,5,10,20])
        is_reverse = any(abs(ratio - 1/n) < 0.01 for n in [2,3,4,5,10,20])
        verdict = '액면분할↑' if is_split else ('액면합병↓' if is_reverse else '비정상')
    else:
        verdict = '비교불가'

    print(f'  {tk}  {jump_date_str}  {pre_str:<35}  {post_str:<35}  {verdict}')

print('\n[2021-01-04 거래정지 재개 표본 4종목]')
for tk, jump_date_str in candidates_resume:
    series = trading[tk].replace(0, np.nan)
    jump_date = pd.Timestamp(jump_date_str)
    if jump_date not in series.index: continue
    loc = series.index.get_loc(jump_date)
    pre = series.iloc[max(0,loc-30):loc]
    pre_valid = pre.dropna()
    post = series.iloc[loc:loc+5].dropna().tolist()
    pre_str = f'직전30일 유효:{len(pre_valid)}/{len(pre)} ({pre_valid.tail(3).tolist() if not pre_valid.empty else "전부 NaN"})'
    post_str = ' '.join(f'{int(x):>7}' for x in post[:5])
    print(f'  {tk}  {jump_date_str}  {pre_str}  점프후: {post_str}')

print('\n[2019-06-03 다발 점프 표본 4종목 (불명확)]')
for tk, jump_date_str in candidates_unclear:
    series = trading[tk].replace(0, np.nan)
    jump_date = pd.Timestamp(jump_date_str)
    if jump_date not in series.index: continue
    loc = series.index.get_loc(jump_date)
    pre = series.iloc[max(0,loc-5):loc].dropna().tolist()
    post = series.iloc[loc:loc+5].dropna().tolist()
    pre_str = ' '.join(f'{int(x):>7}' for x in pre[-5:])
    post_str = ' '.join(f'{int(x):>7}' for x in post[:5])
    print(f'  {tk}  {jump_date_str}  pre={pre_str}  post={post_str}')

# 2019-06-03, 2021-01-04 다발 점프 종목 카운트
print('\n[같은 날짜 동시 점프 카운트 — 데이터 source 변경 의심]')
all_jumps = {}
for tk in trading.columns:
    series = trading[tk].replace(0, np.nan).dropna()
    if len(series) < 100: continue
    ratio = series / series.shift(1)
    extreme = ratio[(ratio > 10) | (ratio < 0.1)]
    for date in extreme.index:
        all_jumps.setdefault(date.strftime('%Y-%m-%d'), []).append(tk)

# 같은 날 점프 많은 순
sorted_jumps = sorted(all_jumps.items(), key=lambda x: -len(x[1]))
print(f'동시 점프 발생 일자 (상위 15):')
for date, tks in sorted_jumps[:15]:
    print(f'  {date}: {len(tks)}종목')
