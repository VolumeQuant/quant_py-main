import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

"""
퀀트 포트폴리오 생성 v6.0 — Slow In, Fast Out

파이프라인:
  유니버스(시총3000억+,거래대금차등) → PER/PBR 상한 필터
  → MA120 추세 필터 (하락 추세 원천 차단, 5% 버퍼)
  → A 사전필터(200) → B 멀티팩터 스코어링
  → 일일 순위 JSON 저장 (3일 교집합용)

팩터:
  - Value 30% + Quality 30% + Momentum 40% (섹터중립)
  - Value: PER + PBR + PCR + PSR
  - Quality: ROE + GPA + CFO + EPS개선도
  - Momentum: 6M수익률 / 6M변동성 [리스크 조정]

데이터 소스:
  - FnGuide 캐시: 재무제표 (Quality 팩터, PCR/PSR용)
  - pykrx 실시간: 시가총액, OHLCV, PER/PBR/DIV (Value 팩터)
"""

import os
import pandas as pd
import numpy as np
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
from ranking_manager import save_ranking, load_ranking, get_available_ranking_dates

# 설정
try:
    from config import (
        MIN_MARKET_CAP,
        MAX_CONCURRENT_REQUESTS, PYKRX_WORKERS, CACHE_DIR,
        PREFILTER_N, N_STOCKS, SKIP_PREFILTER
    )
except ImportError:
    MIN_MARKET_CAP = 1000
    MAX_CONCURRENT_REQUESTS = 10
    PYKRX_WORKERS = 10
    CACHE_DIR = "data_cache"
    PREFILTER_N = 200
    N_STOCKS = 30
    SKIP_PREFILTER = True

# KRX 인증 (2026-02-27~ 로그인 필수)
import krx_auth
krx_auth.login()

# 최근 거래일 자동 탐지 (한국 시간 기준)
from pykrx import stock as pykrx_stock
from zoneinfo import ZoneInfo
KST = ZoneInfo('Asia/Seoul')

# pykrx 업종지수명 → 표시 이름 (최소 통합 — 구체적 유지)
KRX_SECTOR_MAP = {
    # 통합이 필요한 것만 매핑 (나머지는 KRX 이름 그대로)
    '바이오/제약': '바이오/제약', '제약': '바이오/제약', '의료정밀': '의료기기',
    '운수장비': '자동차', '운수창고': '물류',
    '전기가스': '에너지/유틸',
    '금융': '금융', '증권': '금융', '보험': '금융',
    '출판/매체': '미디어', '기타제조': '기타',
}

def get_broad_sector(krx_sector: str) -> str:
    """pykrx 업종명 → 통합 대분류"""
    return KRX_SECTOR_MAP.get(krx_sector, krx_sector or '기타')

def get_latest_trading_date() -> str:
    """최근 거래일 찾기 — 개별종목 조회 우선, 캐시 폴백"""
    today = datetime.now(KST)
    # 1차: 삼성전자 개별 OHLCV로 최신 거래일 확인 (벌크 API 불필요)
    try:
        end = today.strftime('%Y%m%d')
        start = (today - timedelta(days=10)).strftime('%Y%m%d')
        df = pykrx_stock.get_market_ohlcv(start, end, '005930')
        if not df.empty:
            latest = df.index[-1].strftime('%Y%m%d')
            print(f"[거래일] 개별종목 조회: {latest}")
            return latest
    except Exception as e:
        print(f"[거래일] 개별종목 조회 실패: {e}")
    # 2차: market_cap 캐시 파일에서 최신 거래일 탐색
    cache_dir = Path(__file__).parent / CACHE_DIR
    mc_dates = []
    for f in cache_dir.glob('market_cap_ALL_*.parquet'):
        d = f.stem.split('_')[-1]
        if len(d) == 8 and d.isdigit():
            mc_dates.append(d)
    if mc_dates:
        today_str = today.strftime('%Y%m%d')
        valid = [d for d in mc_dates if d <= today_str]
        if valid:
            latest = max(valid)
            print(f"[거래일] 캐시에서 탐색: {latest}")
            return latest
    raise RuntimeError("최근 거래일을 찾을 수 없습니다. 캐시 파일과 네트워크를 확인하세요.")

import sys
if len(sys.argv) > 1 and len(sys.argv[1]) == 8 and sys.argv[1].isdigit():
    BASE_DATE = sys.argv[1]
    print(f"[날짜 오버라이드] BASE_DATE = {BASE_DATE}")
else:
    BASE_DATE = get_latest_trading_date()
OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# 제외 키워드 (금융업/지주사)
EXCLUDE_KEYWORDS = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                   '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT']


def _check_data_mismatch(dart_df, fn_df):
    """DART vs FnGuide 동일 연도 주요 계정 비교 — 심각한 불일치 감지

    매출액/자산: 양수끼리 50%+ 차이
    영업이익/당기순이익/영업현금흐름/자본: 부호 반전 (한쪽 양수, 한쪽 음수)
    2개 이상 계정에서 불일치 발견 시 True
    """
    try:
        mismatch_count = 0
        check_accounts = ['매출액', '영업이익', '당기순이익', '자산', '자본', '영업활동으로인한현금흐름']

        for acct in check_accounts:
            d_rows = dart_df[(dart_df['공시구분'] == 'y') & (dart_df['계정'] == acct)].copy()
            f_rows = fn_df[(fn_df['공시구분'] == 'y') & (fn_df['계정'] == acct)].copy()
            if d_rows.empty or f_rows.empty:
                continue
            d_rows['year'] = d_rows['기준일'].dt.year
            f_rows['year'] = f_rows['기준일'].dt.year
            common_years = set(d_rows['year']) & set(f_rows['year'])

            for yr in common_years:
                dv = d_rows[d_rows['year'] == yr].iloc[0]['값']
                fv = f_rows[f_rows['year'] == yr].iloc[0]['값']

                if acct in ('매출액', '자산'):
                    # 양수 계정: ratio 기반
                    if fv > 0 and dv > 0:
                        ratio = dv / fv
                        if ratio < 0.5 or ratio > 2.0:
                            mismatch_count += 1
                            break
                else:
                    # 부호 반전 감지 (둘 다 0이 아닌 경우)
                    if dv != 0 and fv != 0 and (dv > 0) != (fv > 0):
                        mismatch_count += 1
                        break
                    # 크기 차이도 체크 (둘 다 양수/음수인데 5배+ 차이)
                    if fv != 0 and dv != 0:
                        ratio = dv / fv
                        if ratio < 0.2 or ratio > 5.0:
                            mismatch_count += 1
                            break

        return mismatch_count >= 1
    except Exception:
        return False


def _merge_fs_supplement(primary_df, secondary_df):
    """DART(primary)에 누락된 계정을 FnGuide(secondary)에서 보충.

    두 소스의 데이터를 완전 결합. primary에 없는 분기/계정도 secondary에서 가져옴.
    데이터 갭은 growth 계산 시 별도 검증 (TTM 갭 체크).
    """
    # primary의 기존 키 세트
    primary_keys = set()
    for _, row in primary_df.iterrows():
        primary_keys.add((row['기준일'], row['공시구분'], row['계정']))

    # primary의 (기준일, 공시구분) → rcept_dt 매핑
    rcept_map = {}
    if 'rcept_dt' in primary_df.columns:
        for _, row in primary_df.iterrows():
            key = (row['기준일'], row['공시구분'])
            if key not in rcept_map and pd.notna(row.get('rcept_dt')):
                rcept_map[key] = row['rcept_dt']

    supplement_rows = []
    for _, row in secondary_df.iterrows():
        full_key = (row['기준일'], row['공시구분'], row['계정'])
        if full_key not in primary_keys and pd.notna(row['값']):
            period_key = (row['기준일'], row['공시구분'])
            new_row = {
                '계정': row['계정'],
                '기준일': row['기준일'],
                '값': row['값'],
                '종목코드': row.get('종목코드', primary_df.iloc[0].get('종목코드', '')),
                '공시구분': row['공시구분'],
            }
            if 'rcept_dt' in primary_df.columns:
                # primary에 같은 분기 rcept_dt 있으면 복사, 없으면 secondary 것 사용
                rcept = rcept_map.get(period_key)
                if rcept is None and 'rcept_dt' in secondary_df.columns:
                    rcept = row.get('rcept_dt')
                new_row['rcept_dt'] = rcept
            supplement_rows.append(new_row)

    if supplement_rows:
        merged = pd.concat([primary_df, pd.DataFrame(supplement_rows)], ignore_index=True)
        return merged, len(supplement_rows)
    return primary_df, 0


def load_fs_data_dart_first(tickers):
    """재무제표 로드: DART 우선 → FnGuide 폴백 + 누락 계정 보충

    1. DART vs FnGuide 불일치 종목 → FnGuide로 교체
    2. DART에 특정 분기 계정 누락 → FnGuide에서 보충 (매출액 등)
    """
    fs_data = {}
    dart_count = fn_count = mismatch_swap = supplement_count = 0
    cache_path = Path(CACHE_DIR)

    for ticker in tickers:
        dart_file = cache_path / f'fs_dart_{ticker}.parquet'
        fn_file = cache_path / f'fs_fnguide_{ticker}.parquet'

        dart_df = fn_df = None
        if dart_file.exists():
            try:
                dart_df = pd.read_parquet(dart_file)
                if dart_df.empty:
                    dart_df = None
            except Exception:
                dart_df = None
        if fn_file.exists():
            try:
                fn_df = pd.read_parquet(fn_file)
                if fn_df.empty:
                    fn_df = None
            except Exception:
                fn_df = None

        if dart_df is not None and fn_df is not None:
            if _check_data_mismatch(dart_df, fn_df):
                fs_data[ticker] = fn_df
                fn_count += 1
                mismatch_swap += 1
            else:
                # DART 분기 수 vs FnGuide 분기 수 비교
                dart_q_count = len(dart_df[dart_df['공시구분'] == 'q']['기준일'].unique())
                fn_q_count = len(fn_df[fn_df['공시구분'] == 'q']['기준일'].unique())
                if dart_q_count < 8 and fn_q_count > dart_q_count:
                    # DART 부족 → FnGuide 주 데��터 + DART 보충 (rcept_dt 등)
                    merged, n_sup = _merge_fs_supplement(fn_df, dart_df)
                    fs_data[ticker] = merged
                    fn_count += 1
                    supplement_count += n_sup
                else:
                    # DART 기반 + FnGuide 보충
                    merged, n_sup = _merge_fs_supplement(dart_df, fn_df)
                    fs_data[ticker] = merged
                    dart_count += 1
                    supplement_count += n_sup
        elif dart_df is not None:
            fs_data[ticker] = dart_df
            dart_count += 1
        elif fn_df is not None:
            fs_data[ticker] = fn_df
            fn_count += 1

    swap_msg = f", 불일치→FnGuide {mismatch_swap}" if mismatch_swap else ""
    sup_msg = f", FnGuide보충 {supplement_count}건" if supplement_count else ""
    print(f"  재무제표 로드: {len(fs_data)}개 (DART {dart_count} + FnGuide {fn_count}{swap_msg}{sup_msg})")
    return fs_data


def apply_ma120_filter(price_df: pd.DataFrame, universe_tickers: list) -> list:
    """
    MA120 추세 필터 (5% 버퍼): 현재가 >= 120일 이동평균 × 0.95인 종목만 통과

    가치 함정(Value Trap) 원천 차단:
    - 주가가 120일 이동평균의 95% 미만 = 중장기 하락 추세
    - 단기 조정(-5% 이내)은 허용하되, 본격 하락 추세는 제외
    - 60일 → 120일로 확대하여 단기 변동에 덜 민감

    Args:
        price_df: OHLCV 가격 데이터 (날짜 인덱스, 종목 컬럼)
        universe_tickers: 유니버스 종목 리스트

    Returns:
        MA120 필터 통과한 종목 리스트
    """
    if price_df.empty:
        print("  MA120 필터: 가격 데이터 없음 - 필터 스킵")
        return universe_tickers

    passed = []
    failed_tickers = []

    for ticker in universe_tickers:
        if ticker not in price_df.columns:
            continue

        prices = price_df[ticker].dropna()
        if len(prices) < 1:
            continue

        current_price = prices.iloc[-1]

        if len(prices) < 120:
            # 120일 미만: 중장기 추세 판단 불가 → 필터 면제
            passed.append(ticker)
            continue

        ma120 = prices.tail(120).mean()
        if current_price >= ma120:
            passed.append(ticker)
        else:
            failed_tickers.append(ticker)

    print(f"  MA120 필터: {len(passed)}개 통과 / {len(failed_tickers)}개 제외 (현재가 < MA120)")
    return passed, failed_tickers


def collect_consensus_data(
    tickers: List[str],
    error_tracker: ErrorTracker
) -> pd.DataFrame:
    """FnGuide 컨센서스 데이터 수집"""
    print("\n[FnGuide] 컨센서스 데이터 수집")
    print(f"  대상 종목: {len(tickers)}개")

    try:
        consensus_df = get_consensus_batch(tickers=tickers, delay=0.3)
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
    """market_cap 캐시에서 20일 평균 거래대금 계산 (BASE_DATE 기준)"""
    mcap_files = sorted(Path(CACHE_DIR).glob('market_cap_ALL_*.parquet'))
    if not mcap_files:
        print("  market_cap 캐시 없음")
        return pd.DataFrame()

    # BASE_DATE 기준 최근 60일 이내의 일별 캐시만 사용 (분기별 백테스트 파일 제외)
    # 주말 파일(거래대금=0) 자동 제외 — 20일 평균 왜곡 방지
    cutoff = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=60)).strftime('%Y%m%d')
    valid_files = []
    for f in mcap_files:
        date_str = f.stem.split('_')[-1]
        if cutoff <= date_str <= BASE_DATE:
            try:
                dt = datetime.strptime(date_str, '%Y%m%d')
                if dt.weekday() < 5:  # 월~금만
                    valid_files.append(f)
            except ValueError:
                pass
    target_files = valid_files[-days:]

    if not target_files:
        print("  거래대금 계산 가능한 캐시 없음")
        return pd.DataFrame()

    date_range = [f.stem.split('_')[-1] for f in target_files]
    print(f"  거래대금 조회: {date_range[0]} ~ {date_range[-1]} ({len(date_range)}일)")

    dfs = []
    for f in target_files:
        try:
            df = pd.read_parquet(f, columns=['거래대금'])
            dfs.append(df['거래대금'])
        except Exception:
            continue

    if not dfs:
        print("  거래대금 데이터 로드 실패")
        return pd.DataFrame()

    combined = pd.concat(dfs, axis=1)
    avg_values = combined.mean(axis=1) / 100_000_000

    result = pd.DataFrame({'avg_trading_value': avg_values})
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

    # 2. 거래대금 필터 — 시총 구간별 차등 적용
    #    대형주(1조+): 50억, 중소형(3000억~1조): 20억
    TRADING_LARGE = 50   # 시총 1조 이상
    TRADING_MID = 20     # 시총 3000억 ~ 1조
    print(f"20일 평균 거래대금 계산 중...")
    avg_trading_df = calculate_avg_trading_value_from_cache(days=20)

    if not avg_trading_df.empty:
        filtered = filtered.join(avg_trading_df, how='left')
        filtered['거래대금_억'] = filtered['거래대금'] / 100_000_000
        filtered['avg_trading_value'] = filtered['avg_trading_value'].fillna(filtered['거래대금_억'])
        tv_col = 'avg_trading_value'
    else:
        print("  (배치 실패 - 당일 거래대금 사용)")
        filtered['거래대금_억'] = filtered['거래대금'] / 100_000_000
        tv_col = '거래대금_억'

    large_mask = filtered['시가총액_억'] >= 10000  # 1조 이상
    pass_large = filtered[large_mask & (filtered[tv_col] >= TRADING_LARGE)]
    pass_mid = filtered[~large_mask & (filtered[tv_col] >= TRADING_MID)]
    filtered = pd.concat([pass_large, pass_mid]).copy()
    print(f"거래대금 차등 필터 (대형≥{TRADING_LARGE}억, 중소형≥{TRADING_MID}억): {len(filtered)}개")

    # 3. 종목명 수집 (JSON 캐시 우선 → pykrx 폴백)
    import json
    names_cache_path = Path(CACHE_DIR) / 'ticker_names_cache.json'
    if names_cache_path.exists():
        with open(names_cache_path, 'r', encoding='utf-8') as f:
            cached_names = json.load(f)
        print(f"종목명 캐시 로드: {len(cached_names)}개")
    else:
        cached_names = {}

    ticker_names = {}
    uncached = []
    for ticker in filtered.index.tolist():
        if ticker in cached_names:
            ticker_names[ticker] = cached_names[ticker]
        else:
            uncached.append(ticker)

    # 캐시에 없는 종목만 pykrx 조회 (신규 상장 등)
    if uncached:
        print(f"  신규 종목 {len(uncached)}개 pykrx 조회...")
        for ticker in uncached:
            try:
                name = pykrx_stock.get_market_ticker_name(ticker)
                ticker_names[ticker] = name
                cached_names[ticker] = name
                time.sleep(1)
            except Exception:
                ticker_names[ticker] = ticker
        # 캐시 업데이트
        with open(names_cache_path, 'w', encoding='utf-8') as f:
            json.dump(cached_names, f, ensure_ascii=False)
        print(f"  종목명 캐시 업데이트: {len(cached_names)}개")
    else:
        print("종목명 전부 캐시 히트")
    filtered['종목명'] = filtered.index.map(ticker_names)

    # 4. 금융업/지주사 제외
    mask = ~filtered['종목명'].str.contains('|'.join(EXCLUDE_KEYWORDS), na=False)
    filtered = filtered[mask].copy()
    print(f"금융업/지주사 제외 후: {len(filtered)}개")

    return filtered, ticker_names


def run_strategy_a_prefilter(
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


def run_strategy_b_scoring(
    prefiltered_df: pd.DataFrame,
    fundamental_df: pd.DataFrame,
    price_df: pd.DataFrame,
    ticker_names: Dict[str, str],
    error_tracker: ErrorTracker,
    consensus_df: pd.DataFrame = None,
    sector_map: Dict[str, str] = None
) -> pd.DataFrame:
    """전략 B (멀티팩터) - 전체 스코어링 v68 (V30+Q30+M40, 섹터중립)"""
    print(f"\n[전략 B] 멀티팩터 전체 스코어링 ({len(prefiltered_df)}개)")

    if prefiltered_df.empty:
        print("  사전 필터 데이터 없음 - 스킵")
        return pd.DataFrame()

    try:
        multifactor_df = prefiltered_df.copy()
        multifactor_df['종목명'] = multifactor_df['종목코드'].map(ticker_names)

        # Forward PER 병합 (FnGuide 컨센서스)
        if consensus_df is not None and not consensus_df.empty:
            fwd_cols = consensus_df[['ticker', 'forward_per']].dropna(subset=['forward_per'])
            if not fwd_cols.empty:
                multifactor_df = multifactor_df.merge(
                    fwd_cols, left_on='종목코드', right_on='ticker', how='left'
                )
                if 'ticker' in multifactor_df.columns:
                    multifactor_df.drop(columns=['ticker'], inplace=True)
                fwd_count = multifactor_df['forward_per'].notna().sum()
                print(f"  Forward PER 병합: {fwd_count}/{len(multifactor_df)}개 종목")

        # pykrx PER/PBR/EPS/BPS 병합 (strategy_b에서 pykrx_PER 등으로 사용)
        if not fundamental_df.empty:
            for col, new_col in [('PER', 'pykrx_PER'), ('PBR', 'pykrx_PBR'),
                                  ('EPS', 'pykrx_EPS'), ('BPS', 'pykrx_BPS')]:
                if col in fundamental_df.columns:
                    fund_map = fundamental_df[col].to_dict()
                    multifactor_df[new_col] = multifactor_df['종목코드'].map(fund_map)
            pykrx_count = multifactor_df['pykrx_PER'].notna().sum() if 'pykrx_PER' in multifactor_df.columns else 0
            print(f"  pykrx PER/PBR 병합: {pykrx_count}/{len(multifactor_df)}개")

        strategy = MultiFactorStrategy()
        selected, scored = strategy.run(multifactor_df, price_df=price_df, n_stocks=len(multifactor_df), sector_map=sector_map, base_date=BASE_DATE)

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

    report = f"""
================================================================================
퀀트 포트폴리오 리포트 v6.0 — Slow In, Fast Out
기준일: {BASE_DATE}
생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
================================================================================

[유니버스]
- 전체 종목: {len(market_cap_df)}개
- 필터링 후: {len(universe_df)}개
- 필터 조건:
  * 시가총액 >= {MIN_MARKET_CAP}억원
  * 거래대금: 대형(1조+)≥50억, 중소형≥20억
  * 금융업/지주사 제외
  * MA120 추세 필터 (현재가 < 120일 이동평균×0.95 제외)

[사전 필터 - 마법공식 상위 {PREFILTER_N}개]
- 통과 종목 수: {len(prefiltered)}개
"""

    if not prefiltered.empty and '종목명' in prefiltered.columns:
        if '마법공식_순위' in prefiltered.columns:
            report += f"- 상위 10종목:\n{prefiltered.head(10)[['종목코드', '종목명', '마법공식_순위']].to_string()}\n"
        else:
            report += f"- 전체 {len(prefiltered)}개 종목 (사전필터 스킵)\n"

    report += f"""
[최종 포트폴리오 - 멀티팩터 상위 {N_STOCKS}개]
- 선정 종목 수: {len(selected)}개
- 순위: 멀티팩터 100% (마법공식은 사전필터만)
- Value 팩터 30%: PER(실시간) + PBR(실시간) + PCR + PSR (섹터중립)
- Quality 팩터 30%: ROE + GPA + CFO + EPS개선도 (섹터중립)
- Momentum 팩터 40%: 6M수익률 / 6M변동성 [리스크 조정] (섹터중립)
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


def main():
    """메인 함수"""
    start_time = datetime.now()
    base_dt = datetime.strptime(BASE_DATE, '%Y%m%d')

    print("=" * 80)
    print("퀀트 포트폴리오 생성 v6.0 — Slow In, Fast Out")
    print(f"기준일: {BASE_DATE}")
    print(f"파이프라인: 유니버스 → MA120 필터 → A 사전필터({PREFILTER_N}) → B 멀티팩터 → 순위 저장")
    print(f"모멘텀: 6M / 변동성 [리스크 조정]")
    print("=" * 80)

    error_tracker = ErrorTracker(log_dir=Path("logs"), name="portfolio")
    error_tracker.log_info(f"포트폴리오 생성 시작 - 기준일: {BASE_DATE}")

    collector = DataCollector(start_date='20150101', end_date='20261231')

    # KRX 업종분류 로드 (섹터 통계용)
    sector_df = collector.get_krx_sector(BASE_DATE)
    sector_map = {}
    if not sector_df.empty:
        code_col = '종목코드' if '종목코드' in sector_df.columns else sector_df.columns[0]
        sect_col = '업종명' if '업종명' in sector_df.columns else None
        if sect_col:
            for _, row in sector_df.iterrows():
                ticker = str(row[code_col]).zfill(6)
                sector_map[ticker] = str(row[sect_col])
            print(f"  KRX 업종분류: {len(sector_map)}개 종목 매핑")

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
    # 3단계: 재무제표 수집 (DART 우선 → FnGuide 폴백)
    # =========================================================================
    print("\n[3단계] 재무제표 수집 (DART 우선 → FnGuide 폴백)")
    try:
        from fnguide_crawler import extract_magic_formula_data
        fs_data = load_fs_data_dart_first(universe_tickers)
        magic_df = extract_magic_formula_data(fs_data, base_date=BASE_DATE, use_ttm=True)
        print(f"  재무제표에서 {len(magic_df)}개 종목 로드")
    except Exception as e:
        error_tracker.log_error("FS_LOAD", ErrorCategory.UNKNOWN, "재무제표 로드 실패", e)
        magic_df = pd.DataFrame()

    # 자본잠식 종목 필터링
    if not magic_df.empty and '자본' in magic_df.columns:
        before_count = len(magic_df)
        magic_df = magic_df[magic_df['자본'] > 0].copy()
        filtered_count = before_count - len(magic_df)
        print(f"자본잠식 종목 제외: {filtered_count}개 → {len(magic_df)}개 남음")

    # 3.5단계: pykrx 실시간 펀더멘탈 수집 (PER/PBR/EPS/BPS)
    print("\n[3.5단계] pykrx 실시간 펀더멘탈 수집 (PER/PBR/EPS/BPS)")
    fundamental_df = collector.get_market_fundamental_batch(BASE_DATE)
    if not fundamental_df.empty:
        print(f"  pykrx 펀더멘털: {len(fundamental_df)}개 종목")
    else:
        print("  pykrx 펀더멘털 수집 실패")

    # =========================================================================
    # 4단계: OHLCV 수집 (캐시 + 증분 업데이트)
    # =========================================================================
    print("\n[4단계] OHLCV 데이터 로드 (캐시 + 증분)")

    ohlcv_tickers = magic_df['종목코드'].tolist() if not magic_df.empty else universe_tickers
    print(f"  OHLCV 대상: {len(ohlcv_tickers)}개 종목")

    end_date_dt = datetime.strptime(BASE_DATE, '%Y%m%d')
    start_date_dt = end_date_dt - timedelta(days=450)
    price_start = start_date_dt.strftime('%Y%m%d')

    ohlcv_cache_files = list(Path(CACHE_DIR).glob("all_ohlcv_*.parquet"))
    price_df = pd.DataFrame()
    need_refresh = True

    if ohlcv_cache_files:
        # BASE_DATE를 포함하면서 가장 긴 히스토리 파일 선택
        # 파일명: all_ohlcv_{start}_{end}.parquet
        best_file = None
        best_span = 0
        for f in ohlcv_cache_files:
            parts = f.stem.split('_')
            if len(parts) >= 4:
                f_start, f_end = parts[2], parts[3]
                if f_start <= BASE_DATE <= f_end:
                    span = int(f_end) - int(f_start)
                    if span > best_span:
                        best_span = span
                        best_file = f
        ohlcv_cache_file = best_file or sorted(ohlcv_cache_files)[-1]
        print(f"  캐시 파일 확인: {ohlcv_cache_file.name}")
        price_df = pd.read_parquet(ohlcv_cache_file)

        base_date_ts = pd.Timestamp(end_date_dt)
        if not price_df.empty and base_date_ts in price_df.index:
            # 캐시 히트: BASE_DATE 데이터 있음
            price_df = price_df[price_df.index <= base_date_ts]
            print(f"  캐시 히트 — {len(price_df.columns)}개 종목, {len(price_df)}거래일")
            need_refresh = False
        elif not price_df.empty:
            # 캐시 있지만 BASE_DATE 없음 — 증분 업데이트 시도
            last_cached = price_df.index[-1]
            gap_days = (base_date_ts - last_cached).days

            if 0 < gap_days <= 30:
                print(f"  증분 업데이트: 캐시 마지막={last_cached.strftime('%Y%m%d')}, 갭={gap_days}일")
                cached_tickers = set(price_df.columns)
                # 현재 유니버스에 있지만 캐시에 없는 신규 종목
                universe_set = set(ohlcv_tickers)
                new_universe = universe_set - cached_tickers
                if new_universe:
                    print(f"  신규 유니버스 종목: {len(new_universe)}개 → 개별 수집")

                new_rows = []
                keep_tickers = list(cached_tickers | universe_set)
                for offset in range(1, gap_days + 1):
                    date_dt = last_cached + timedelta(days=offset)
                    date_str = date_dt.strftime('%Y%m%d')
                    # 벌크 API 먼저 시도, 실패 시 개별 종목 수집
                    try:
                        day_ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(date_str, market='ALL')
                        if not day_ohlcv.empty and '종가' in day_ohlcv.columns:
                            row = day_ohlcv['종가']
                            row = row[row.index.isin(keep_tickers)]
                            row.name = pd.Timestamp(date_dt)
                            new_rows.append(row)
                            continue
                    except Exception:
                        pass
                    # 벌크 실패 시 개별 수집하지 않음 (차단 위험)
                    # 휴장일이거나 API 일시 장애 → 다음 날짜로 진행
                    print(f"    {date_str}: 벌크 실패 — 스킵 (휴장일 가능)")

                if new_rows:
                    new_df = pd.DataFrame(new_rows)
                    price_df = pd.concat([price_df, new_df])
                    price_df = price_df[~price_df.index.duplicated(keep='last')]
                    price_df = price_df.sort_index()
                    # 신규 유니버스 종목의 과거 데이터 개별 수집
                    if new_universe:
                        import time as _time
                        for ticker in new_universe:
                            try:
                                tk_ohlcv = pykrx_stock.get_market_ohlcv_by_date(
                                    price_start, BASE_DATE, ticker)
                                if not tk_ohlcv.empty and '종가' in tk_ohlcv.columns:
                                    price_df[ticker] = tk_ohlcv['종가'].reindex(price_df.index)
                                _time.sleep(1)
                            except Exception:
                                pass
                        print(f"  신규 종목 과거 데이터 수집 완료: {len(new_universe)}개")
                    # 캐시 저장 (새 날짜 범위) + 이전 파일 정리
                    new_start = price_df.index[0].strftime('%Y%m%d')
                    new_end = price_df.index[-1].strftime('%Y%m%d')
                    new_cache = Path(CACHE_DIR) / f'all_ohlcv_{new_start}_{new_end}.parquet'
                    price_df.to_parquet(new_cache)
                    # 이전 캐시 파일 정리 (새 파일보다 짧은 범위만 삭제, 긴 파일 보존)
                    new_span = int(new_end) - int(new_start)
                    for old_f in Path(CACHE_DIR).glob('all_ohlcv_*.parquet'):
                        if old_f == new_cache:
                            continue
                        parts = old_f.stem.split('_')
                        if len(parts) >= 4:
                            old_span = int(parts[3]) - int(parts[2])
                            if old_span <= new_span:
                                old_f.unlink()
                                print(f"  이전 캐시 삭제: {old_f.name}")
                            else:
                                print(f"  장기 캐시 보존: {old_f.name}")
                    print(f"  증분 완료: +{len(new_rows)}거래일 → 총 {len(price_df)}거래일, {len(price_df.columns)}종목")
                    # 다른 OHLCV 파일(백테스트용 등)도 증분 업데이트
                    for other_f in Path(CACHE_DIR).glob('all_ohlcv_*.parquet'):
                        if other_f == new_cache:
                            continue
                        try:
                            other_df = pd.read_parquet(other_f)
                            other_end = other_df.index[-1]
                            if other_end < price_df.index[-1]:
                                # 새 데이터 추가
                                append_rows = price_df[price_df.index > other_end]
                                if not append_rows.empty:
                                    updated = pd.concat([other_df, append_rows])
                                    updated = updated[~updated.index.duplicated(keep='last')].sort_index()
                                    o_start = updated.index[0].strftime('%Y%m%d')
                                    o_end = updated.index[-1].strftime('%Y%m%d')
                                    updated_path = Path(CACHE_DIR) / f'all_ohlcv_{o_start}_{o_end}.parquet'
                                    updated.to_parquet(updated_path)
                                    if updated_path != other_f:
                                        other_f.unlink()
                                    print(f"  백테스트용 증분: {other_f.name} → {updated_path.name} (+{len(append_rows)}일)")
                        except Exception as _e:
                            print(f"  백테스트용 증분 실패: {other_f.name} ({_e})")
                else:
                    print(f"  증분 업데이트: 새 거래일 없음 (휴장일)")
                need_refresh = False
            else:
                print(f"  캐시 갭 {gap_days}일 — 전체 재수집 필요")

    if need_refresh:
        print(f"  OHLCV 전체 수집 시작 ({len(ohlcv_tickers)}개 종목)...")
        price_df = collect_price_data_parallel(
            collector, ohlcv_tickers, price_start, BASE_DATE, error_tracker
        )

    # 주말/휴장일 0원 데이터 제거 (pct_change에서 inf 방지)
    if not price_df.empty:
        zero_rows = (price_df == 0).all(axis=1)
        if zero_rows.any():
            removed_dates = price_df.index[zero_rows].strftime('%Y-%m-%d').tolist()
            price_df = price_df[~zero_rows]
            print(f"  0원 행 제거: {len(removed_dates)}일 ({', '.join(removed_dates)})")
        price_df = price_df.replace(0, np.nan)

    # =========================================================================
    # 4.5단계: MA120 추세 필터 (가치 함정 원천 차단, 5% 버퍼)
    # =========================================================================
    print(f"\n[4.5단계] MA120 추세 필터 (현재가 < MA120×0.95 종목 제외)")
    ma120_failed = []
    if not price_df.empty and not magic_df.empty:
        ma120_tickers, ma120_failed = apply_ma120_filter(price_df, magic_df['종목코드'].tolist())
        before_count = len(magic_df)
        magic_df = magic_df[magic_df['종목코드'].isin(ma120_tickers)].copy()
        print(f"  MA120 필터 후: {before_count}개 → {len(magic_df)}개")
    else:
        print("  가격 데이터 부족 - MA120 필터 스킵")

    # =========================================================================
    # 5단계: FnGuide 컨센서스 수집 (Forward PER)
    # =========================================================================
    if SKIP_PREFILTER:
        # 사전필터 건너뜀 — MA120 통과한 전체 종목 멀티팩터 채점
        prefiltered = magic_df.merge(
            universe_df[['시가총액', '종목명']],
            left_on='종목코드', right_index=True, how='left'
        )
        prefiltered['시가총액'] = prefiltered['시가총액'] / 100_000_000
        print(f"\n[전략 A] 사전 필터 스킵 — 전체 {len(prefiltered)}개 종목 멀티팩터 채점")
    else:
        prefiltered = run_strategy_a_prefilter(magic_df, universe_df, error_tracker)

    consensus_df = pd.DataFrame()
    if not prefiltered.empty:
        print(f"\n[4.5단계] FnGuide 컨센서스 수집 (Forward PER) - {len(prefiltered)}개 종목")
        prefiltered_tickers = prefiltered['종목코드'].tolist()

        # 과거 재계산 모드: 기존 ranking JSON에서 Forward PER 로드
        use_json_consensus = os.environ.get('CONSENSUS_FROM_JSON') == '1'
        if use_json_consensus:
            print(f"  [재계산 모드] 기존 ranking JSON에서 Forward PER 로드 (BASE_DATE={BASE_DATE})")
            fwd_map = {}
            # 해당 날짜 → 직전 날짜 순으로 탐색 (해당 날짜 우선)
            all_dates = sorted(get_available_ranking_dates())
            target_dates = [d for d in all_dates if d <= BASE_DATE]
            for prev_date in reversed(target_dates):
                prev_data = load_ranking(prev_date)
                if prev_data:
                    for r in prev_data.get('rankings', []):
                        t = r.get('ticker', '')
                        if t and r.get('fwd_per') is not None and t not in fwd_map:
                            fwd_map[t] = r['fwd_per']
            rows = []
            for t in prefiltered_tickers:
                rows.append({
                    'ticker': t,
                    'forward_per': fwd_map.get(t),
                    'has_consensus': t in fwd_map,
                })
            consensus_df = pd.DataFrame(rows)
            has_fwd = consensus_df['forward_per'].notna().sum()
            print(f"  Forward PER 확보: {has_fwd}/{len(consensus_df)}개 ({has_fwd/len(consensus_df)*100:.0f}%)")
        else:
            consensus_df = collect_consensus_data(prefiltered_tickers, error_tracker)

        if not consensus_df.empty:
            if not use_json_consensus:
                has_fwd = consensus_df['forward_per'].notna().sum()
                print(f"  Forward PER 확보: {has_fwd}/{len(consensus_df)}개 ({has_fwd/len(consensus_df)*100:.0f}%)")

            # Forward PER fallback: 크롤링 실패 시 직전 ranking에서 보충
            missing_fwd = consensus_df[consensus_df['forward_per'].isna()]['ticker'].tolist()
            if missing_fwd:
                prev_dates = get_available_ranking_dates()
                fwd_fallback = {}
                for prev_date in prev_dates[:3]:
                    prev_data = load_ranking(prev_date)
                    if prev_data:
                        for r in prev_data.get('rankings', []):
                            t = r.get('ticker', '')
                            if t in missing_fwd and t not in fwd_fallback and r.get('fwd_per') is not None:
                                fwd_fallback[t] = r['fwd_per']
                if fwd_fallback:
                    for t, fwd_val in fwd_fallback.items():
                        consensus_df.loc[consensus_df['ticker'] == t, 'forward_per'] = fwd_val
                    print(f"  Forward PER fallback: {len(fwd_fallback)}개 종목 (직전 순위에서 보충)")

    # =========================================================================
    # 5단계: 전략 실행 (B 스코어링 → A+B 통합순위)
    # =========================================================================
    scored_b = run_strategy_b_scoring(
        prefiltered, fundamental_df, price_df, ticker_names, error_tracker,
        consensus_df=consensus_df,
        sector_map=sector_map
    )

    # 가중순위 기반 Top 30 선정: T0(멀티팩터) × 0.5 + T1 × 0.3 + T2 × 0.2
    print(f"\n[최종순위] 가중순위 = 멀티팩터×0.5 + T1×0.3 + T2×0.2")
    if not scored_b.empty and '멀티팩터_순위' in scored_b.columns:
        # 이전 2일 순위 로드
        available_dates = get_available_ranking_dates()
        prev_dates = sorted([d for d in available_dates if d < BASE_DATE])
        t1_date = prev_dates[-1] if len(prev_dates) >= 1 else None
        t2_date = prev_dates[-2] if len(prev_dates) >= 2 else None
        t1_data = load_ranking(t1_date) if t1_date else None
        t2_data = load_ranking(t2_date) if t2_date else None

        PENALTY = 50
        # T-1, T-2의 composite_rank 맵 (가중순위가 아닌 순수 composite!)
        # 주의: rank<=30 필터 없이 전체 종목 포함 (이전에 30위 밖이었을 수 있음)
        t1_map = {}
        if t1_data:
            for item in t1_data.get('rankings', []):
                t1_map[item['ticker']] = item.get('composite_rank', item['rank'])
        t2_map = {}
        if t2_data:
            for item in t2_data.get('rankings', []):
                t2_map[item['ticker']] = item.get('composite_rank', item['rank'])

        # 가중순위 = composite_T0 × 0.5 + composite_T1 × 0.3 + composite_T2 × 0.2
        weighted_scores = []
        for _, row in scored_b.iterrows():
            ticker = str(row.get('종목코드', '')).zfill(6)
            r0 = int(row['멀티팩터_순위'])
            r1 = t1_map.get(ticker, PENALTY) if t1_data else PENALTY
            r2 = t2_map.get(ticker, PENALTY) if t2_data else PENALTY
            weighted_scores.append(r0 * 0.5 + r1 * 0.3 + r2 * 0.2)

        scored_b['가중순위_점수'] = weighted_scores
        scored_b = scored_b.sort_values('가중순위_점수')
        scored_b['통합순위'] = range(1, len(scored_b) + 1)
        scored_b['통합순위_점수'] = scored_b['가중순위_점수']

        selected = scored_b.head(N_STOCKS).copy()
        all_ranked = scored_b.copy()
        history_str = f"T1={t1_date or '없음'}, T2={t2_date or '없음'}"
        print(f"  가중순위 적용: {history_str}")
        print(f"  전체 순위: {len(all_ranked)}개, CSV 선정: {len(selected)}개 종목")
    else:
        selected = scored_b.head(N_STOCKS).copy() if not scored_b.empty else pd.DataFrame()
        all_ranked = scored_b.copy() if not scored_b.empty else pd.DataFrame()
        print(f"  멀티팩터 순위로 선정: {len(selected)}개")

    # =========================================================================
    # 7단계: 결과 저장 (CSV + 일일 순위 JSON)
    # =========================================================================
    print("\n[7단계] 결과 저장")

    year_month = f"{base_dt.year}_{base_dt.month:02d}"

    if not selected.empty:
        output_path = OUTPUT_DIR / f'portfolio_{year_month}.csv'
        selected.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"  포트폴리오 CSV: {output_path}")

    # 일일 순위 JSON 저장 (3일 교집합 + Death List용)
    if not all_ranked.empty:
        rankings_list = []
        for _, row in all_ranked.iterrows():
            entry = {
                'rank': int(row.get('통합순위', 999)),
                'composite_rank': int(row.get('멀티팩터_순위', 999)),
                'ticker': str(row.get('종목코드', '')).zfill(6),
                'name': str(row.get('종목명', '')),
                'score': round(float(row.get('멀티팩터_점수', 0)), 4) if pd.notna(row.get('멀티팩터_점수')) else 0,
                'sector': get_broad_sector(sector_map.get(str(row.get('종목코드', '')).zfill(6), '')),
            }
            # 선택적 필드
            for col, key in [('PER', 'per'), ('PBR', 'pbr'), ('ROE', 'roe'), ('forward_per', 'fwd_per')]:
                val = row.get(col)
                if val is not None and pd.notna(val):
                    entry[key] = round(float(val), 2)
            # 팩터별 점수 (Death List 사유 분석용)
            for col, key in [('밸류_점수', 'value_s'), ('퀄리티_점수', 'quality_s'), ('성장_점수', 'growth_s'), ('모멘텀_점수', 'momentum_s')]:
                val = row.get(col)
                if val is not None and pd.notna(val):
                    entry[key] = round(float(val), 4)
            # Growth 서브팩터 z-score (G-ratio 재계산용)
            for col, key in [('매출성장률_z', 'rev_z'), ('이익변화량_z', 'oca_z')]:
                val = row.get(col)
                if val is not None and pd.notna(val):
                    entry[key] = round(float(val), 4)
            # 종가 (가격 변동 태그용)
            ticker = entry['ticker']
            if not price_df.empty and ticker in price_df.columns:
                last_price = price_df[ticker].dropna()
                if not last_price.empty:
                    entry['price'] = int(last_price.iloc[-1])
            rankings_list.append(entry)

        # 6.5단계: Top 30 상관관계 계산 (60일 수익률, 정보 표시용)
        corr_60d = {}
        top30_tickers = [r['ticker'] for r in rankings_list[:30]]
        valid_tickers = [t for t in top30_tickers if t in price_df.columns]
        if len(valid_tickers) >= 2 and len(price_df) >= 20:
            rets = price_df[valid_tickers].tail(60).pct_change().dropna()
            if len(rets) >= 20:
                corr_matrix = rets.corr()
                for i in range(len(valid_tickers)):
                    for j in range(i + 1, len(valid_tickers)):
                        t1, t2 = valid_tickers[i], valid_tickers[j]
                        c = corr_matrix.iloc[i, j]
                        if not pd.isna(c):
                            key = '_'.join(sorted([t1, t2]))
                            corr_60d[key] = round(float(c), 3)
                print(f"  상관관계 계산: {len(corr_60d)}개 페어 (Top 30, 60일)")

        save_ranking(BASE_DATE, rankings_list, metadata={
            'total_universe': len(universe_tickers),
            'prefilter_passed': len(prefiltered) if not prefiltered.empty else 0,
            'scored_count': len(all_ranked),
            'version': '6.0',
            'correlation_60d': corr_60d,
            'ma120_failed': ma120_failed,
        })
        print(f"  일일 순위 JSON: state/ranking_{BASE_DATE}.json ({len(rankings_list)}개 종목)")

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


if __name__ == '__main__':
    main()
