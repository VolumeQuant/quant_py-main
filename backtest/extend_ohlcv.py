"""OHLCV 데이터를 과거로 확장 (하락장/횡보장 백테스트용)

기존 all_ohlcv 파일의 종목 리스트로 과거 데이터 수집 후 병합.
pykrx get_market_ohlcv_by_date(start, end, ticker) 사용.

Usage:
    python backtest/extend_ohlcv.py
"""
import sys
import time
from pathlib import Path

import pandas as pd
from pykrx import stock as pykrx_stock

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / 'data_cache'

EXTEND_START = '20210601'


def main():
    # 1. 기존 OHLCV 로드
    existing_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    if not existing_files:
        print('기존 OHLCV 파일 없음')
        return

    existing = pd.read_parquet(existing_files[-1])
    existing_start = existing.index[0].strftime('%Y%m%d')
    existing_end = existing.index[-1].strftime('%Y%m%d')
    tickers = list(existing.columns)
    print(f'기존 OHLCV: {existing_start} ~ {existing_end} ({len(existing)}일, {len(tickers)}종목)')

    # 2. 확장 기간 확인
    extend_end = (existing.index[0] - pd.Timedelta(days=1)).strftime('%Y%m%d')
    print(f'확장: {EXTEND_START} ~ {extend_end}')
    print(f'대상 종목: {len(tickers)}개')
    print(f'예상 시간: {len(tickers) * 1 / 60:.0f}분')

    # 3. 종목별 종가 수집
    # get_market_ohlcv_by_date 컬럼: 시가, 고가, 저가, 종가, 거래량, 등락률
    # 인코딩 이슈로 컬럼명 대신 인덱스(3번째=종가) 사용
    price_data = {}
    t0 = time.time()
    success = 0
    for i, ticker in enumerate(tickers):
        try:
            df = pykrx_stock.get_market_ohlcv_by_date(EXTEND_START, extend_end, ticker)
            if not df.empty:
                close_col = df.columns[3]  # 종가 (4번째 컬럼)
                price_data[ticker] = df[close_col]
                success += 1
        except Exception as e:
            if (i + 1) % 100 == 0:
                print(f'    실패: {ticker} — {e}')

        time.sleep(0.1)  # KRX 속도 제한 방지

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            rate = elapsed / (i + 1)
            remaining = rate * (len(tickers) - i - 1) / 60
            print(f'  [{i+1}/{len(tickers)}] {success}종목 수집, {elapsed:.0f}초, 남은 ~{remaining:.0f}분')

    elapsed = time.time() - t0
    print(f'\n수집 완료: {success}/{len(tickers)}종목, {elapsed:.0f}초')

    if not price_data:
        print('수집된 데이터 없음')
        return

    # 4. DataFrame 빌드 + 기존 데이터 병합
    new_df = pd.DataFrame(price_data)
    print(f'신규: {len(new_df)}거래일, {len(new_df.columns)}종목')

    merged = pd.concat([new_df, existing])
    merged = merged[~merged.index.duplicated(keep='last')]
    merged = merged.sort_index()

    # 0원 행 제거
    zero_rows = (merged == 0).all(axis=1)
    if zero_rows.any():
        merged = merged[~zero_rows]
        print(f'0원 행 제거: {zero_rows.sum()}일')

    # 5. 저장
    new_start = merged.index[0].strftime('%Y%m%d')
    new_end = merged.index[-1].strftime('%Y%m%d')
    out_file = CACHE_DIR / f'all_ohlcv_{new_start}_{new_end}.parquet'
    merged.to_parquet(out_file)

    print(f'\n확장 완료: {out_file.name}')
    print(f'  기간: {new_start} ~ {new_end}')
    print(f'  거래일: {len(merged)}')
    print(f'  종목수: {len(merged.columns)}')
    print(f'  소요: {elapsed / 60:.1f}분')


if __name__ == '__main__':
    main()
