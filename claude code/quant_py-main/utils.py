"""
유틸리티 함수 모음
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def filter_universe(market_cap_df, price_df, fundamental_df, sector_df=None,
                    min_market_cap=100_000_000_000,  # 1,000억
                    min_avg_trading_value=1_000_000_000,  # 10억
                    lookback_days=60):
    """
    유니버스 필터링

    Args:
        market_cap_df: 시가총액 데이터프레임 (종목코드 인덱스)
        price_df: 가격 데이터프레임 (날짜 인덱스, 종목코드 컬럼)
        fundamental_df: 펀더멘털 데이터프레임 (종목코드 포함)
        sector_df: 섹터 정보 데이터프레임 (종목코드, 섹터)
        min_market_cap: 최소 시가총액
        min_avg_trading_value: 최소 평균 거래대금
        lookback_days: 거래대금 계산 기간 (일)

    Returns:
        filtered_tickers: 필터링된 종목 리스트
    """

    # 1. 시가총액 필터 (1,000억 이상)
    if '시가총액' in market_cap_df.columns:
        mcap_filter = market_cap_df['시가총액'] >= min_market_cap
        valid_tickers_mcap = market_cap_df[mcap_filter].index.tolist()
    else:
        # 시가총액 컬럼이 없으면 인덱스에서 시가총액 확인
        valid_tickers_mcap = market_cap_df.index.tolist()

    print(f"시가총액 필터 통과: {len(valid_tickers_mcap)}개 종목")

    # 2. 거래대금 필터 (일평균 10억 이상)
    # price_df에서 최근 lookback_days의 평균 거래대금 계산
    recent_prices = price_df.tail(lookback_days)

    if '거래대금' in market_cap_df.columns:
        # pykrx의 get_market_cap에는 거래대금도 포함
        avg_trading_value = market_cap_df['거래대금']
        trading_filter = avg_trading_value >= min_avg_trading_value
        valid_tickers_trading = market_cap_df[trading_filter].index.tolist()
    else:
        # 거래대금이 없으면 일단 모든 종목 통과
        valid_tickers_trading = valid_tickers_mcap

    print(f"거래대금 필터 통과: {len(valid_tickers_trading)}개 종목")

    # 3. 금융업, 지주사 제외
    exclude_keywords = ['금융', '지주', '홀딩스', '캐피탈', '증권', '보험', '은행', '카드']

    if sector_df is not None and '종목명' in sector_df.columns:
        exclude_filter = sector_df['종목명'].str.contains('|'.join(exclude_keywords), na=False)
        valid_tickers_sector = sector_df[~exclude_filter]['종목코드'].tolist()
    elif '종목명' in fundamental_df.columns:
        exclude_filter = fundamental_df['종목명'].str.contains('|'.join(exclude_keywords), na=False)
        valid_tickers_sector = fundamental_df[~exclude_filter]['종목코드'].tolist()
    else:
        valid_tickers_sector = valid_tickers_mcap

    print(f"금융업/지주사 제외 후: {len(valid_tickers_sector)}개 종목")

    # 4. 최근 4분기 합산 적자기업 제외
    # fundamental_df에 EPS나 당기순이익이 있다고 가정
    if 'EPS' in fundamental_df.columns:
        # EPS > 0인 종목만
        profit_filter = fundamental_df['EPS'] > 0
        valid_tickers_profit = fundamental_df[profit_filter]['종목코드'].tolist()
    else:
        valid_tickers_profit = valid_tickers_mcap

    print(f"흑자기업 필터 통과: {len(valid_tickers_profit)}개 종목")

    # 5. 모든 필터 교집합
    valid_tickers = list(set(valid_tickers_mcap) &
                         set(valid_tickers_trading) &
                         set(valid_tickers_sector) &
                         set(valid_tickers_profit))

    print(f"최종 유니버스: {len(valid_tickers)}개 종목")

    return valid_tickers


def calculate_momentum(price_df, lookback_months=12, skip_months=1):
    """
    모멘텀 계산 (12개월 수익률, 최근 1개월 제외)

    Args:
        price_df: 가격 데이터프레임 (날짜 인덱스, 종목코드 컬럼)
        lookback_months: 모멘텀 계산 기간 (개월)
        skip_months: 제외할 최근 기간 (개월)

    Returns:
        momentum_series: 종목별 모멘텀 값
    """
    lookback_days = lookback_months * 21  # 대략 21 영업일/월
    skip_days = skip_months * 21

    # 현재가 대비 lookback_days 전 가격
    if len(price_df) < lookback_days + skip_days:
        print(f"경고: 데이터가 부족합니다. {len(price_df)} < {lookback_days + skip_days}")
        return pd.Series()

    # 최근 skip_days를 제외한 가격
    end_price = price_df.iloc[-(skip_days + 1)]
    start_price = price_df.iloc[-(lookback_days + skip_days + 1)]

    momentum = (end_price / start_price - 1) * 100  # 퍼센트 수익률

    return momentum


def calculate_zscore_by_sector(df, value_col, sector_col='섹터'):
    """
    섹터별 Z-Score 계산

    Args:
        df: 데이터프레임
        value_col: 값 컬럼명
        sector_col: 섹터 컬럼명

    Returns:
        zscore_series: Z-Score 시리즈
    """
    def zscore(x):
        return (x - x.mean()) / x.std()

    if sector_col in df.columns:
        # 섹터별로 그룹화하여 Z-Score 계산
        df['zscore'] = df.groupby(sector_col)[value_col].transform(zscore)
        return df['zscore']
    else:
        # 섹터 정보가 없으면 전체 평균/표준편차로 계산
        return zscore(df[value_col])


def add_financial_reporting_lag(date, quarters=1):
    """
    재무제표 공시일 고려 (look-ahead bias 방지)

    한국 시장:
    - 연간 재무제표: 회계연도 종료 후 90일 이내 (보통 3월 말)
    - 분기 재무제표: 분기 종료 후 45일 이내

    Args:
        date: 기준 날짜
        quarters: 공시 지연 분기 수

    Returns:
        adjusted_date: 조정된 날짜
    """
    # 간단하게 3개월(1분기) 지연 적용
    lag_days = quarters * 90
    adjusted_date = pd.to_datetime(date) + pd.Timedelta(days=lag_days)

    return adjusted_date.strftime('%Y%m%d')


def winsorize(series, lower=0.01, upper=0.99):
    """
    이상치 제거 (Winsorization)

    Args:
        series: 데이터 시리즈
        lower: 하위 백분위수
        upper: 상위 백분위수

    Returns:
        winsorized_series: 조정된 시리즈
    """
    lower_val = series.quantile(lower)
    upper_val = series.quantile(upper)

    return series.clip(lower=lower_val, upper=upper_val)


def get_rebalancing_dates(start_date, end_date, frequency='Q'):
    """
    리밸런싱 날짜 생성

    Args:
        start_date: 시작 날짜 (YYYY-MM-DD)
        end_date: 종료 날짜 (YYYY-MM-DD)
        frequency: 'Q' (분기), 'M' (월), 'Y' (연)

    Returns:
        rebalancing_dates: 리밸런싱 날짜 리스트
    """
    dates = pd.date_range(start=start_date, end=end_date, freq=f'{frequency}E')
    return dates


if __name__ == '__main__':
    # 테스트
    print("유틸리티 함수 테스트")

    # 리밸런싱 날짜 테스트
    rebal_dates = get_rebalancing_dates('2015-01-01', '2025-12-31', frequency='Q')
    print(f"\n분기별 리밸런싱 날짜 (총 {len(rebal_dates)}개):")
    print(rebal_dates[:5])
    print("...")
    print(rebal_dates[-5:])

    # Winsorization 테스트
    test_data = pd.Series([1, 2, 3, 4, 5, 100, 200])
    print(f"\n원본 데이터: {test_data.tolist()}")
    print(f"Winsorized: {winsorize(test_data, 0.1, 0.9).tolist()}")
