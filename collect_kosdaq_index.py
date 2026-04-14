"""KOSDAQ 지수 OHLCV 2014-01-01 ~ 2020-05-31 수집 (yfinance 이전 구간)
1초 sleep 엄수, 회사 PC 전용
"""
import sys
import time
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

# KRX 인증 먼저
sys.path.insert(0, 'C:/dev')
from krx_auth import login, _patch_pykrx
from config import KRX_USER_ID, KRX_PASSWORD
print('[KRX 인증 시도]', flush=True)
if login(KRX_USER_ID, KRX_PASSWORD):
    _patch_pykrx()
    print('[KRX 인증 성공 + pykrx 패치 완료]', flush=True)
else:
    print('[KRX 인증 실패 — 비인증 모드로 진행]', flush=True)

from pykrx import stock

# KOSDAQ 지수 티커: "2001"
KOSDAQ_TICKER = '2001'

def fetch(start, end, label):
    print(f'  {label}: {start} ~ {end}', flush=True)
    t0 = time.time()
    df = stock.get_index_ohlcv_by_date(start, end, KOSDAQ_TICKER)
    print(f'    {len(df)}행, {time.time()-t0:.1f}초', flush=True)
    if len(df) > 0:
        print(f'    첫: {df.index[0]} = {df.iloc[0]["종가"]:.2f}', flush=True)
        print(f'    끝: {df.index[-1]} = {df.iloc[-1]["종가"]:.2f}', flush=True)
        print(f'    컬럼: {list(df.columns)}', flush=True)
    return df


# === 표본 테스트: 2014-01 ===
print('=== 표본: 2014-01 ===', flush=True)
sample = fetch('20140101', '20140131', '표본')

time.sleep(1)  # pykrx 1초 sleep

# === 검증 ===
expected_trading_days = 20  # 1월 영업일 약 20일
if len(sample) < 15 or len(sample) > 25:
    print(f'\n⚠️ 거래일 수 이상: {len(sample)} (기대 ~20)', flush=True)
    sys.exit(1)

req_cols = ['시가', '고가', '저가', '종가', '거래량']
missing = [c for c in req_cols if c not in sample.columns]
if missing:
    print(f'\n⚠️ 필수 컬럼 누락: {missing}', flush=True)
    sys.exit(1)

print(f'\n✅ 표본 OK. 전체 수집 시작.', flush=True)
time.sleep(1)

# === 전체 수집: 2014-01-01 ~ 2020-05-31 ===
# 한번에 요청 가능 (단일 지수)
print('\n=== 전체: 2014-01-01 ~ 2020-05-31 ===', flush=True)
full = fetch('20140101', '20200531', '전체')

# === 저장 ===
# 기존 kosdaq_yf.parquet와 호환되는 구조: 컬럼에 '종가' + 'kosdaq'
# 과거 데이터는 '종가' 컬럼에만 넣고 'kosdaq' 컬럼은 NaN (yfinance 데이터 로딩 때 fillna 됨)

out = pd.DataFrame({
    '종가': full['종가'],
    'kosdaq': pd.NA,
})
out.index.name = 'Date'

out_path = 'C:/dev/data_cache/kosdaq_pykrx_20140101_20200531.parquet'
out.to_parquet(out_path)
print(f'\n저장: {out_path}', flush=True)
print(f'  shape: {out.shape}', flush=True)
print(f'  범위: {out.index.min()} ~ {out.index.max()}', flush=True)
