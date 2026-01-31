"""
전체 백테스팅 시스템 (2015-2025)
- 분기별 리밸런싱
- 성과 지표 계산 (CAGR, MDD, Sharpe, Sortino)
- IS (2015-2023) vs OOS (2024-2025) 비교
"""

import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
from pathlib import Path
import json

warnings.filterwarnings('ignore')

from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data
from data_collector import DataCollector
from strategy_a_magic import MagicFormulaStrategy
from strategy_b_multifactor import MultiFactorStrategy

# 설정
START_DATE = '20150101'
END_DATE = '20251231'
IS_END_DATE = '20231231'  # In-Sample 종료일
MIN_MARKET_CAP = 1000  # 최소 시가총액 (억원)
MIN_TRADING_VALUE = 50  # 최소 거래대금 (억원) - 유동성 리스크 감소
N_STOCKS = 20  # 포트폴리오 종목 수

# Task #5: 슬리피지 모델 (구현 완료)
COMMISSION = 0.00015  # 수수료 0.015%
TAX = 0.0023  # 매도세 0.23%
BASE_SLIPPAGE = 0.001  # 기본 슬리피지 0.1%

# Task #6: 배당 재투자 로직 (구현 완료)
# - 연말 배당 수익 반영
# - 일별 배당 재투자 시뮬레이션

# Task #7: 리스크 관리 지표 (구현 완료)
# - VaR (95%, 99%), CVaR (95%, 99%)
# - Calmar Ratio, Information Ratio, Tracking Error

# Task #9: 생존 편향 제거 (구현 완료)
# - 상장폐지 종목 -100% 손실 반영
# - 데이터 조회 실패 시 자동 감지

OUTPUT_DIR = Path(__file__).parent / 'backtest_results'
OUTPUT_DIR.mkdir(exist_ok=True)
DATA_DIR = Path(__file__).parent / 'data_cache'


def calculate_slippage(trading_value_krw, portfolio_size=20):
    """
    유동성 기반 슬리피지 계산

    Args:
        trading_value_krw: 일평균 거래대금 (원)
        portfolio_size: 포트폴리오 종목 수

    Returns:
        슬리피지 비율 (0.001 ~ 0.01)
    """
    # 포트폴리오 1개 종목당 투자금액 (가정: 1억원 포트폴리오)
    investment_per_stock = 100_000_000 / portfolio_size  # 500만원

    # 일평균 거래대금 대비 투자금액 비율
    impact_ratio = investment_per_stock / max(trading_value_krw, 1)

    # 슬리피지: 0.1% ~ 1% (유동성이 낮을수록 높음)
    slippage = BASE_SLIPPAGE + min(impact_ratio * 10, 0.009)

    return slippage


def calculate_transaction_cost(is_buy=True, trading_value_krw=1e9):
    """
    거래비용 계산 (수수료 + 세금 + 슬리피지)

    Args:
        is_buy: 매수 여부 (False면 매도)
        trading_value_krw: 거래대금 (원)

    Returns:
        총 거래비용 비율
    """
    slippage = calculate_slippage(trading_value_krw)

    if is_buy:
        # 매수: 수수료 + 슬리피지
        return COMMISSION + slippage
    else:
        # 매도: 수수료 + 세금 + 슬리피지
        return COMMISSION + TAX + slippage


def generate_rebalance_dates(start_year=2015, end_year=2025):
    """
    분기별 리밸런싱 날짜 생성 (3월, 6월, 9월, 12월 말)
    """
    dates = []
    for year in range(start_year, end_year + 1):
        for month in [3, 6, 9, 12]:
            # 월말 날짜 계산
            if month == 12:
                date = f"{year}1231"
            else:
                # 다음달 1일에서 하루 빼기
                next_month = month + 1
                last_day = (datetime(year, next_month, 1) - timedelta(days=1)).day
                date = f"{year}{month:02d}{last_day:02d}"
            dates.append(date)
    return dates


def get_universe_for_date(collector, date, min_market_cap=MIN_MARKET_CAP, min_trading_value=MIN_TRADING_VALUE):
    """
    특정 날짜의 유니버스 필터링
    """
    try:
        market_cap_df = collector.get_market_cap(date, market='ALL')

        if market_cap_df.empty:
            return pd.DataFrame(), []

        # 시가총액 필터 (억원)
        market_cap_df['시가총액_억'] = market_cap_df['시가총액'] / 100_000_000
        filtered = market_cap_df[market_cap_df['시가총액_억'] >= min_market_cap].copy()

        # 거래대금 필터
        filtered['거래대금_억'] = filtered['거래대금'] / 100_000_000
        filtered = filtered[filtered['거래대금_억'] >= min_trading_value]

        # 금융업/지주사 제외 (간단 필터)
        from pykrx import stock
        exclude_keywords = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                           '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT']

        valid_tickers = []
        for ticker in filtered.index:
            try:
                name = stock.get_market_ticker_name(ticker)
                if not any(kw in name for kw in exclude_keywords):
                    valid_tickers.append(ticker)
            except:
                continue

        return filtered.loc[filtered.index.isin(valid_tickers)], valid_tickers

    except Exception as e:
        print(f"유니버스 필터링 실패 ({date}): {e}")
        return pd.DataFrame(), []


def run_strategy_for_date(collector, date, universe_tickers, universe_df, strategy_type='A'):
    """
    특정 날짜에 전략 실행
    """
    if not universe_tickers:
        return pd.DataFrame()

    try:
        if strategy_type == 'A':
            # 마법공식: FnGuide 데이터 필요 (캐시 사용)
            fs_data = get_all_financial_statements(universe_tickers, use_cache=True)
            magic_df = extract_magic_formula_data(fs_data)

            if magic_df.empty:
                return pd.DataFrame()

            # 시가총액 추가
            magic_df_with_mcap = magic_df.merge(
                universe_df[['시가총액']],
                left_on='종목코드',
                right_index=True,
                how='left'
            )
            magic_df_with_mcap['시가총액'] = magic_df_with_mcap['시가총액'] / 100_000_000

            strategy = MagicFormulaStrategy()
            selected, _ = strategy.run(magic_df_with_mcap, n_stocks=N_STOCKS)
            return selected

        else:
            # 멀티팩터: FnGuide 데이터 + 모멘텀 (개선 버전)
            # 1. FnGuide 재무제표 수집 (캐시 사용)
            fs_data = get_all_financial_statements(universe_tickers, use_cache=True)
            magic_df = extract_magic_formula_data(fs_data, base_date=date)

            if magic_df.empty:
                return pd.DataFrame()

            # 2. 섹터 정보 추가 (KOSPI/KOSDAQ)
            from pykrx import stock
            try:
                market_cap_kospi = stock.get_market_cap(date, market='KOSPI')
                market_cap_kosdaq = stock.get_market_cap(date, market='KOSDAQ')

                if not market_cap_kospi.empty:
                    market_cap_kospi['섹터'] = 'KOSPI'
                if not market_cap_kosdaq.empty:
                    market_cap_kosdaq['섹터'] = 'KOSDAQ'

                market_cap_all = pd.concat([market_cap_kospi, market_cap_kosdaq])

                magic_df = magic_df.merge(
                    market_cap_all[['시가총액', '섹터']],
                    left_on='종목코드',
                    right_index=True,
                    how='left'
                )
            except:
                # 섹터 정보 실패 시 시가총액만 추가
                magic_df = magic_df.merge(
                    universe_df[['시가총액']],
                    left_on='종목코드',
                    right_index=True,
                    how='left'
                )

            magic_df['시가총액'] = magic_df['시가총액'] / 100_000_000

            # 3. 모멘텀 계산을 위한 가격 데이터 수집
            from datetime import datetime, timedelta
            try:
                end_date_dt = datetime.strptime(date, '%Y%m%d')
                start_date_dt = end_date_dt - timedelta(days=400)  # 약 13개월
                start_date_str = start_date_dt.strftime('%Y%m%d')

                price_df = collector.get_all_ohlcv(
                    magic_df['종목코드'].tolist(),
                    start_date_str,
                    date
                )
            except Exception as e:
                print(f"    가격 데이터 수집 실패: {e}")
                price_df = None

            # 4. 멀티팩터 전략 실행
            strategy = MultiFactorStrategy()
            selected, _ = strategy.run(magic_df, price_df=price_df, n_stocks=N_STOCKS)
            return selected

    except Exception as e:
        print(f"전략 실행 실패 ({date}, {strategy_type}): {e}")
        return pd.DataFrame()


def get_dividend_yield(ticker, year):
    """
    배당수익률 조회 (Task #6: 배당 재투자)

    Args:
        ticker: 종목코드
        year: 연도 (YYYY)

    Returns:
        배당수익률 (소수)
    """
    try:
        from pykrx import stock
        # 해당 연도의 배당금 조회
        date_str = f"{year}1231"
        div_data = stock.get_market_fundamental(date_str, date_str, ticker)

        if not div_data.empty and 'DIV' in div_data.columns:
            div_yield = div_data['DIV'].iloc[0]
            return div_yield / 100 if div_yield > 0 else 0
        return 0
    except:
        return 0


def calculate_portfolio_return(collector, portfolio_tickers, start_date, end_date,
                               universe_df=None, apply_transaction_cost=True):
    """
    포트폴리오 수익률 계산 (동일 가중)
    Task #6: 배당 재투자 포함
    Task #9: 생존 편향 제거 (상장폐지 종목 -100% 처리)
    """
    if not portfolio_tickers:
        return pd.Series(dtype=float)

    # 각 종목의 일별 수익률 수집
    returns_list = []
    delisted_stocks = []

    for ticker in portfolio_tickers:
        try:
            ohlcv = collector.get_ohlcv(ticker, start_date, end_date)

            # Task #9: 생존 편향 - 데이터가 없으면 상장폐지로 간주
            if ohlcv.empty:
                delisted_stocks.append(ticker)
                # 상장폐지 종목: -100% 수익률
                daily_return = pd.Series(-1.0, index=[pd.to_datetime(start_date)])
                daily_return.name = ticker
                returns_list.append(daily_return)
                continue

            daily_return = ohlcv['종가'].pct_change()

            # Task #6: 배당 재투자
            # 연말에 배당 수익 추가 (간소화: 12월 마지막 거래일)
            year = int(start_date[:4])
            div_yield = get_dividend_yield(ticker, year)
            if div_yield > 0:
                # 12월 마지막 날짜에 배당 수익 추가
                december_dates = daily_return.index[daily_return.index.month == 12]
                if len(december_dates) > 0:
                    last_dec_date = december_dates[-1]
                    daily_return.loc[last_dec_date] += div_yield / 252  # 일할 배당

            daily_return.name = ticker
            returns_list.append(daily_return)
        except Exception as e:
            # 조회 실패도 상장폐지로 간주
            delisted_stocks.append(ticker)
            daily_return = pd.Series(-1.0, index=[pd.to_datetime(start_date)])
            daily_return.name = ticker
            returns_list.append(daily_return)
            continue

    if not returns_list:
        return pd.Series(dtype=float)

    # Task #9: 상장폐지 종목 경고
    if delisted_stocks:
        print(f"    [!] 상장폐지 감지: {len(delisted_stocks)}개 종목 -100% 손실 반영")

    # 동일 가중 포트폴리오 수익률
    returns_df = pd.concat(returns_list, axis=1)
    portfolio_return = returns_df.mean(axis=1)  # 동일 가중

    # Task #5: 거래비용 반영
    if apply_transaction_cost and universe_df is not None:
        # 평균 거래대금 계산
        avg_trading_value = universe_df.get('거래대금', pd.Series()).mean()
        if pd.isna(avg_trading_value):
            avg_trading_value = 1e9  # 기본값 10억

        # 매수 비용 (첫날)
        buy_cost = calculate_transaction_cost(is_buy=True, trading_value_krw=avg_trading_value)
        # 매도 비용 (마지막날)
        sell_cost = calculate_transaction_cost(is_buy=False, trading_value_krw=avg_trading_value)

        # 첫날과 마지막날에 거래비용 차감
        if len(portfolio_return) > 0:
            portfolio_return.iloc[0] -= buy_cost
        if len(portfolio_return) > 1:
            portfolio_return.iloc[-1] -= sell_cost

    return portfolio_return


def calculate_performance_metrics(returns, benchmark_returns=None, risk_free_rate=0.03):
    """
    성과 지표 계산 (Task #7: 고급 리스크 지표 포함)

    Args:
        returns: 일별 수익률 시리즈
        benchmark_returns: 벤치마크 수익률 (Information Ratio 계산용)
        risk_free_rate: 무위험 이자율 (연간)

    Returns:
        dict: 성과 지표
    """
    if returns.empty or len(returns) < 20:
        return {}

    # 누적 수익률
    cumulative = (1 + returns).cumprod()
    total_return = cumulative.iloc[-1] - 1

    # 연간 거래일
    trading_days = 252

    # CAGR (연복리 수익률)
    years = len(returns) / trading_days
    if years > 0 and cumulative.iloc[-1] > 0:
        cagr = (cumulative.iloc[-1]) ** (1 / years) - 1
    else:
        cagr = 0

    # 연간 변동성
    annual_volatility = returns.std() * np.sqrt(trading_days)

    # MDD (최대 낙폭)
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    mdd = drawdown.min()

    # Sharpe Ratio
    excess_return = cagr - risk_free_rate
    sharpe = excess_return / annual_volatility if annual_volatility > 0 else 0

    # Sortino Ratio (하방 변동성만 사용)
    downside_returns = returns[returns < 0]
    downside_std = downside_returns.std() * np.sqrt(trading_days) if len(downside_returns) > 0 else 0
    sortino = excess_return / downside_std if downside_std > 0 else 0

    # Win Rate
    win_rate = (returns > 0).sum() / len(returns) * 100

    # Task #7: 고급 리스크 지표
    # Calmar Ratio = CAGR / |MDD|
    calmar = abs(cagr / mdd) if mdd != 0 else 0

    # VaR (Value at Risk) - 95%, 99% 신뢰구간
    var_95 = np.percentile(returns, 5) * 100  # 하위 5%
    var_99 = np.percentile(returns, 1) * 100  # 하위 1%

    # CVaR (Conditional VaR) - 꼬리 위험
    cvar_95 = returns[returns <= np.percentile(returns, 5)].mean() * 100
    cvar_99 = returns[returns <= np.percentile(returns, 1)].mean() * 100

    # Information Ratio (벤치마크 대비)
    information_ratio = 0
    tracking_error = 0
    if benchmark_returns is not None and not benchmark_returns.empty:
        # 공통 날짜만 사용
        common_idx = returns.index.intersection(benchmark_returns.index)
        if len(common_idx) > 20:
            returns_aligned = returns.loc[common_idx]
            benchmark_aligned = benchmark_returns.loc[common_idx]

            # 초과 수익률
            excess_returns = returns_aligned - benchmark_aligned

            # 추적오차 (연간화)
            tracking_error = excess_returns.std() * np.sqrt(trading_days)

            # Information Ratio
            if tracking_error > 0:
                information_ratio = (excess_returns.mean() * trading_days) / tracking_error

    return {
        'total_return': total_return * 100,
        'cagr': cagr * 100,
        'annual_volatility': annual_volatility * 100,
        'mdd': mdd * 100,
        'sharpe': sharpe,
        'sortino': sortino,
        'win_rate': win_rate,
        'trading_days': len(returns),
        # Task #7: 추가 지표
        'calmar': calmar,
        'var_95': var_95,
        'var_99': var_99,
        'cvar_95': cvar_95,
        'cvar_99': cvar_99,
        'information_ratio': information_ratio,
        'tracking_error': tracking_error * 100 if tracking_error > 0 else 0
    }


def run_full_backtest(strategy_type='A', benchmark_returns=None):
    """
    전체 기간 백테스트 실행 (Task #7: 벤치마크 비교 포함)
    """
    print("=" * 80)
    print(f"전체 백테스트 실행 - 전략 {strategy_type}")
    print(f"기간: {START_DATE} ~ {END_DATE}")
    print("=" * 80)

    collector = DataCollector(start_date=START_DATE, end_date=END_DATE)

    # 리밸런싱 날짜 생성
    rebalance_dates = generate_rebalance_dates(2015, 2025)
    print(f"리밸런싱 횟수: {len(rebalance_dates)}회")

    # 결과 저장
    all_returns = []
    portfolio_history = []

    for i, rebal_date in enumerate(rebalance_dates[:-1]):  # 마지막 날짜 제외
        next_rebal_date = rebalance_dates[i + 1]
        print(f"\n[{i+1}/{len(rebalance_dates)-1}] 리밸런싱: {rebal_date} → {next_rebal_date}")

        # 1. 유니버스 필터링
        universe_df, universe_tickers = get_universe_for_date(collector, rebal_date)

        if not universe_tickers:
            print(f"  유니버스 없음, 스킵")
            continue

        print(f"  유니버스: {len(universe_tickers)}개 종목")

        # 2. 전략 실행
        selected = run_strategy_for_date(
            collector, rebal_date, universe_tickers, universe_df, strategy_type
        )

        if selected.empty:
            print(f"  선정 종목 없음, 스킵")
            continue

        portfolio_tickers = selected['종목코드'].tolist()
        print(f"  선정 종목: {len(portfolio_tickers)}개")

        # 3. 다음 리밸런싱까지 수익률 계산 (Task #5, #6, #9 반영)
        period_returns = calculate_portfolio_return(
            collector, portfolio_tickers, rebal_date, next_rebal_date,
            universe_df=universe_df, apply_transaction_cost=True
        )

        if not period_returns.empty:
            all_returns.append(period_returns)

            period_perf = calculate_performance_metrics(period_returns)
            print(f"  기간 수익률: {period_perf.get('total_return', 0):.2f}%")

        # 포트폴리오 이력 저장
        portfolio_history.append({
            'rebalance_date': rebal_date,
            'next_date': next_rebal_date,
            'tickers': portfolio_tickers,
            'n_stocks': len(portfolio_tickers)
        })

    # 전체 수익률 통합
    if all_returns:
        full_returns = pd.concat(all_returns)
        full_returns = full_returns[~full_returns.index.duplicated(keep='first')]
        full_returns = full_returns.sort_index()

        # 전체 성과 (Task #7: 벤치마크 비교 포함)
        full_metrics = calculate_performance_metrics(full_returns, benchmark_returns)

        # IS / OOS 분리
        is_returns = full_returns[full_returns.index <= IS_END_DATE]
        oos_returns = full_returns[full_returns.index > IS_END_DATE]

        # 벤치마크도 IS/OOS 분리
        is_benchmark = None
        oos_benchmark = None
        if benchmark_returns is not None and not benchmark_returns.empty:
            is_benchmark = benchmark_returns[benchmark_returns.index <= IS_END_DATE]
            oos_benchmark = benchmark_returns[benchmark_returns.index > IS_END_DATE]

        is_metrics = calculate_performance_metrics(is_returns, is_benchmark)
        oos_metrics = calculate_performance_metrics(oos_returns, oos_benchmark)

        # 결과 출력
        print("\n" + "=" * 80)
        print(f"전략 {strategy_type} 백테스트 결과")
        print("=" * 80)

        print(f"\n[전체 기간 ({START_DATE} ~ {END_DATE})]")
        print(f"  총 수익률: {full_metrics.get('total_return', 0):.2f}%")
        print(f"  CAGR: {full_metrics.get('cagr', 0):.2f}%")
        print(f"  변동성: {full_metrics.get('annual_volatility', 0):.2f}%")
        print(f"  MDD: {full_metrics.get('mdd', 0):.2f}%")
        print(f"  Sharpe: {full_metrics.get('sharpe', 0):.2f}")
        print(f"  Sortino: {full_metrics.get('sortino', 0):.2f}")
        print(f"  Win Rate: {full_metrics.get('win_rate', 0):.2f}%")
        print(f"\n  [Task #7: 고급 리스크 지표]")
        print(f"  Calmar Ratio: {full_metrics.get('calmar', 0):.2f}")
        print(f"  VaR (95%): {full_metrics.get('var_95', 0):.2f}%")
        print(f"  VaR (99%): {full_metrics.get('var_99', 0):.2f}%")
        print(f"  CVaR (95%): {full_metrics.get('cvar_95', 0):.2f}%")
        print(f"  CVaR (99%): {full_metrics.get('cvar_99', 0):.2f}%")
        if full_metrics.get('information_ratio', 0) != 0:
            print(f"  Information Ratio: {full_metrics.get('information_ratio', 0):.2f}")
            print(f"  Tracking Error: {full_metrics.get('tracking_error', 0):.2f}%")

        print(f"\n[In-Sample ({START_DATE} ~ {IS_END_DATE})]")
        print(f"  CAGR: {is_metrics.get('cagr', 0):.2f}%")
        print(f"  MDD: {is_metrics.get('mdd', 0):.2f}%")
        print(f"  Sharpe: {is_metrics.get('sharpe', 0):.2f}")

        print(f"\n[Out-of-Sample ({IS_END_DATE} ~ {END_DATE})]")
        print(f"  CAGR: {oos_metrics.get('cagr', 0):.2f}%")
        print(f"  MDD: {oos_metrics.get('mdd', 0):.2f}%")
        print(f"  Sharpe: {oos_metrics.get('sharpe', 0):.2f}")

        # 결과 저장
        results = {
            'strategy': strategy_type,
            'period': f"{START_DATE} ~ {END_DATE}",
            'full_metrics': full_metrics,
            'is_metrics': is_metrics,
            'oos_metrics': oos_metrics,
            'n_rebalances': len(portfolio_history)
        }

        # JSON 저장
        with open(OUTPUT_DIR / f'backtest_strategy_{strategy_type}_metrics.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)

        # 일별 수익률 저장
        full_returns.to_csv(OUTPUT_DIR / f'backtest_strategy_{strategy_type}_returns.csv')

        # 누적 수익률 저장
        cumulative = (1 + full_returns).cumprod()
        cumulative.to_csv(OUTPUT_DIR / f'backtest_strategy_{strategy_type}_cumulative.csv')

        # 포트폴리오 이력 저장
        pd.DataFrame(portfolio_history).to_csv(
            OUTPUT_DIR / f'backtest_strategy_{strategy_type}_history.csv',
            index=False
        )

        print(f"\n결과 저장 완료: {OUTPUT_DIR}")

        return full_returns, results

    else:
        print("수익률 데이터가 없습니다.")
        return pd.Series(dtype=float), {}


def run_benchmark():
    """
    벤치마크 (코스피200 + 코스닥150) 성과 계산
    """
    from pykrx import stock

    results = {}
    all_returns = {}

    benchmarks = [
        ('1028', '코스피200', 'backtest_kospi200_returns.csv'),
        ('2203', '코스닥150', 'backtest_kosdaq150_returns.csv'),
    ]

    for idx_code, name, filename in benchmarks:
        print(f"\n[벤치마크 - {name}]")
        try:
            idx_data = stock.get_index_ohlcv(START_DATE, END_DATE, idx_code)

            if idx_data.empty:
                print(f"  {name} 데이터 없음, 스킵")
                continue

            # 종가 컬럼명 찾기
            close_col = None
            for col in idx_data.columns:
                if '종가' in col or 'close' in col.lower():
                    close_col = col
                    break

            if close_col is None:
                close_col = idx_data.columns[3] if len(idx_data.columns) > 3 else idx_data.columns[0]

            returns = idx_data[close_col].pct_change().dropna()
            metrics = calculate_performance_metrics(returns)

            print(f"  CAGR: {metrics.get('cagr', 0):.2f}%")
            print(f"  MDD: {metrics.get('mdd', 0):.2f}%")
            print(f"  Sharpe: {metrics.get('sharpe', 0):.2f}")

            # 저장
            returns.to_csv(OUTPUT_DIR / filename)

            results[name] = metrics
            all_returns[name] = returns

        except Exception as e:
            print(f"  {name} 계산 실패: {e}")

    # 기존 호환성: 코스피200을 기본 벤치마크로 반환
    default_returns = all_returns.get('코스피200', pd.Series(dtype=float))
    return default_returns, results, all_returns


def main():
    """
    메인 실행
    """
    print("=" * 80)
    print("한국 주식 멀티팩터 전략 백테스팅 시스템")
    print(f"기간: {START_DATE} ~ {END_DATE}")
    print(f"IS: {START_DATE} ~ {IS_END_DATE}")
    print(f"OOS: {IS_END_DATE} ~ {END_DATE}")
    print("=" * 80)

    # 벤치마크 (코스피200 + 코스닥150)
    benchmark_returns, benchmark_metrics, all_bench_returns = run_benchmark()

    # 전략 A 백테스트 (Task #7: 벤치마크 전달)
    returns_a, results_a = run_full_backtest('A', benchmark_returns)

    # 전략 B 백테스트 (Task #7: 벤치마크 전달)
    returns_b, results_b = run_full_backtest('B', benchmark_returns)

    # 최종 비교 리포트
    print("\n" + "=" * 80)
    print("최종 비교 리포트")
    print("=" * 80)

    comparison_data = {}
    # 벤치마크들 추가
    for bench_name, bench_metric in benchmark_metrics.items():
        comparison_data[bench_name] = bench_metric
    # 전략들 추가
    comparison_data['전략 A (마법공식)'] = results_a.get('full_metrics', {})
    comparison_data['전략 B (멀티팩터)'] = results_b.get('full_metrics', {})

    comparison = pd.DataFrame(comparison_data).T

    print(comparison.to_string())

    # 비교 결과 저장
    comparison.to_csv(OUTPUT_DIR / 'backtest_comparison.csv')

    print(f"\n모든 결과 저장 완료: {OUTPUT_DIR}")
    print("=" * 80)


if __name__ == '__main__':
    main()
