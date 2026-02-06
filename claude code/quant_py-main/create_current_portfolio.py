"""
퀀트 포트폴리오 생성 v3.0

파이프라인:
  유니버스(~600) → A 사전필터(150) → pykrx 실시간 PER/PBR/DIV → B 최종선정(30)

데이터 소스:
  - FnGuide 캐시: 재무제표 (Quality 팩터, PCR/PSR용)
  - pykrx 실시간: 시가총액, OHLCV, PER/PBR/DIV (Value 팩터)
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
from fnguide_crawler import get_consensus_batch
from error_handler import ErrorTracker, ErrorCategory
from strategy_a_magic import MagicFormulaStrategy
from strategy_b_multifactor import MultiFactorStrategy

# 설정
try:
    from config import (
        MIN_MARKET_CAP, MIN_TRADING_VALUE,
        MAX_CONCURRENT_REQUESTS, PYKRX_WORKERS, CACHE_DIR,
        PREFILTER_N, N_STOCKS
    )
except ImportError:
    MIN_MARKET_CAP = 1000
    MIN_TRADING_VALUE = 30
    MAX_CONCURRENT_REQUESTS = 10
    PYKRX_WORKERS = 10
    CACHE_DIR = "data_cache"
    PREFILTER_N = 150
    N_STOCKS = 30

# 최근 거래일 자동 탐지 (한국 시간 기준)
from pykrx import stock as pykrx_stock
from zoneinfo import ZoneInfo
KST = ZoneInfo('Asia/Seoul')

def get_latest_trading_date() -> str:
    """최근 거래일 찾기 (한국 시간 기준)"""
    today = datetime.now(KST)
    for i in range(1, 20):
        date = (today - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = pykrx_stock.get_market_cap(date, market='KOSPI')
            if not df.empty and df['시가총액'].sum() > 0:
                return date
        except:
            continue
    return '20260129'

BASE_DATE = get_latest_trading_date()
OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# 제외 키워드 (금융업/지주사)
EXCLUDE_KEYWORDS = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                   '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT']


def collect_consensus_data(
    tickers: List[str],
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """FnGuide 컨센서스 데이터 수집"""
    print("\n[FnGuide] 컨센서스 데이터 수집")
    print(f"  대상 종목: {len(tickers)}개")

    try:
        consensus_df = get_consensus_batch(tickers=tickers, delay=0.5)
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
    """병렬 처리로 OHLCV 데이터 수집"""
    print("\n[OHLCV] 주가 데이터 수집 (병렬)")
    print(f"  대상 종목: {len(tickers)}개")
    print(f"  기간: {start_date} ~ {end_date}")

    try:
        price_df = collector.get_all_ohlcv(
            tickers=tickers,
            start_date=start_date,
            end_date=end_date
        )
        print(f"  수집 완료: {len(price_df.columns)}개 종목, {len(price_df)}거래일")
        return price_df
    except Exception as e:
        error_tracker.log_error("OHLCV", ErrorCategory.NETWORK, "주가 데이터 수집 실패", e)
        return pd.DataFrame()


def calculate_avg_trading_value_from_cache(days: int = 20) -> pd.DataFrame:
    """OHLCV 캐시에서 20일 평균 거래대금 계산"""
    ohlcv_files = sorted(Path(CACHE_DIR).glob('all_ohlcv_*.parquet'))
    if not ohlcv_files:
        print("  OHLCV 캐시 없음")
        return pd.DataFrame()

    ohlcv_file = ohlcv_files[-1]
    print(f"  OHLCV 캐시 사용: {ohlcv_file.name}")

    price_df = pd.read_parquet(ohlcv_file)
    from pykrx import stock

    if len(price_df) < days:
        print(f"  데이터 부족: {len(price_df)}일")
        return pd.DataFrame()

    dates = price_df.index[-days:].strftime('%Y%m%d').tolist()
    print(f"  거래대금 조회: {dates[0]} ~ {dates[-1]} ({len(dates)}일)")

    trading_values = {}
    for date in dates:
        try:
            df = stock.get_market_cap(date, market='ALL')
            if not df.empty:
                for ticker in df.index:
                    if ticker not in trading_values:
                        trading_values[ticker] = []
                    trading_values[ticker].append(df.loc[ticker, '거래대금'])
        except:
            continue

    avg_values = {}
    for ticker, values in trading_values.items():
        if values:
            avg_values[ticker] = np.mean(values) / 100_000_000

    result = pd.DataFrame({'avg_trading_value': pd.Series(avg_values)})
    result.index.name = 'ticker'
    print(f"  20일 평균 거래대금 계산 완료: {len(result)}개 종목")
    return result


def filter_universe_optimized(
    collector: DataCollector,
    market_cap_df: pd.DataFrame,
    error_tracker: ErrorTracker
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """유니버스 필터링 (최적화 버전)"""
    print("\n[유니버스 필터링]")
    print(f"전체 종목 수: {len(market_cap_df)}")

    # 1. 시가총액 필터
    market_cap_df = market_cap_df.copy()
    market_cap_df['시가총액_억'] = market_cap_df['시가총액'] / 100_000_000
    filtered = market_cap_df[market_cap_df['시가총액_억'] >= MIN_MARKET_CAP].copy()
    print(f"시가총액 {MIN_MARKET_CAP}억원 이상: {len(filtered)}개")

    # 2. 거래대금 필터 (20일 평균)
    print(f"20일 평균 거래대금 계산 중...")
    avg_trading_df = calculate_avg_trading_value_from_cache(days=20)

    if not avg_trading_df.empty:
        filtered = filtered.join(avg_trading_df, how='left')
        filtered['거래대금_억'] = filtered['거래대금'] / 100_000_000
        filtered['avg_trading_value'] = filtered['avg_trading_value'].fillna(filtered['거래대금_억'])
        filtered = filtered[filtered['avg_trading_value'] >= MIN_TRADING_VALUE].copy()
        print(f"20일 평균 거래대금 {MIN_TRADING_VALUE}억원 이상: {len(filtered)}개")
    else:
        print("  (배치 실패 - 당일 거래대금 사용)")
        filtered['거래대금_억'] = filtered['거래대금'] / 100_000_000
        filtered = filtered[filtered['거래대금_억'] >= MIN_TRADING_VALUE].copy()
        print(f"당일 거래대금 {MIN_TRADING_VALUE}억원 이상: {len(filtered)}개")

    # 3. 종목명 수집
    print("종목명 수집 중...")
    ticker_names = {}
    for ticker in filtered.index.tolist():
        try:
            name = pykrx_stock.get_market_ticker_name(ticker)
            ticker_names[ticker] = name
        except:
            ticker_names[ticker] = ticker
    filtered['종목명'] = filtered.index.map(ticker_names)

    # 4. 금융업/지주사 제외
    mask = ~filtered['종목명'].str.contains('|'.join(EXCLUDE_KEYWORDS), na=False)
    filtered = filtered[mask].copy()
    print(f"금융업/지주사 제외 후: {len(filtered)}개")

    return filtered, ticker_names


async def run_strategy_a_prefilter(
    magic_df: pd.DataFrame,
    universe_df: pd.DataFrame,
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """전략 A (마법공식) - 사전 필터 (상위 PREFILTER_N개)"""
    print(f"\n[전략 A] 마법공식 사전 필터 (상위 {PREFILTER_N}개)")

    if magic_df.empty:
        print("  데이터 없음 - 스킵")
        return pd.DataFrame()

    try:
        magic_df_with_mcap = magic_df.merge(
            universe_df[['시가총액', '종목명']],
            left_on='종목코드',
            right_index=True,
            how='left'
        )
        magic_df_with_mcap['시가총액'] = magic_df_with_mcap['시가총액'] / 100_000_000

        strategy = MagicFormulaStrategy()
        selected, scored = strategy.run(magic_df_with_mcap, n_stocks=PREFILTER_N)

        print(f"  사전 필터 통과: {len(selected)}개 종목")
        return selected

    except Exception as e:
        error_tracker.log_error("STRATEGY_A", ErrorCategory.UNKNOWN, "마법공식 사전 필터 실패", e)
        return pd.DataFrame()


async def run_strategy_b_scoring(
    prefiltered_df: pd.DataFrame,
    fundamental_df: pd.DataFrame,
    price_df: pd.DataFrame,
    ticker_names: Dict[str, str],
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """전략 B (멀티팩터) - 150개 전체 스코어링 (pykrx 실시간 PER/PBR/DIV 포함)"""
    print(f"\n[전략 B] 멀티팩터 전체 스코어링 ({len(prefiltered_df)}개)")

    if prefiltered_df.empty:
        print("  사전 필터 데이터 없음 - 스킵")
        return pd.DataFrame()

    try:
        multifactor_df = prefiltered_df.copy()
        multifactor_df['종목명'] = multifactor_df['종목코드'].map(ticker_names)

        # pykrx 실시간 PER/PBR/DIV 병합
        if not fundamental_df.empty:
            live_cols = {}
            if 'PER' in fundamental_df.columns:
                live_cols['PER'] = 'PER_live'
            if 'PBR' in fundamental_df.columns:
                live_cols['PBR'] = 'PBR_live'
            if 'DIV' in fundamental_df.columns:
                live_cols['DIV'] = 'DIV_live'

            if live_cols:
                fund_subset = fundamental_df[list(live_cols.keys())].rename(columns=live_cols)
                multifactor_df = multifactor_df.merge(
                    fund_subset,
                    left_on='종목코드',
                    right_index=True,
                    how='left'
                )
                live_count = multifactor_df['PER_live'].notna().sum() if 'PER_live' in multifactor_df.columns else 0
                print(f"  pykrx 실시간 데이터 병합: {live_count}/{len(multifactor_df)}개 종목")

        strategy = MultiFactorStrategy()
        selected, scored = strategy.run(multifactor_df, price_df=price_df, n_stocks=len(multifactor_df))

        print(f"  스코어링 완료: {len(scored)}개 종목")
        return scored

    except Exception as e:
        error_tracker.log_error("STRATEGY_B", ErrorCategory.UNKNOWN, "멀티팩터 스코어링 실패", e)
        return pd.DataFrame()


def generate_report(
    prefiltered: pd.DataFrame,
    selected: pd.DataFrame,
    universe_df: pd.DataFrame,
    market_cap_df: pd.DataFrame,
    ticker_names: Dict[str, str],
    error_tracker: ErrorTracker
) -> str:
    """최종 리포트 생성"""
    error_summary = error_tracker.get_summary()

    base_dt = datetime.strptime(BASE_DATE, '%Y%m%d')

    report = f"""
================================================================================
퀀트 포트폴리오 리포트 v3.0
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

[사전 필터 - 마법공식 상위 {PREFILTER_N}개]
- 통과 종목 수: {len(prefiltered)}개
"""

    if not prefiltered.empty and '종목명' in prefiltered.columns:
        report += f"- 상위 10종목:\n{prefiltered.head(10)[['종목코드', '종목명', '마법공식_순위']].to_string()}\n"

    report += f"""
[최종 포트폴리오 - 통합순위 상위 {N_STOCKS}개]
- 선정 종목 수: {len(selected)}개
- 통합순위: 마법공식 50% + 멀티팩터 50%
- Value 팩터: PER(실시간) + PBR(실시간) + PCR + PSR + DIV(실시간)
- Quality 팩터: ROE + GPA + CFO
- Momentum 팩터: 12M-1M 수익률
"""

    if not selected.empty and '종목명' in selected.columns:
        cols = ['종목코드', '종목명', '통합순위', '마법공식_순위', '멀티팩터_순위']
        available_cols = [c for c in cols if c in selected.columns]
        report += f"- 상위 10종목:\n{selected.head(10)[available_cols].to_string()}\n"

    report += f"""
[에러 요약]
- 총 에러: {error_summary['total_errors']}건
- 실패 종목: {error_summary['failed_ticker_count']}개
- 경고: {error_summary['warning_count']}건

================================================================================
"""
    return report


async def main_async():
    """메인 함수 (비동기)"""
    start_time = datetime.now()
    base_dt = datetime.strptime(BASE_DATE, '%Y%m%d')

    print("=" * 80)
    print("퀀트 포트폴리오 생성 v3.0")
    print(f"기준일: {BASE_DATE}")
    print(f"파이프라인: 유니버스 → A 사전필터({PREFILTER_N}) → A50%+B50% 통합순위 → 최종{N_STOCKS}개")
    print(f"데이터 소스: FnGuide 캐시 + pykrx 실시간 PER/PBR/DIV")
    print("=" * 80)

    error_tracker = ErrorTracker(log_dir=Path("logs"), name="portfolio")
    error_tracker.log_info(f"포트폴리오 생성 시작 - 기준일: {BASE_DATE}")

    collector = DataCollector(start_date='20150101', end_date='20261231')

    # =========================================================================
    # 1단계: 시가총액 데이터 수집
    # =========================================================================
    print("\n[1단계] 시가총액 데이터 수집")
    market_cap_df = collector.get_market_cap(BASE_DATE, market='ALL')
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
    # 3단계: 재무제표 수집 (FnGuide 캐시)
    # =========================================================================
    print("\n[3단계] 재무제표 수집 (FnGuide 캐시)")
    try:
        from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data
        fs_data = get_all_financial_statements(universe_tickers, use_cache=True)
        magic_df = extract_magic_formula_data(fs_data, base_date=BASE_DATE, use_ttm=True)
        print(f"  FnGuide 캐시에서 {len(magic_df)}개 종목 로드")
    except Exception as e:
        error_tracker.log_error("FNGUIDE", ErrorCategory.UNKNOWN, "FnGuide 캐시 로드 실패", e)
        magic_df = pd.DataFrame()

    # 자본잠식 종목 필터링
    if not magic_df.empty and '자본' in magic_df.columns:
        before_count = len(magic_df)
        magic_df = magic_df[magic_df['자본'] > 0].copy()
        filtered_count = before_count - len(magic_df)
        print(f"자본잠식 종목 제외: {filtered_count}개 → {len(magic_df)}개 남음")

    # =========================================================================
    # 3.5단계: pykrx 실시간 펀더멘털 수집 (PER/PBR/DIV)
    # =========================================================================
    print("\n[3.5단계] pykrx 실시간 펀더멘털 수집 (PER/PBR/DIV)")
    fundamental_df = collector.get_market_fundamental_batch(BASE_DATE)
    if not fundamental_df.empty:
        print(f"  pykrx 펀더멘털: {len(fundamental_df)}개 종목 (PER/PBR/EPS/BPS/DIV)")
    else:
        print("  pykrx 펀더멘털 수집 실패 - FnGuide 캐시로 fallback")

    # =========================================================================
    # 4단계: OHLCV 수집 (병렬)
    # =========================================================================
    print("\n[4단계] OHLCV 데이터 로드 (캐시)")

    ohlcv_cache_files = list(Path(CACHE_DIR).glob("all_ohlcv_*.parquet"))
    price_df = pd.DataFrame()
    need_refresh = True

    if ohlcv_cache_files:
        ohlcv_cache_file = sorted(ohlcv_cache_files)[-1]
        print(f"  캐시 파일 확인: {ohlcv_cache_file.name}")
        price_df = pd.read_parquet(ohlcv_cache_file)

        base_date_dt = pd.Timestamp(datetime.strptime(BASE_DATE, '%Y%m%d'))
        if not price_df.empty and base_date_dt in price_df.index:
            print(f"  캐시에 {BASE_DATE} 데이터 있음 - 캐시 사용")
            print(f"  로드 완료: {len(price_df.columns)}개 종목, {len(price_df)}거래일")
            need_refresh = False
        else:
            print(f"  캐시에 {BASE_DATE} 데이터 없음 - 새로 수집 필요")

    if need_refresh:
        print("  OHLCV 데이터 수집 시작...")
        end_date_dt = datetime.strptime(BASE_DATE, '%Y%m%d')
        start_date_dt = end_date_dt - timedelta(days=450)
        price_start = start_date_dt.strftime('%Y%m%d')
        price_df = collect_price_data_parallel(
            collector, universe_tickers, price_start, BASE_DATE, error_tracker
        )

    # =========================================================================
    # 5단계: 전략 실행 (A 사전필터 → B 스코어링 → A+B 통합순위)
    # =========================================================================
    prefiltered = await run_strategy_a_prefilter(magic_df, universe_df, error_tracker)
    scored_b = await run_strategy_b_scoring(
        prefiltered, fundamental_df, price_df, ticker_names, error_tracker
    )

    # A 50% + B 50% 통합순위로 최종 30개 선정
    print(f"\n[통합순위] 마법공식 50% + 멀티팩터 50%")
    if not scored_b.empty and '마법공식_순위' in scored_b.columns and '멀티팩터_순위' in scored_b.columns:
        scored_b['통합순위_점수'] = scored_b['마법공식_순위'] * 0.5 + scored_b['멀티팩터_순위'] * 0.5
        scored_b['통합순위'] = scored_b['통합순위_점수'].rank(ascending=True, method='min')
        scored_b = scored_b.sort_values('통합순위')
        selected = scored_b.head(N_STOCKS).copy()
        print(f"  최종 선정: {len(selected)}개 종목")
    else:
        selected = scored_b.head(N_STOCKS).copy() if not scored_b.empty else pd.DataFrame()
        print(f"  순위 컬럼 부족 - 멀티팩터 순위로 대체: {len(selected)}개")

    # =========================================================================
    # 6단계: 결과 저장 (통합 CSV 1개)
    # =========================================================================
    print("\n[6단계] 결과 저장")

    year_month = f"{base_dt.year}_{base_dt.month:02d}"

    if not selected.empty:
        output_path = OUTPUT_DIR / f'portfolio_{year_month}.csv'
        selected.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"  포트폴리오: {output_path}")

    # 리포트 생성
    report = generate_report(
        prefiltered, selected, universe_df, market_cap_df,
        ticker_names, error_tracker
    )

    report_path = OUTPUT_DIR / f'portfolio_{year_month}_report.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"  리포트: {report_path}")

    if error_tracker.errors:
        error_tracker.save_error_log()

    # =========================================================================
    # 완료
    # =========================================================================
    elapsed = datetime.now() - start_time

    print("\n" + "=" * 80)
    print("포트폴리오 생성 완료!")
    print(f"소요 시간: {elapsed.total_seconds():.1f}초 ({elapsed.total_seconds()/60:.1f}분)")
    print(f"사전 필터(A): {len(prefiltered)}개 → 최종 선정(B): {len(selected)}개")
    error_tracker.print_summary()
    print("=" * 80)

    return selected


def main():
    """동기 래퍼 (호환성)"""
    return asyncio.run(main_async())


if __name__ == '__main__':
    main()
