"""
FnGuide 재무제표 캐시 주간 갱신 스크립트

매주 일요일 실행하여 전 종목 재무제표 캐시를 최신화합니다.
기존 캐시를 무시하고 FnGuide에서 새로 크롤링합니다.

실행: python refresh_fnguide_cache.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import time
import threading
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

KST = ZoneInfo('Asia/Seoul')

# 병렬 워커 수 (FnGuide 부하 방지를 위해 4로 제한)
MAX_WORKERS = 4


def _crawl_one(ticker, get_financial_statement):
    """단일 종목 크롤링 (워커 스레드에서 실행)"""
    try:
        get_financial_statement(ticker, use_cache=False)
        return ticker, True, None
    except Exception as e:
        return ticker, False, str(e)


def main():
    from data_collector import DataCollector
    from fnguide_crawler import get_financial_statement

    print(f"[FnGuide 캐시 갱신] {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")

    # 최근 거래일의 유니버스 가져오기
    dc = DataCollector()
    from pykrx import stock
    from datetime import timedelta

    today = datetime.now(KST)
    base_date = None
    for i in range(1, 10):
        date = (today - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = stock.get_market_cap(date, market='ALL')
            if not df.empty and df.iloc[:, 0].sum() > 0:
                base_date = date
                break
        except Exception:
            continue

    if not base_date:
        print("거래일을 찾을 수 없습니다.")
        sys.exit(1)

    print(f"기준일: {base_date}")

    # 시가총액 1000억 이상 종목 (넉넉하게)
    market_cap = dc.get_market_cap(base_date, market='ALL')
    tickers = market_cap[market_cap['시가총액'] >= 1000_0000_0000].index.tolist()
    print(f"갱신 대상: {len(tickers)}개 종목 (워커 {MAX_WORKERS}개 병렬)")

    success = 0
    fail = 0
    fail_tickers = []
    done = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_crawl_one, ticker, get_financial_statement): ticker
            for ticker in tickers
        }

        for future in as_completed(futures):
            ticker, ok, err = future.result()
            done += 1

            if ok:
                success += 1
            else:
                fail += 1
                fail_tickers.append(ticker)
                if fail <= 10:
                    print(f"  실패 {ticker}: {err}")

            if done % 50 == 0:
                elapsed = time.time() - start_time
                print(f"  진행: {done}/{len(tickers)} "
                      f"(성공 {success}, 실패 {fail}, "
                      f"경과 {elapsed:.0f}초)")

    elapsed = time.time() - start_time
    print(f"\n완료: {success}개 성공, {fail}개 실패 "
          f"(총 {len(tickers)}개, {elapsed:.0f}초)")

    if fail_tickers:
        print(f"실패 종목: {fail_tickers[:20]}")


if __name__ == '__main__':
    main()
