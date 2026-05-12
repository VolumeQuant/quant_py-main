"""OHLCV 결손 일자 (가용 종목 < 1500) pykrx 통째 재수집.

전략:
  - 일자별 pykrx.get_market_ohlcv_by_ticker(date, market='ALL') 한 호출 → 그 날 전체 종목
  - 결손 일자만 호출 (약 1675일 × 1초 sleep ≈ 60분)
  - 그 행 통째로 교체 (NaN → 실제 종가)
  - 중간 진행 저장 (50일마다)
"""
import sys, os, time
from pathlib import Path
import pandas as pd
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krx_auth
if not krx_auth.login():
    print('ERROR: KRX 로그인 실패')
    sys.exit(1)
from pykrx import stock as pykrx_stock

CACHE = Path('data_cache')
SRC = CACHE / 'all_ohlcv_20170601_20260512.parquet'
print(f'[1/3] load {SRC.name}')
o = pd.read_parquet(SRC)
print(f'  shape: {o.shape}')

nz = o.notna().sum(axis=1)
bad = nz[nz < 1500].index.sort_values()
print(f'[2/3] 결손 일자: {len(bad)} ({bad.min().date()} ~ {bad.max().date()})')

start = time.time()
fail_dates = []
for i, ts in enumerate(bad, 1):
    date_str = ts.strftime('%Y%m%d')
    try:
        df = pykrx_stock.get_market_ohlcv_by_ticker(date_str, market='ALL')
        if df.empty or '종가' not in df.columns:
            fail_dates.append(date_str)
            print(f'  {i}/{len(bad)} {date_str}: EMPTY', flush=True)
            continue
        row = df['종가'].replace(0, np.nan)
        # 기존 column에 정렬, 새 column은 reindex로 추가
        new_cols = sorted(set(o.columns) | set(row.index))
        if set(new_cols) != set(o.columns):
            o = o.reindex(columns=new_cols)
        o.loc[ts, row.index] = row.values
        if i % 50 == 0:
            elapsed = time.time() - start
            eta = elapsed / i * (len(bad) - i) / 60
            avail = o.loc[ts].notna().sum()
            print(f'  {i}/{len(bad)} {date_str}: {avail}종목 ({elapsed/60:.1f}분 / ETA {eta:.0f}분)', flush=True)
        time.sleep(1.0)  # IP 차단 방지
    except Exception as e:
        fail_dates.append(date_str)
        print(f'  {i}/{len(bad)} {date_str}: ERROR {type(e).__name__}: {e}', flush=True)
        time.sleep(2.0)

# 중간 저장 (50일마다)
    if i % 100 == 0:
        tmp = CACHE / 'all_ohlcv_REFILL_progress.parquet'
        o.to_parquet(tmp)
        print(f'    [save] {tmp.name}', flush=True)

print(f'\n[3/3] 완료 — {(time.time()-start)/60:.1f}분, 실패 {len(fail_dates)}일')
if fail_dates:
    print(f'  실패 표본: {fail_dates[:10]}')

# 최종 저장
OUT = CACHE / 'all_ohlcv_20170601_20260512.parquet'
o = o.sort_index().sort_index(axis=1)
o.to_parquet(OUT)
print(f'  saved: {OUT.name} ({len(o.columns)}종목, {len(o)}일)')

# 검증
nz2 = o.notna().sum(axis=1)
bad2 = nz2[nz2 < 1500]
print(f'  남은 결손 일자: {len(bad2)} (목표 < 100)')
print(f'  분기별 종목수 (2019-2026):')
print(nz2.resample('QE').mean().round(0).to_string())
