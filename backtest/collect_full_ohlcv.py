"""전체 KRX OHLCV 수집 — 하루 1건 API로 전 종목 한 번에

pykrx.get_market_ohlcv_by_date(date, date, market='ALL') 사용
1,287거래일 × 1초 sleep = ~21분

Usage:
    python backtest/collect_full_ohlcv.py
"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from pathlib import Path

CACHE_DIR = Path('data_cache')

def main():
    # 기존 OHLCV에서 거래일 목록 추출
    existing_files = sorted(CACHE_DIR.glob('all_ohlcv_2019*.parquet'))
    if not existing_files:
        existing_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    full_files = [f for f in existing_files if '_full' in f.stem]
    if full_files:
        existing_files = full_files
    existing = pd.read_parquet(existing_files[0])
    trading_dates = existing.index.tolist()
    print(f'거래일: {len(trading_dates)}일 ({trading_dates[0].strftime("%Y%m%d")}~{trading_dates[-1].strftime("%Y%m%d")})')

    # BT 기간만 (20210104~)
    bt_start = pd.Timestamp('20210101')
    bt_dates = [d for d in trading_dates if d >= bt_start]
    print(f'BT 기간: {len(bt_dates)}일 ({bt_dates[0].strftime("%Y%m%d")}~{bt_dates[-1].strftime("%Y%m%d")})')

    # pykrx 인증
    import krx_auth
    krx_auth.login()
    from pykrx import stock as pykrx_stock

    # 수집
    all_data = {}  # {date: {ticker: close_price}}
    t0 = time.time()
    failed = 0

    for i, dt in enumerate(bt_dates):
        date_str = dt.strftime('%Y%m%d')
        try:
            df = pykrx_stock.get_market_ohlcv_by_ticker(date_str, market='ALL')
            if not df.empty and '종가' in df.columns:
                closes = df['종가'].to_dict()
                all_data[dt] = {str(k).zfill(6): v for k, v in closes.items() if v > 0}
            time.sleep(1)
        except Exception as e:
            failed += 1
            if failed <= 5:
                print(f'  {date_str} 실패: {e}')
            time.sleep(1)

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            remain = (len(bt_dates) - i - 1) / rate
            n_tickers = len(set().union(*[set(v.keys()) for v in all_data.values()])) if all_data else 0
            print(f'  [{i+1}/{len(bt_dates)}] {elapsed:.0f}초 | 남은 ~{remain:.0f}초 | 종목 {n_tickers}개 | 실패 {failed}', flush=True)

    elapsed = time.time() - t0
    print(f'\n수집 완료: {len(all_data)}일, {elapsed/60:.1f}분, 실패 {failed}', flush=True)

    if not all_data:
        print('데이터 없음!')
        return

    # DataFrame 생성
    print('DataFrame 변환 중...', flush=True)
    all_tickers = sorted(set().union(*[set(v.keys()) for v in all_data.values()]))
    print(f'전체 종목: {len(all_tickers)}개')

    result = pd.DataFrame(index=bt_dates, columns=all_tickers, dtype=np.float64)
    for dt, closes in all_data.items():
        for ticker, price in closes.items():
            result.loc[dt, ticker] = price

    # 기존 OHLCV의 BT 이전 데이터와 합치기
    pre_bt = existing[existing.index < bt_start]
    if not pre_bt.empty:
        # 기존 종목 + 신규 종목 합집합
        all_cols = sorted(set(pre_bt.columns) | set(result.columns))
        pre_bt = pre_bt.reindex(columns=all_cols)
        result = result.reindex(columns=all_cols)
        full = pd.concat([pre_bt, result])
    else:
        full = result

    # 저장
    start_str = full.index[0].strftime('%Y%m%d')
    end_str = full.index[-1].strftime('%Y%m%d')
    out_path = CACHE_DIR / f'all_ohlcv_{start_str}_{end_str}_full.parquet'
    full.to_parquet(out_path)
    print(f'\n저장: {out_path.name} ({full.shape[0]}일 × {full.shape[1]}종목)', flush=True)

    # 기존 파일과 비교
    print(f'\n기존: {existing.shape[1]}종목')
    print(f'신규: {full.shape[1]}종목 (+{full.shape[1] - existing.shape[1]})')

    # 시총 1000억+ 커버리지 확인
    mcap = pd.read_parquet(sorted(CACHE_DIR.glob('market_cap_ALL_20260403.parquet'))[-1])
    large = set(mcap[mcap['시가총액'] / 1e8 >= 1000].index)
    in_full = large & set(full.columns)
    print(f'시총 1000억+ 커버리지: {len(in_full)}/{len(large)} ({len(in_full)/len(large)*100:.1f}%)')


if __name__ == '__main__':
    main()
