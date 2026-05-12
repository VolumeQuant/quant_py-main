"""data_refresher.refresh_all(date) 4/18 ~ 5/12 일괄 갱신.

거래일만 호출 (휴장일은 데이터 없어서 skip). 약 17 거래일.
"""
import sys, os
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krx_auth
krx_auth.login()

from data_refresher import refresh_all

# OHLCV에서 거래일 추출
ohlcv = pd.read_parquet('data_cache/all_ohlcv_20170601_20260511.parquet')
trading_dates = ohlcv.index[(ohlcv.index >= pd.Timestamp('2026-04-18')) & (ohlcv.index <= pd.Timestamp('2026-05-12'))]
print(f'거래일: {len(trading_dates)}')
for ts in trading_dates:
    print(f'  {ts.date()}')

print('\n=== data_refresher.refresh_all 일자별 호출 ===')
for ts in trading_dates:
    date_str = ts.strftime('%Y%m%d')
    print(f'\n[{date_str}]')
    try:
        refresh_all(date_str)
    except Exception as e:
        print(f'  ERROR: {type(e).__name__}: {e}')

# 5/12 OHLCV도 추가 (현재 5/11까지)
print('\n=== 5/12 OHLCV 추가 ===')
from pykrx import stock as pykrx_stock
import time
df = pykrx_stock.get_market_ohlcv_by_ticker('20260512', market='ALL')
if not df.empty and '종가' in df.columns:
    row = df['종가']
    row.name = pd.Timestamp('2026-05-12')
    new_df = pd.DataFrame([row])
    merged = pd.concat([ohlcv, new_df])
    merged = merged[~merged.index.duplicated(keep='last')].sort_index()
    out = Path('data_cache') / 'all_ohlcv_20170601_20260512.parquet'
    merged.to_parquet(out)
    print(f'저장: {out.name} ({len(merged.columns)}종목, {len(merged)}일)')
    # 기존 파일 제거
    old = Path('data_cache') / 'all_ohlcv_20170601_20260511.parquet'
    if old.exists():
        old.unlink()
        print(f'정리: {old.name}')
