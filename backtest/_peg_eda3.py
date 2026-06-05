"""EDA3: market_cap + fs_dart 구조 확인 → daily self_per(시총/TTM NI) 재구성 가능성."""
import glob, sys
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')

# market_cap 구조
mc_files = sorted(glob.glob('data_cache/market_cap_ALL_*.parquet'))
print('market_cap files:', len(mc_files))
mc = pd.read_parquet(mc_files[-1])
print('market_cap shape:', mc.shape)
print('market_cap cols:', list(mc.columns))
print('market_cap index name:', mc.index.name, '| sample idx:', list(mc.index[:3]))
print(mc.head(3))

# 날짜 분포: 일별인지 분기별인지
dates = [f.split('_')[-1].replace('.parquet','') for f in mc_files]
print('\nmarket_cap date range:', dates[0], '~', dates[-1])
# 2024년 며칠치 있나
y2024 = [d for d in dates if d.startswith('2024')]
print('2024 market_cap days:', len(y2024), '(일별이면 ~245)')

# fs_dart 구조
print('\n=== fs_dart sample (005930) ===')
fd = pd.read_parquet('data_cache/fs_dart_005930.parquet')
print('shape:', fd.shape, '| cols:', list(fd.columns))
print(fd.head(8).to_string())
# 당기순이익 계정 있나
if '계정' in fd.columns:
    print('\n계정 unique:', fd['계정'].unique()[:20])
