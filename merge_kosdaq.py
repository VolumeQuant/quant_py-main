"""KOSDAQ 2014-01 ~ 2026-04 완전 시리즈 생성
pykrx(2014-01~2020-05) + yfinance(2020-06~2026-04)
"""
import pandas as pd

# pykrx 과거 데이터
old = pd.read_parquet('C:/dev/data_cache/kosdaq_pykrx_20140101_20200531.parquet')
old_close = old['종가'].rename('close')
print(f'pykrx: {old_close.index.min()} ~ {old_close.index.max()}, {len(old_close)}일')

# yfinance 현재 데이터
new_df = pd.read_parquet('C:/dev/data_cache/kosdaq_yf.parquet')
new_close = new_df.iloc[:, 0].fillna(new_df['kosdaq']).rename('close')
print(f'yfinance: {new_close.index.min()} ~ {new_close.index.max()}, {len(new_close)}일')

# 겹치는 구간 확인
overlap = old_close.index.intersection(new_close.index)
print(f'겹침: {len(overlap)}')

# 병합 (pykrx 우선, yfinance는 이후 구간)
merged = pd.concat([old_close[old_close.index < '2020-06-01'], new_close]).sort_index()
merged = merged[~merged.index.duplicated(keep='first')]
print(f'병합: {merged.index.min()} ~ {merged.index.max()}, {len(merged)}일')
print(f'NaN: {merged.isna().sum()}')

# 저장 - 기존 kosdaq_yf.parquet 포맷 맞춤 ('종가' 컬럼)
out = pd.DataFrame({'종가': merged, 'kosdaq': merged})
out.index.name = 'Date'
out.to_parquet('C:/dev/data_cache/kosdaq_full_20140102_20260413.parquet')
print(f'저장: kosdaq_full_20140102_20260413.parquet')

# 검증: MA200 계산
ma200 = merged.rolling(200).mean()
print(f'MA200 첫 값: {ma200.first_valid_index()}')
print(f'2018-01 KOSDAQ MA200: {ma200.get(pd.Timestamp("2018-01-02"))}')
print(f'2018-07 KOSDAQ MA200: {ma200.get(pd.Timestamp("2018-07-02"))}')
