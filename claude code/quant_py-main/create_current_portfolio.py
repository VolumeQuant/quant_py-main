"""
2026년 1월 현재 포트폴리오 생성 (리팩토링 버전)

개선사항:
- OpenDART API를 통한 재무제표 수집 (빠르고 안정적)
- 비동기 처리 (asyncio + aiohttp)
- 병렬 처리 (ThreadPoolExecutor)
- Skip & Log 에러 처리 패턴
- 런타임: ~50분 → ~5-10분
"""

import pandas as pd
import numpy as np
import asyncio
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings('ignore')

# 내부 모듈
from data_collector import DataCollector
from dart_api import DartApiClient, DartConfig, calculate_ttm
from fnguide_crawler import get_consensus_batch_async
from error_handler import ErrorTracker, ErrorCategory
from strategy_a_magic import MagicFormulaStrategy
from strategy_b_multifactor import MultiFactorStrategy

# 설정
try:
    from config import (
        MIN_MARKET_CAP, MIN_TRADING_VALUE, DART_API_KEY,
        MAX_CONCURRENT_REQUESTS, PYKRX_WORKERS, CACHE_DIR
    )
except ImportError:
    # 기본값
    MIN_MARKET_CAP = 1000
    MIN_TRADING_VALUE = 50
    DART_API_KEY = None
    MAX_CONCURRENT_REQUESTS = 10
    PYKRX_WORKERS = 10
    CACHE_DIR = "data_cache"

# 최근 거래일 자동 탐지
from pykrx import stock as pykrx_stock

def get_latest_trading_date() -> str:
    """최근 거래일 찾기"""
    today = datetime.now()
    for i in range(1, 20):
        date = (today - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = pykrx_stock.get_market_cap(date, market='KOSPI')
            if not df.empty and df['시가총액'].sum() > 0:
                return date
        except:
            continue
    return '20260129'  # 기본값

BASE_DATE = get_latest_trading_date()
N_STOCKS = 30
OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# 제외 키워드 (금융업/지주사)
EXCLUDE_KEYWORDS = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                   '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT']


async def collect_financial_data_dart(
    tickers: List[str],
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """
    OpenDART API를 통한 재무제표 수집

    Returns:
        마법공식용 재무 데이터 DataFrame
    """
    print("\n[DART API] 재무제표 수집 시작")
    print(f"  대상 종목: {len(tickers)}개")

    if not DART_API_KEY:
        error_tracker.log_warning("SYSTEM", "DART API 키가 설정되지 않음. FnGuide 캐시 사용")
        return pd.DataFrame()

    # DartConfig 생성
    config = DartConfig(
        api_key=DART_API_KEY,
        cache_dir=Path(CACHE_DIR),
        max_concurrent=MAX_CONCURRENT_REQUESTS
    )

    async with DartApiClient(config) as client:
        # 배치로 재무제표 수집 (연간 + 분기)
        fs_data = await client.get_financial_statements_batch(
            tickers=tickers,
            years=[2024, 2025, 2026]  # 최근 3년
        )

    if not fs_data:
        print("  [경고] DART API로 수집된 데이터 없음")
        return pd.DataFrame()

    print(f"  수집 완료: {len(fs_data)}개 종목")

    # TTM 계산 및 마법공식 데이터 추출
    result_data = []

    for ticker, df in fs_data.items():
        if df is None or df.empty:
            error_tracker.log_warning(ticker, "재무데이터 없음")
            continue

        try:
            # TTM 계산
            ttm_df = calculate_ttm(df)

            if ttm_df.empty:
                continue

            # 최신 TTM 데이터 추출
            latest = ttm_df.iloc[-1]

            # 마법공식에 필요한 지표 추출
            row = {
                '종목코드': ticker,
                '매출액': latest.get('매출액', np.nan),
                '영업이익': latest.get('영업이익', np.nan),
                '당기순이익': latest.get('당기순이익', np.nan),
                '자산': latest.get('자산', np.nan),
                '부채': latest.get('부채', np.nan),
                '자본': latest.get('자본', np.nan),
            }

            # 마법공식 지표 계산
            # EBIT = 영업이익
            ebit = row['영업이익']

            # 투하자본 = 자산 - 부채 (간소화된 계산)
            # 또는: 영업자산 - 영업부채
            invested_capital = row['자산'] - row['부채'] if pd.notna(row['자산']) and pd.notna(row['부채']) else np.nan

            row['EBIT'] = ebit
            row['투하자본'] = invested_capital

            result_data.append(row)
            error_tracker.mark_success(ticker)

        except Exception as e:
            error_tracker.log_error(ticker, ErrorCategory.PARSE_ERROR, "TTM 계산 실패", e)
            continue

    if not result_data:
        return pd.DataFrame()

    return pd.DataFrame(result_data)


async def collect_consensus_data(
    tickers: List[str],
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """
    FnGuide 컨센서스 데이터 수집 (비동기)
    """
    print("\n[FnGuide] 컨센서스 데이터 수집")
    print(f"  대상 종목: {len(tickers)}개")

    try:
        consensus_df = await get_consensus_batch_async(
            tickers=tickers,
            delay=0.3,
            max_concurrent=5,
            timeout=30
        )
        print(f"  수집 완료: {len(consensus_df)}개 종목")
        return consensus_df
    except Exception as e:
        error_tracker.log_error("CONSENSUS", ErrorCategory.NETWORK, "컨센서스 수집 실패", e)
        return pd.DataFrame()


def collect_price_data_parallel(
    collector: DataCollector,
    tickers: List[str],
    start_date: str,
    end_date: str,
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """
    병렬 처리로 OHLCV 데이터 수집
    """
    print("\n[OHLCV] 주가 데이터 수집 (병렬)")
    print(f"  대상 종목: {len(tickers)}개")
    print(f"  기간: {start_date} ~ {end_date}")

    try:
        price_df = collector.get_ohlcv_parallel(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date
        )
        print(f"  수집 완료: {len(price_df.columns)}개 종목, {len(price_df)}거래일")
        return price_df
    except Exception as e:
        error_tracker.log_error("OHLCV", ErrorCategory.NETWORK, "주가 데이터 수집 실패", e)
        return pd.DataFrame()


def filter_universe_optimized(
    collector: DataCollector,
    market_cap_df: pd.DataFrame,
    error_tracker: ErrorTracker
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """
    유니버스 필터링 (최적화 버전)

    Returns:
        (필터링된 DataFrame, 종목명 딕셔너리)
    """
    print("\n[유니버스 필터링]")
    print(f"전체 종목 수: {len(market_cap_df)}")

    # 1. 시가총액 필터
    market_cap_df = market_cap_df.copy()
    market_cap_df['시가총액_억'] = market_cap_df['시가총액'] / 100_000_000
    filtered = market_cap_df[market_cap_df['시가총액_억'] >= MIN_MARKET_CAP].copy()
    print(f"시가총액 {MIN_MARKET_CAP}억원 이상: {len(filtered)}개")

    # 2. 거래대금 필터
    filtered['거래대금_억'] = filtered['거래대금'] / 100_000_000
    filtered = filtered[filtered['거래대금_억'] >= MIN_TRADING_VALUE].copy()
    print(f"거래대금 {MIN_TRADING_VALUE}억원 이상: {len(filtered)}개")

    # 3. 종목명 병렬 수집
    print("종목명 수집 중 (병렬)...")
    ticker_names = collector.get_ticker_names_parallel(
        filtered.index.tolist()
    )
    filtered['종목명'] = filtered.index.map(ticker_names)

    # 4. 금융업/지주사 제외
    mask = ~filtered['종목명'].str.contains('|'.join(EXCLUDE_KEYWORDS), na=False)
    filtered = filtered[mask].copy()
    print(f"금융업/지주사 제외 후: {len(filtered)}개")

    return filtered, ticker_names


async def run_strategy_a(
    magic_df: pd.DataFrame,
    universe_df: pd.DataFrame,
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """
    전략 A (마법공식) 실행
    """
    print("\n[전략 A] 마법공식 실행")

    if magic_df.empty:
        print("  데이터 없음 - 스킵")
        return pd.DataFrame()

    try:
        # 시가총액 데이터 추가
        magic_df_with_mcap = magic_df.merge(
            universe_df[['시가총액', '종목명']],
            left_on='종목코드',
            right_index=True,
            how='left'
        )
        magic_df_with_mcap['시가총액'] = magic_df_with_mcap['시가총액'] / 100_000_000

        # 전략 실행
        strategy = MagicFormulaStrategy()
        selected, scored = strategy.run(magic_df_with_mcap, n_stocks=N_STOCKS)

        print(f"  선정 종목: {len(selected)}개")
        return selected

    except Exception as e:
        error_tracker.log_error("STRATEGY_A", ErrorCategory.UNKNOWN, "마법공식 실행 실패", e)
        return pd.DataFrame()


async def run_strategy_b(
    magic_df: pd.DataFrame,
    price_df: pd.DataFrame,
    universe_df: pd.DataFrame,
    ticker_names: Dict[str, str],
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """
    전략 B (멀티팩터) 실행
    """
    print("\n[전략 B] 멀티팩터 실행")

    if magic_df.empty:
        print("  데이터 없음 - 스킵")
        return pd.DataFrame()

    try:
        # 데이터 준비
        multifactor_df = magic_df.copy()
        multifactor_df['종목명'] = multifactor_df['종목코드'].map(ticker_names)

        # 시가총액 및 섹터 정보 추가
        multifactor_df = multifactor_df.merge(
            universe_df[['시가총액', '섹터']],
            left_on='종목코드',
            right_index=True,
            how='left'
        )
        multifactor_df['시가총액'] = multifactor_df['시가총액'] / 100_000_000

        # 전략 실행
        strategy = MultiFactorStrategy()
        selected, scored = strategy.run(multifactor_df, price_df=price_df, n_stocks=N_STOCKS)

        print(f"  선정 종목: {len(selected)}개")
        return selected

    except Exception as e:
        error_tracker.log_error("STRATEGY_B", ErrorCategory.UNKNOWN, "멀티팩터 실행 실패", e)
        return pd.DataFrame()


def generate_report(
    selected_a: pd.DataFrame,
    selected_b: pd.DataFrame,
    universe_df: pd.DataFrame,
    market_cap_df: pd.DataFrame,
    ticker_names: Dict[str, str],
    error_tracker: ErrorTracker
) -> str:
    """
    최종 리포트 생성
    """
    # 공통 종목 찾기
    tickers_a = set(selected_a['종목코드'].tolist()) if not selected_a.empty else set()
    tickers_b = set(selected_b['종목코드'].tolist()) if not selected_b.empty else set()
    common_tickers = tickers_a & tickers_b

    # 에러 요약
    error_summary = error_tracker.get_summary()

    report = f"""
================================================================================
2026년 1월 포트폴리오 분석 리포트 (리팩토링 버전)
기준일: {BASE_DATE}
생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
================================================================================

[유니버스]
- 전체 종목: {len(market_cap_df)}개
- 필터링 후: {len(universe_df)}개
- 필터 조건:
  * 시가총액 >= {MIN_MARKET_CAP}억원
  * 거래대금 >= {MIN_TRADING_VALUE}억원
  * 금융업/지주사 제외

[전략 A - 마법공식]
- 선정 종목 수: {len(selected_a)}개
"""

    if not selected_a.empty and '종목명' in selected_a.columns:
        report += f"- 상위 10종목:\n{selected_a.head(10)[['종목코드', '종목명', '마법공식_순위']].to_string()}\n"

    report += f"""
[전략 B - 멀티팩터]
- 선정 종목 수: {len(selected_b)}개
"""

    if not selected_b.empty and '종목명' in selected_b.columns:
        report += f"- 상위 10종목:\n{selected_b.head(10)[['종목코드', '종목명', '멀티팩터_순위']].to_string()}\n"

    report += f"""
[공통 종목]
- 공통 선정: {len(common_tickers)}개
- 종목: {', '.join([f"{ticker_names.get(t, t)}({t})" for t in common_tickers])}

[에러 요약]
- 총 에러: {error_summary['total_errors']}건
- 실패 종목: {error_summary['failed_ticker_count']}개
- 경고: {error_summary['warning_count']}건

================================================================================
"""
    return report


async def main_async():
    """
    메인 함수 (비동기)
    """
    start_time = datetime.now()

    print("=" * 80)
    print("2026년 1월 현재 포트폴리오 생성 (리팩토링 버전)")
    print(f"기준일: {BASE_DATE}")
    print(f"데이터 소스: OpenDART API + FnGuide (컨센서스)")
    print("=" * 80)

    # 에러 추적기 초기화
    error_tracker = ErrorTracker(log_dir=Path("logs"), name="portfolio")
    error_tracker.log_info(f"포트폴리오 생성 시작 - 기준일: {BASE_DATE}")

    # DataCollector 초기화
    collector = DataCollector(start_date='20150101', end_date='20261231')

    # =========================================================================
    # 1단계: 시가총액 데이터 수집
    # =========================================================================
    print("\n[1단계] 시가총액 데이터 수집")

    market_cap_df = collector.get_market_cap_batch(BASE_DATE, markets=['KOSPI', 'KOSDAQ'])
    print(f"전체 종목 수: {len(market_cap_df)}")

    # =========================================================================
    # 2단계: 유니버스 필터링
    # =========================================================================
    print("\n[2단계] 유니버스 필터링")

    universe_df, ticker_names = filter_universe_optimized(
        collector, market_cap_df, error_tracker
    )
    universe_tickers = universe_df.index.tolist()
    print(f"최종 유니버스: {len(universe_tickers)}개 종목")

    # =========================================================================
    # 3단계: 재무제표 수집 (DART API)
    # =========================================================================
    print("\n[3단계] 재무제표 수집 (DART API)")

    magic_df = await collect_financial_data_dart(universe_tickers, error_tracker)

    # DART 실패 시 FnGuide 캐시 시도
    if magic_df.empty:
        print("  DART 데이터 없음 - FnGuide 캐시 시도")
        try:
            from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data
            fs_data = get_all_financial_statements(universe_tickers, use_cache=True)
            magic_df = extract_magic_formula_data(fs_data, base_date=BASE_DATE, use_ttm=True)
            print(f"  FnGuide 캐시에서 {len(magic_df)}개 종목 로드")
        except Exception as e:
            error_tracker.log_error("FNGUIDE", ErrorCategory.UNKNOWN, "FnGuide 캐시 로드 실패", e)

    # 자본잠식 종목 필터링
    if not magic_df.empty and '자본' in magic_df.columns:
        before_count = len(magic_df)
        magic_df = magic_df[magic_df['자본'] > 0].copy()
        filtered_count = before_count - len(magic_df)
        print(f"자본잠식 종목 제외: {filtered_count}개 → {len(magic_df)}개 남음")

    # =========================================================================
    # 4단계: OHLCV 수집 (병렬)
    # =========================================================================
    print("\n[4단계] OHLCV 데이터 수집 (병렬)")

    end_date_dt = datetime.strptime(BASE_DATE, '%Y%m%d')
    start_date_dt = end_date_dt - timedelta(days=450)
    price_start = start_date_dt.strftime('%Y%m%d')

    price_df = collect_price_data_parallel(
        collector, universe_tickers, price_start, BASE_DATE, error_tracker
    )

    # =========================================================================
    # 5단계: 전략 실행
    # =========================================================================
    selected_a = await run_strategy_a(magic_df, universe_df, error_tracker)
    selected_b = await run_strategy_b(magic_df, price_df, universe_df, ticker_names, error_tracker)

    # =========================================================================
    # 6단계: 결과 저장
    # =========================================================================
    print("\n[6단계] 결과 저장")

    if not selected_a.empty:
        output_path_a = OUTPUT_DIR / 'portfolio_2026_01_strategy_a.csv'
        selected_a.to_csv(output_path_a, index=False, encoding='utf-8-sig')
        print(f"  전략 A: {output_path_a}")

    if not selected_b.empty:
        output_path_b = OUTPUT_DIR / 'portfolio_2026_01_strategy_b.csv'
        selected_b.to_csv(output_path_b, index=False, encoding='utf-8-sig')
        print(f"  전략 B: {output_path_b}")

    # 리포트 생성
    report = generate_report(
        selected_a, selected_b, universe_df, market_cap_df,
        ticker_names, error_tracker
    )

    report_path = OUTPUT_DIR / 'portfolio_2026_01_report.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"  리포트: {report_path}")

    # 에러 로그 저장
    if error_tracker.errors:
        error_tracker.save_error_log()

    # =========================================================================
    # 완료
    # =========================================================================
    elapsed = datetime.now() - start_time

    print("\n" + "=" * 80)
    print("포트폴리오 생성 완료!")
    print(f"소요 시간: {elapsed.total_seconds():.1f}초 ({elapsed.total_seconds()/60:.1f}분)")
    error_tracker.print_summary()
    print("=" * 80)

    return selected_a, selected_b


def main():
    """
    동기 래퍼 (호환성)
    """
    return asyncio.run(main_async())


if __name__ == '__main__':
    main()
