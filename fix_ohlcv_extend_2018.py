"""OHLCV 2018-07-02 ~ 2019-06-02 수집 (백업 2019-06-03 시작 보강)"""
import sys, os, time
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krx_auth
if not krx_auth.login():
    print('ERROR: KRX 로그인 실패'); sys.exit(1)

from pykrx import stock as pykrx_stock

PROJECT = Path(__file__).parent
CACHE_DIR = PROJECT / 'data_cache'

# 기존 파일 로드
ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
ohlcv_files = [f for f in ohlcv_files if '_full' not in f.stem]
if not ohlcv_files:
    print('ERROR: 기존 파일 없음'); sys.exit(1)
best_file = ohlcv_files[-1]
print(f'기준: {best_file.name}')
ohlcv_df = pd.read_parquet(best_file)
first_cached = ohlcv_df.index[0]
print(f'현재 시작: {first_cached.strftime("%Y-%m-%d")}, 종목: {len(ohlcv_df.columns)}')

# 2018-07-02 ~ 첫 캐시 직전
target_start = datetime(2018, 7, 2)
target_end = first_cached.to_pydatetime() - timedelta(days=1)
current = target_start
new_rows = []
calls = 0

while current <= target_end:
    date_str = current.strftime('%Y%m%d')
    try:
        day_ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(date_str, market='ALL')
        if not day_ohlcv.empty and '종가' in day_ohlcv.columns:
            row = day_ohlcv['종가']
            row.name = pd.Timestamp(current)
            new_rows.append(row)
            calls += 1
            if calls % 20 == 0:
                print(f'  {date_str}: ✓ {calls} 누적, {len(row)} 종목')
    except Exception as e:
        pass  # 휴장일
    time.sleep(1)
    current += timedelta(days=1)

print(f'\n수집 완료: {calls} 거래일')

if new_rows:
    new_df = pd.DataFrame(new_rows)
    ohlcv_df = pd.concat([new_df, ohlcv_df])
    ohlcv_df = ohlcv_df[~ohlcv_df.index.duplicated(keep='last')].sort_index()
    new_start = ohlcv_df.index[0].strftime('%Y%m%d')
    new_end = ohlcv_df.index[-1].strftime('%Y%m%d')
    new_cache = CACHE_DIR / f'all_ohlcv_{new_start}_{new_end}.parquet'
    ohlcv_df.to_parquet(new_cache)
    print(f'저장: {new_cache.name} ({len(ohlcv_df.columns)}종목, {len(ohlcv_df)}일)')
    for old_f in CACHE_DIR.glob('all_ohlcv_*.parquet'):
        if old_f != new_cache:
            old_f.unlink()
            print(f'정리: {old_f.name}')
