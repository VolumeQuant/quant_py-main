"""DART 2016 커버리지 EDA — 어떤 종목이 2016 데이터 있고 없는지
현재 fs_dart_*.parquet 1892개 중 2016 데이터 있는 종목 확인
"""
import pandas as pd
from pathlib import Path

CACHE = Path('C:/dev/data_cache')
fs_files = sorted(CACHE.glob('fs_dart_*.parquet'))
print(f'fs_dart 파일: {len(fs_files)}개', flush=True)

has_2016 = []
no_2016 = []
has_2016_partial = []  # 일부 분기만

for fp in fs_files:
    ticker = fp.stem.replace('fs_dart_', '')
    try:
        df = pd.read_parquet(fp)
        if df.empty:
            no_2016.append(ticker)
            continue
        y2016 = df[df['기준일'].dt.year == 2016]
        if y2016.empty:
            no_2016.append(ticker)
        else:
            # 2016 분기 커버리지
            quarters = set(y2016['기준일'].unique())
            if len(quarters) >= 4:  # Q1~Q4 완전
                has_2016.append(ticker)
            else:
                has_2016_partial.append((ticker, len(quarters)))
    except Exception as e:
        no_2016.append(ticker)

print(f'\n=== DART 2016 커버리지 ===')
print(f'  완전 (Q1~Q4 전부): {len(has_2016)}')
print(f'  부분 (1~3 분기만): {len(has_2016_partial)}')
print(f'  없음: {len(no_2016)}')
print(f'  전체 fs_dart: {len(fs_files)}')

# 2016년에 활성 종목 수 확인 (market_cap으로)
mc_files = sorted(CACHE.glob('market_cap_ALL_2016*.parquet'))
if mc_files:
    mc_sample = pd.read_parquet(mc_files[len(mc_files)//2])  # 중간 파일
    active_2016 = set(mc_sample.index.astype(str).str.zfill(6))
    print(f'\n  2016년 활성 종목 (market_cap 기준): {len(active_2016)}')

    # fs_dart 있는 종목 중 2016 없는 종목
    fs_tickers = set(fp.stem.replace('fs_dart_', '') for fp in fs_files)
    need_2016 = fs_tickers & active_2016 - set(has_2016)
    print(f'  fs_dart 있으나 2016 없는 + 2016 활성: {len(need_2016)}')

    # 미수집 active 종목 (fs_dart 자체가 없음)
    not_in_fs = active_2016 - fs_tickers
    print(f'  market_cap 2016 있으나 fs_dart 없음: {len(not_in_fs)}')

# 부분 샘플
if has_2016_partial:
    print(f'\n부분 샘플 (5개):')
    for t, q in has_2016_partial[:5]:
        print(f'  {t}: {q}개 분기')
