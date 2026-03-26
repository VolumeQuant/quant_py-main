"""pykrx 백테스트용 캐시 수집 — 매일(시총/펀더멘털) + 분기(섹터)

all_ohlcv에서 실제 거래일 추출 → 캐시 없는 날짜만 순차 수집.
절대 병렬 금지 — 1건씩 순차, 호출 간 1초 sleep.

Usage:
    python collect_pykrx_backtest.py                  # 전체 (2020~2024)
    python collect_pykrx_backtest.py --year 2022      # 특정 연도만
    python collect_pykrx_backtest.py --check           # 현황만 확인
"""
import sys
import time
import glob
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from pykrx import stock as pykrx_stock

import krx_auth
krx_auth.login()

CACHE_DIR = Path(__file__).parent / 'data_cache'

# 섹터 인덱스 코드 (분기 수집용)
SECTOR_INDICES = {
    '1005': '음식료', '1006': '섬유/의류', '1007': '종이/목재',
    '1008': '화학', '1009': '바이오/제약', '1010': '비금속',
    '1011': '금속', '1012': '기계', '1013': '전기전자',
    '1014': '의료정밀', '1015': '운수장비', '1016': '유통',
    '1017': '전기가스', '1018': '건설', '1019': '운수창고',
    '1020': '통신', '1021': '금융', '1024': '증권', '1025': '보험',
    '1026': '서비스', '1045': '부동산', '1046': 'IT서비스', '1047': '엔터/문화',
    '2012': '서비스', '2026': '건설', '2027': '유통',
    '2029': '운수창고', '2031': '금융', '2037': '엔터/문화',
    '2056': '음식료', '2058': '섬유/의류', '2062': '종이/목재',
    '2063': '출판/매체', '2065': '화학', '2066': '제약',
    '2067': '비금속', '2068': '금속', '2070': '기계',
    '2072': '전기전자', '2074': '의료정밀', '2075': '운수장비',
    '2077': '기타제조', '2114': '통신', '2118': 'IT서비스',
}


def get_trading_days(start_year=2020, end_year=2024):
    """all_ohlcv에서 실제 거래일 목록 추출"""
    ohlcv_file = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                        key=lambda f: f.stem.split('_')[2])[0]
    print(f'거래일 소스: {ohlcv_file.name}')
    df = pd.read_parquet(ohlcv_file)
    dates = df.index
    mask = (dates >= f'{start_year}-01-01') & (dates <= f'{end_year}-12-31')
    trading_days = sorted(dates[mask].strftime('%Y%m%d').tolist())
    return trading_days


def get_existing_dates(prefix):
    """이미 캐시된 날짜 set 반환"""
    pattern = str(CACHE_DIR / f'{prefix}_*.parquet')
    existing = set()
    for f in glob.glob(pattern):
        d = Path(f).stem.split('_')[-1]
        if d.isdigit() and len(d) == 8:
            existing.add(d)
    return existing


def collect_market_cap(date_str):
    """market_cap_ALL 수집 (KOSPI + KOSDAQ)"""
    cache = CACHE_DIR / f'market_cap_ALL_{date_str}.parquet'
    if cache.exists():
        return True, 'cached'
    try:
        df_kospi = pykrx_stock.get_market_cap(date_str, market='KOSPI')
        time.sleep(1)
        df_kosdaq = pykrx_stock.get_market_cap(date_str, market='KOSDAQ')
        time.sleep(1)
        if df_kospi.empty and df_kosdaq.empty:
            return False, 'empty'
        df = pd.concat([df_kospi, df_kosdaq])
        df.to_parquet(cache)
        return True, f'{len(df)}'
    except Exception as e:
        time.sleep(2)
        return False, str(e)[:50]


def collect_fundamental(date_str):
    """fundamental_batch_ALL 수집 (KOSPI + KOSDAQ)"""
    cache = CACHE_DIR / f'fundamental_batch_ALL_{date_str}.parquet'
    if cache.exists():
        return True, 'cached'
    try:
        df_kospi = pykrx_stock.get_market_fundamental(date_str, market='KOSPI')
        time.sleep(1)
        df_kosdaq = pykrx_stock.get_market_fundamental(date_str, market='KOSDAQ')
        time.sleep(1)
        if df_kospi.empty and df_kosdaq.empty:
            return False, 'empty'
        df = pd.concat([df_kospi, df_kosdaq])
        df.to_parquet(cache)
        return True, f'{len(df)}'
    except Exception as e:
        time.sleep(2)
        return False, str(e)[:50]


def collect_sector(date_str):
    """krx_sector 수집 (37개 업종지수 순회)"""
    cache = CACHE_DIR / f'krx_sector_{date_str}.parquet'
    if cache.exists():
        return True, 'cached'
    rows = []
    for idx_code, sector_name in SECTOR_INDICES.items():
        try:
            tickers = pykrx_stock.get_index_portfolio_deposit_file(idx_code, date_str)
            for t in tickers:
                rows.append({'종목코드': t, '업종명': sector_name})
            time.sleep(0.5)
        except Exception:
            continue
    if rows:
        sector_df = pd.DataFrame(rows)
        sector_df = sector_df.drop_duplicates(subset='종목코드', keep='first')
        sector_df.to_parquet(cache, index=False)
        return True, f'{len(sector_df)}'
    return False, 'no data'


def get_quarter_end_dates(trading_days):
    """거래일 목록에서 분기 마지막 거래일 추출"""
    df = pd.DataFrame({'date': trading_days})
    df['dt'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df['quarter'] = df['dt'].dt.to_period('Q')
    quarter_ends = df.groupby('quarter')['date'].last().tolist()
    return quarter_ends


def check_status(trading_days):
    """현재 캐시 현황 표시"""
    mcap_exists = get_existing_dates('market_cap_ALL')
    fund_exists = get_existing_dates('fundamental_batch_ALL')
    sector_exists = get_existing_dates('krx_sector')

    mcap_need = [d for d in trading_days if d not in mcap_exists]
    fund_need = [d for d in trading_days if d not in fund_exists]
    quarter_ends = get_quarter_end_dates(trading_days)
    sector_need = [d for d in quarter_ends if d not in sector_exists]

    print(f'=== 캐시 현황 ===')
    print(f'총 거래일: {len(trading_days)}')
    print(f'market_cap:   {len(trading_days)-len(mcap_need)}/{len(trading_days)} (수집필요: {len(mcap_need)})')
    print(f'fundamental:  {len(trading_days)-len(fund_need)}/{len(trading_days)} (수집필요: {len(fund_need)})')
    print(f'sector (분기): {len(quarter_ends)-len(sector_need)}/{len(quarter_ends)} (수집필요: {len(sector_need)})')

    total_calls = len(mcap_need) * 2 + len(fund_need) * 2 + len(sector_need) * 37
    est_minutes = total_calls * 1.2 / 60
    print(f'\n예상 API 호출: ~{total_calls:,}건')
    print(f'예상 소요시간: ~{est_minutes:.0f}분')
    return mcap_need, fund_need, sector_need


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', type=int, help='특정 연도만 수집')
    parser.add_argument('--start', type=int, help='시작 연도')
    parser.add_argument('--end', type=int, help='종료 연도')
    parser.add_argument('--check', action='store_true', help='현황만 확인')
    args = parser.parse_args()

    if args.year:
        start_year = end_year = args.year
    elif args.start or args.end:
        start_year = args.start or 2020
        end_year = args.end or 2026
    else:
        start_year = 2020
        end_year = 2024

    print(f'=== pykrx 백테스트 캐시 수집 ({start_year}~{end_year}) ===')
    trading_days = get_trading_days(start_year, end_year)
    print(f'거래일: {len(trading_days)}일 ({trading_days[0]} ~ {trading_days[-1]})')

    mcap_need, fund_need, sector_need = check_status(trading_days)

    if args.check:
        return

    # --- Phase 1: market_cap + fundamental (매일) ---
    # 두 데이터를 같은 날짜에 한번에 수집 (호출 최소화)
    all_daily_dates = sorted(set(mcap_need) | set(fund_need))
    mcap_need_set = set(mcap_need)
    fund_need_set = set(fund_need)

    if all_daily_dates:
        print(f'\n--- Phase 1: 일별 market_cap + fundamental ({len(all_daily_dates)}일) ---')
        mcap_ok = mcap_fail = fund_ok = fund_fail = 0
        t0 = time.time()

        for i, date_str in enumerate(all_daily_dates):
            # market_cap
            if date_str in mcap_need_set:
                ok, msg = collect_market_cap(date_str)
                if ok:
                    mcap_ok += 1
                else:
                    mcap_fail += 1

            # fundamental
            if date_str in fund_need_set:
                ok, msg = collect_fundamental(date_str)
                if ok:
                    fund_ok += 1
                else:
                    fund_fail += 1

            # 진행률 (100일마다)
            if (i + 1) % 100 == 0 or i == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
                remaining = (len(all_daily_dates) - i - 1) / rate if rate > 0 else 0
                print(f'  [{i+1}/{len(all_daily_dates)}] mcap:{mcap_ok}ok/{mcap_fail}fail '
                      f'fund:{fund_ok}ok/{fund_fail}fail | {rate:.0f}일/분 | 남은: ~{remaining:.0f}분')

        elapsed = time.time() - t0
        print(f'\nPhase 1 완료: {elapsed/60:.1f}분')
        print(f'  market_cap: {mcap_ok} 성공, {mcap_fail} 실패')
        print(f'  fundamental: {fund_ok} 성공, {fund_fail} 실패')

    # --- Phase 2: sector (분기말만) ---
    if sector_need:
        print(f'\n--- Phase 2: 분기별 sector ({len(sector_need)}일) ---')
        sec_ok = sec_fail = 0

        for i, date_str in enumerate(sector_need):
            ok, msg = collect_sector(date_str)
            status = 'OK' if ok else 'FAIL'
            print(f'  [{i+1}/{len(sector_need)}] {date_str} sector: {status} ({msg})')
            if ok:
                sec_ok += 1
            else:
                sec_fail += 1
            time.sleep(2)

        print(f'Phase 2 완료: sector {sec_ok} 성공, {sec_fail} 실패')

    # --- 갭 검증 ---
    print('\n=== market_cap 120일 갭 검증 ===')
    mcap_dates = sorted(get_existing_dates('market_cap_ALL'))
    violations = 0
    for j in range(1, len(mcap_dates)):
        d1 = datetime.strptime(mcap_dates[j-1], '%Y%m%d')
        d2 = datetime.strptime(mcap_dates[j], '%Y%m%d')
        gap = (d2 - d1).days
        if gap > 120:
            print(f'  {mcap_dates[j-1]} -> {mcap_dates[j]}: {gap}일 초과')
            violations += 1
    if violations == 0:
        print('  120일 초과 갭 없음 — OK')
    else:
        print(f'  {violations}개 갭 초과 발견')

    print('\n=== 전체 완료 ===')


if __name__ == '__main__':
    main()
