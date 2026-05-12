"""OHLCV 결손 일자 통째 재수집 v2 — REFILL_progress.parquet base + 들여쓰기 버그 수정.

이전 작업(중지된 v1)에서 200일 채워진 progress.parquet base로 이어서 진행.
"""
import sys, os, time
from pathlib import Path
import pandas as pd
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import krx_auth
if not krx_auth.login():
    print('ERROR: KRX 로그인 실패', flush=True)
    sys.exit(1)
from pykrx import stock as pykrx_stock

CACHE = Path('data_cache')
SRC_PROGRESS = CACHE / 'all_ohlcv_REFILL_progress.parquet'
SRC_MAIN = CACHE / 'all_ohlcv_20170601_20260512.parquet'

# progress 있으면 그걸로 시작 (이미 200일 채워짐), 없으면 main
if SRC_PROGRESS.exists():
    SRC = SRC_PROGRESS
    print(f'[1/3] load progress: {SRC.name}', flush=True)
else:
    SRC = SRC_MAIN
    print(f'[1/3] load main: {SRC.name}', flush=True)

o = pd.read_parquet(SRC)
print(f'  shape: {o.shape}', flush=True)

nz = o.notna().sum(axis=1)
bad = nz[nz < 1500].index.sort_values()
print(f'[2/3] 결손 일자: {len(bad)} ({bad.min().date()} ~ {bad.max().date()})', flush=True)

start = time.time()
fail_dates = []
saved_at = 0
for i, ts in enumerate(bad, 1):
    date_str = ts.strftime('%Y%m%d')
    try:
        df = pykrx_stock.get_market_ohlcv_by_ticker(date_str, market='ALL')
        if df.empty or '종가' not in df.columns:
            fail_dates.append(date_str)
            print(f'  {i}/{len(bad)} {date_str}: EMPTY', flush=True)
            time.sleep(1.0)
            continue
        row = df['종가'].replace(0, np.nan)
        # 새 종목 컬럼 추가
        new_tickers = set(row.index) - set(o.columns)
        if new_tickers:
            for t in new_tickers:
                o[t] = np.nan
        o.loc[ts, row.index] = row.values
        if i % 50 == 0:
            elapsed = time.time() - start
            eta = elapsed / i * (len(bad) - i) / 60
            avail = o.loc[ts].notna().sum()
            print(f'  {i}/{len(bad)} {date_str}: {avail}종목 ({elapsed/60:.1f}분 / ETA {eta:.0f}분)', flush=True)
        # 100일마다 중간 저장 (들여쓰기 정상 — for 루프 안에)
        if i % 100 == 0:
            o.to_parquet(SRC_PROGRESS)
            saved_at = i
            print(f'    [save] progress {i}일 저장', flush=True)
        time.sleep(1.0)
    except Exception as e:
        fail_dates.append(date_str)
        print(f'  {i}/{len(bad)} {date_str}: ERROR {type(e).__name__}: {e}', flush=True)
        time.sleep(2.0)

print(f'\n[3/3] 완료 — {(time.time()-start)/60:.1f}분, 실패 {len(fail_dates)}일', flush=True)
if fail_dates:
    print(f'  실패 일자: {fail_dates[:30]}', flush=True)

# 최종 저장 — main 파일에 (sorted)
o = o.sort_index().sort_index(axis=1)
o.to_parquet(SRC_MAIN)
print(f'  saved main: {SRC_MAIN.name} ({len(o.columns)}종목, {len(o)}일)', flush=True)

# progress 파일도 갱신 (호환성)
o.to_parquet(SRC_PROGRESS)

# 검증
nz2 = o.notna().sum(axis=1)
bad2 = nz2[nz2 < 1500]
print(f'\n  최종 결손 일자: {len(bad2)} (시작 {len(bad)} → 끝 {len(bad2)})', flush=True)
print(f'  연도별 평균 종목수:', flush=True)
print(nz2.resample('YE').mean().round(0).to_string(), flush=True)
