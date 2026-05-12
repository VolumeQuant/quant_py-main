"""OHLCV 캐시 증분 수집 (3/31 ~ 5/11) — 사고 복구용

원인: 5/12 작업 중 data_cache/all_ohlcv_*.parquet 직접 위치에서 사라짐.
가장 최신 백업 (all_ohlcv_20190603_20260330.parquet) 복원됨.
3/31 ~ 5/11 약 30거래일 증분 필요.

방식: pykrx 일자별 ALL 호출 (사용자 원칙: 1초 sleep, 순차)
"""
import sys, time
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

from pykrx import stock as pykrx_stock

PROJECT = Path(__file__).parent
CACHE_DIR = PROJECT / 'data_cache'

# 1. 가장 최신 파일 로드
ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
ohlcv_files = [f for f in ohlcv_files if '_full' not in f.stem]  # _full 우선 X
if not ohlcv_files:
    print('ERROR: all_ohlcv 파일 없음')
    sys.exit(1)
best_file = ohlcv_files[-1]
print(f'기준 파일: {best_file.name}')

ohlcv_df = pd.read_parquet(best_file)
last_cached = ohlcv_df.index[-1]
print(f'마지막 거래일: {last_cached.strftime("%Y-%m-%d")}, 종목 수: {len(ohlcv_df.columns)}')

# 2. 5/11까지 증분 수집
target_end = datetime(2026, 5, 11)
current = last_cached.to_pydatetime() + timedelta(days=1)
new_rows = []
calls = 0
fails = 0

while current <= target_end:
    date_str = current.strftime('%Y%m%d')
    try:
        day_ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(date_str, market='ALL')
        if not day_ohlcv.empty and '종가' in day_ohlcv.columns:
            row = day_ohlcv['종가']
            row.name = pd.Timestamp(current)
            new_rows.append(row)
            calls += 1
            print(f'  {date_str}: ✓ ({len(row)} 종목)')
        else:
            print(f'  {date_str}: 휴장')
    except Exception as e:
        fails += 1
        print(f'  {date_str}: ✗ {type(e).__name__}')
    time.sleep(1)  # 사용자 원칙: 1초 sleep
    current += timedelta(days=1)

print(f'\n수집: {calls} 거래일, 실패 {fails}')

# 3. 저장
if new_rows:
    new_df = pd.DataFrame(new_rows)
    ohlcv_df = pd.concat([ohlcv_df, new_df])
    ohlcv_df = ohlcv_df[~ohlcv_df.index.duplicated(keep='last')].sort_index()
    new_start = ohlcv_df.index[0].strftime('%Y%m%d')
    new_end = ohlcv_df.index[-1].strftime('%Y%m%d')
    new_cache = CACHE_DIR / f'all_ohlcv_{new_start}_{new_end}.parquet'
    ohlcv_df.to_parquet(new_cache)
    print(f'저장: {new_cache.name} ({len(ohlcv_df.columns)}종목, {len(ohlcv_df)}일)')
    # 기존 파일 정리 (3/30 백업)
    for old_f in CACHE_DIR.glob('all_ohlcv_*.parquet'):
        if old_f != new_cache:
            print(f'정리: {old_f.name} 제거')
            old_f.unlink()
else:
    print('새 거래일 없음 — 종료')
