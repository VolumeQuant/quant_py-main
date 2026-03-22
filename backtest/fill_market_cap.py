"""시가총액 캐시 역산 보충 스크립트

OHLCV 종가 × 상장주식수로 market_cap 파일을 생성.
KRX 전종목 벌크 API 차단 대응.
"""
import sys
import time
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

DATA_DIR = Path(__file__).parent.parent / 'data_cache'


def load_shares_outstanding():
    """기존 market_cap 파일들에서 상장주식수 타임라인 구축

    Returns:
        dict: {date_str: DataFrame(index=ticker, columns=['상장주식수'])}
    """
    mc_files = sorted(DATA_DIR.glob('market_cap_ALL_*.parquet'))
    shares_timeline = {}
    for f in mc_files:
        d = f.stem.split('_')[-1]
        df = pd.read_parquet(f)
        if '상장주식수' in df.columns:
            shares_timeline[d] = df[['상장주식수']]
    return shares_timeline


def get_nearest_shares(shares_timeline, target_date):
    """target_date에 가장 가까운 상장주식수 반환"""
    dates = sorted(shares_timeline.keys())
    # target_date 이하 중 가장 큰 날짜
    before = [d for d in dates if d <= target_date]
    after = [d for d in dates if d > target_date]

    if before:
        return shares_timeline[before[-1]]
    elif after:
        return shares_timeline[after[0]]
    return None


def main():
    t0 = time.time()

    # 1. OHLCV 로드
    ohlcv_files = sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))
    ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])  # 시작일 기준
    ohlcv = pd.read_parquet(ohlcv_files[0])
    print(f'OHLCV: {ohlcv.shape[0]}일 × {ohlcv.shape[1]}종목')

    # 2. 상장주식수 타임라인
    shares_timeline = load_shares_outstanding()
    print(f'상장주식수 기준일: {len(shares_timeline)}개')

    # 3. 기존 market_cap 날짜 목록
    existing = set()
    for f in DATA_DIR.glob('market_cap_ALL_*.parquet'):
        existing.add(f.stem.split('_')[-1])
    print(f'기존 market_cap: {len(existing)}개')

    # 4. 빈 날짜 찾기 (2021-01-01 ~ 2026-03-20)
    target_dates = []
    for dt in ohlcv.index:
        d = dt.strftime('%Y%m%d')
        if d >= '20210101' and d not in existing:
            target_dates.append((d, dt))

    print(f'생성 대상: {len(target_dates)}일')

    # 5. 역산 + 저장
    created = 0
    last_shares_date = None
    last_shares = None

    for d, dt in target_dates:
        # 상장주식수 (캐시해서 매번 탐색 안 함)
        if last_shares is None or (last_shares_date and d > last_shares_date):
            # 새 기준일 필요한지 체크 (다음 기준일이 있으면 갱신)
            dates_after = [sd for sd in shares_timeline.keys() if sd <= d]
            if dates_after:
                new_date = max(dates_after)
                if new_date != last_shares_date:
                    last_shares_date = new_date
                    last_shares = shares_timeline[new_date]

        if last_shares is None:
            last_shares = get_nearest_shares(shares_timeline, d)
            if last_shares is not None:
                last_shares_date = d

        if last_shares is None:
            continue

        # OHLCV 종가
        row = ohlcv.loc[dt]
        close_prices = row[row > 0].dropna()

        if len(close_prices) == 0:
            continue

        # 교집합 종목
        common = close_prices.index.intersection(last_shares.index)
        if len(common) == 0:
            continue

        # 시가총액 = 종가 × 상장주식수
        prices = close_prices[common]
        shares = last_shares.loc[common, '상장주식수']
        mcap = prices * shares

        # DataFrame 구성 (기존 포맷과 동일)
        result = pd.DataFrame({
            '종가': prices,
            '시가총액': mcap,
            '거래량': 0,
            '거래대금': 0,
            '상장주식수': shares,
        })
        result.index.name = '티커'

        # 저장
        out_path = DATA_DIR / f'market_cap_ALL_{d}.parquet'
        result.to_parquet(out_path)
        created += 1

        if created % 100 == 0:
            print(f'  {created}/{len(target_dates)} ({d})')

    elapsed = time.time() - t0
    print(f'\n완료: {created}개 생성, {elapsed:.1f}초')


if __name__ == '__main__':
    main()
