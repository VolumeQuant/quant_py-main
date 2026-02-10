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
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')

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
    print(f"갱신 대상: {len(tickers)}개 종목")

    success = 0
    fail = 0
    for i, ticker in enumerate(tickers):
        try:
            get_financial_statement(ticker, use_cache=False)
            success += 1
            if (i + 1) % 50 == 0:
                print(f"  진행: {i+1}/{len(tickers)} (성공 {success}, 실패 {fail})")
            time.sleep(0.3)  # FnGuide 부하 방지
        except Exception as e:
            fail += 1
            if fail <= 10:
                print(f"  실패 {ticker}: {e}")

    print(f"\n완료: {success}개 성공, {fail}개 실패 (총 {len(tickers)}개)")


if __name__ == '__main__':
    main()
