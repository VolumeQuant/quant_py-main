"""DART 전체 수집 스크립트 — 우선순위별 자동 진행

트리플 키 (57,000건/일) 활용, skip_cached=True로 이미 수집된 것 자동 스킵.

우선순위:
  1. 2024-2025 × 전체 (프로덕션)
  2. 2021-2022 × 전체 (하락장 백테스트)
  3. 2020 × 전체 (Growth YoY)
  4. 2023 × 전체 (횡보장)

Usage:
    python collect_dart_all.py              # 전체 우선순위 순서대로
    python collect_dart_all.py --resume     # 중단 지점부터 재개 (skip_cached)
"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from pykrx import stock as pykrx_stock
from dart_collector import DartCollector

# KRX 인증
import krx_auth
krx_auth.login()

PROJECT_ROOT = Path(__file__).parent
CACHE_DIR = PROJECT_ROOT / 'data_cache'


def get_universe_tickers(min_mcap_억=1000):
    """시총 기준 유니버스 (1000억+, 금융 제외)"""
    # 최근 market_cap 캐시에서 로드
    mcap_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
    if not mcap_files:
        print('market_cap 캐시 없음 — pykrx에서 직접 조회')
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        KST = ZoneInfo('Asia/Seoul')
        today = datetime.now(KST)
        for i in range(1, 20):
            date = (today - timedelta(days=i)).strftime('%Y%m%d')
            try:
                df = pykrx_stock.get_market_cap(date, market='ALL')
                if not df.empty and df['시가총액'].sum() > 0:
                    break
            except Exception:
                continue
        else:
            raise RuntimeError('거래일 찾기 실패')
    else:
        df = pd.read_parquet(mcap_files[-1])

    df['시가총액_억'] = df['시가총액'] / 1e8
    filtered = df[df['시가총액_억'] >= min_mcap_억]

    # 금융업 제외
    exclude = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
               '홀딩스', 'SPAC', '스팩', '리츠', 'REIT']
    tickers = []
    for ticker in filtered.index.tolist():
        try:
            name = pykrx_stock.get_market_ticker_name(ticker)
            if not any(kw in name for kw in exclude):
                tickers.append(ticker)
        except Exception:
            tickers.append(ticker)

    print(f'유니버스: {len(tickers)}종목 (시총 {min_mcap_억}억+, 금융 제외)')
    return tickers


def collect_priority(dc, tickers, year_groups):
    """우선순위별 수집"""
    for priority, (label, start_year, end_year) in enumerate(year_groups, 1):
        print(f'\n{"="*60}')
        print(f'[{priority}순위] {label}: {start_year}~{end_year} × {len(tickers)}종목')
        print(f'{"="*60}')

        try:
            success, skipped, failed = dc.fetch_universe(
                tickers, start_year, end_year, skip_cached=True
            )
            print(f'결과: {success}수집 {skipped}스킵 {len(failed)}실패')
            print(f'누적 API: {dc._call_count}건 / {dc._total_limit}건')
        except RuntimeError as e:
            if '한도' in str(e):
                print(f'\n일일 한도 도달! ({dc._call_count}건)')
                print('내일 다시 실행하면 skip_cached로 이어서 수집됩니다.')
                return False
            raise

    return True


def main():
    print('DART 전체 수집 — 트리플 키 (57,000건/일)')
    print()

    # 유니버스 로드
    tickers = get_universe_tickers(min_mcap_억=1000)

    # 수집기 생성 (트리플 키 자동 감지)
    dc = DartCollector()

    # 우선순위별 연도 그룹
    year_groups = [
        ('프로덕션', 2024, 2025),
        ('분기YoY+횡보장', 2023, 2023),
        ('하락장 백테스트', 2021, 2022),
        ('Growth YoY 깊은과거', 2020, 2020),
    ]

    t0 = time.time()
    completed = collect_priority(dc, tickers, year_groups)
    elapsed = time.time() - t0

    print(f'\n{"="*60}')
    print(f'총 소요: {elapsed/60:.1f}분')
    print(f'총 API: {dc._call_count}건')
    print(f'DART 캐시: {len(list(CACHE_DIR.glob("fs_dart_*.parquet")))}개')
    if not completed:
        print('미완료 — 내일 재실행 시 자동 재개 (skip_cached)')
    print(f'{"="*60}')


if __name__ == '__main__':
    main()
