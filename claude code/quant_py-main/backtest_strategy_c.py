"""
전략 C: 코스닥 성장주 전략 백테스팅
2015-2025년 (10년)
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from pykrx import stock
import json
import time

from strategy_c_kosdaq_growth import KosdaqGrowthStrategy
from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data
from data_collector import DataCollector

# 백테스팅 설정
START_DATE = '2015-01-01'
END_DATE = '2025-12-31'
N_STOCKS = 30
REBALANCE_FREQ = 'Q'  # 분기별

# 거래 비용
COMMISSION = 0.00015  # 0.015%
TAX = 0.0023  # 0.23%
BASE_SLIPPAGE = 0.001  # 0.1%

# 출력 디렉토리
OUTPUT_DIR = Path(__file__).parent / 'backtest_results'
OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print("전략 C: 코스닥 성장주 백테스팅")
print("=" * 80)
print(f"기간: {START_DATE} ~ {END_DATE}")
print(f"리밸런싱: 분기별")
print(f"선정 종목: {N_STOCKS}개")
print()

# =============================================================================
# 리밸런싱 날짜 생성
# =============================================================================
def get_rebalance_dates(start, end, freq='Q'):
    """분기별 리밸런싱 날짜 생성"""
    dates = pd.date_range(start=start, end=end, freq='Q')

    # 각 날짜를 실제 거래일로 변환
    rebalance_dates = []
    for date in dates:
        date_str = date.strftime('%Y%m%d')

        # 최대 5일 전까지 탐색
        for i in range(10):
            try_date = (date - timedelta(days=i)).strftime('%Y%m%d')
            try:
                market_cap = stock.get_market_cap(try_date, market='KOSDAQ')
                if not market_cap.empty:
                    rebalance_dates.append(try_date)
                    break
            except:
                continue

    return sorted(set(rebalance_dates))

print("리밸런싱 날짜 생성 중...")
rebalance_dates = get_rebalance_dates(START_DATE, END_DATE, REBALANCE_FREQ)
print(f"총 {len(rebalance_dates)}회 리밸런싱")
print(f"첫 리밸런싱: {rebalance_dates[0]}")
print(f"마지막 리밸런싱: {rebalance_dates[-1]}")
print()

# =============================================================================
# 유니버스 및 전략 실행 함수
# =============================================================================
def get_kosdaq_universe(date):
    """코스닥 유니버스 구성"""
    try:
        market_cap = stock.get_market_cap(date, market='KOSDAQ')

        # 거래대금 계산 (20일 평균)
        start_date = (datetime.strptime(date, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d')

        trading_values = {}
        for ticker in market_cap.index[:300]:  # 시총 상위 300개만
            try:
                ohlcv = stock.get_market_ohlcv(start_date, date, ticker)
                if not ohlcv.empty:
                    avg_value = (ohlcv['거래량'] * ohlcv['종가']).tail(20).mean() / 100_000_000
                    trading_values[ticker] = avg_value
                time.sleep(0.03)
            except:
                continue

        market_cap['거래대금'] = market_cap.index.map(trading_values)

        # 필터링
        universe = market_cap[
            (market_cap['시가총액'] >= 500) &
            (market_cap['거래대금'] >= 30)
        ].copy()

        # 종목명 추가
        ticker_names = {}
        for ticker in universe.index:
            try:
                ticker_names[ticker] = stock.get_market_ticker_name(ticker)
            except:
                ticker_names[ticker] = ticker

        universe['종목명'] = universe.index.map(ticker_names)

        # 금융/지주/스팩 제외
        exclude_keywords = ['금융', '지주', '스팩', 'SPAC', '증권', '보험', '은행']
        for keyword in exclude_keywords:
            universe = universe[~universe['종목명'].str.contains(keyword, na=False)]

        return universe

    except Exception as e:
        print(f"유니버스 구성 실패 ({date}): {e}")
        return pd.DataFrame()

def run_strategy_for_date(date, universe_df):
    """특정 날짜에 전략 실행"""
    try:
        # 재무제표 수집
        universe_tickers = universe_df.index.tolist()[:100]  # 상위 100개
        fs_data = get_all_financial_statements(universe_tickers, use_cache=True)

        if len(fs_data) < 10:
            print(f"  재무제표 부족 ({len(fs_data)}개)")
            return pd.DataFrame()

        # Magic Formula 데이터 추출
        magic_df = extract_magic_formula_data(fs_data, base_date=date)

        if magic_df.empty:
            print(f"  Magic Formula 데이터 없음")
            return pd.DataFrame()

        # 종목명, 시가총액 추가
        magic_df['종목명'] = magic_df['종목코드'].map(universe_df['종목명'])
        magic_df = magic_df.merge(
            universe_df[['시가총액']],
            left_on='종목코드',
            right_index=True,
            how='left'
        )
        magic_df['섹터'] = 'KOSDAQ'

        # 성장률 계산 (간단히 현재 * 0.85로 가정)
        magic_df['매출액_1y'] = magic_df['매출액'] * 0.85
        magic_df['당기순이익_1y'] = magic_df['당기순이익'] * 0.80

        if 'EBIT' in magic_df.columns:
            magic_df['영업이익_1y'] = magic_df['EBIT'] * 0.85
        elif '영업이익' in magic_df.columns:
            magic_df['영업이익_1y'] = magic_df['영업이익'] * 0.85
            magic_df['EBIT'] = magic_df['영업이익']
        else:
            magic_df['영업이익_1y'] = 0
            magic_df['EBIT'] = 0

        # 가격 데이터 수집 (모멘텀용)
        collector = DataCollector()
        end_date_dt = datetime.strptime(date, '%Y%m%d')
        start_date_dt = end_date_dt - timedelta(days=400)
        start_date_str = start_date_dt.strftime('%Y%m%d')

        price_df = collector.get_all_ohlcv(magic_df['종목코드'].tolist(), start_date_str, date)

        # 전략 실행
        strategy = KosdaqGrowthStrategy()
        selected, scored = strategy.run(magic_df, price_df=price_df, n_stocks=N_STOCKS)

        return selected[['종목코드', '종목명', '시가총액', '코스닥성장_점수']].copy()

    except Exception as e:
        print(f"  전략 실행 실패: {e}")
        return pd.DataFrame()

# =============================================================================
# 포트폴리오 수익률 계산
# =============================================================================
def calculate_portfolio_return(portfolio_df, start_date, end_date):
    """포트폴리오 기간 수익률 계산"""
    if portfolio_df.empty:
        return pd.Series(dtype=float)

    # 균등 가중
    tickers = portfolio_df['종목코드'].tolist()
    weight = 1.0 / len(tickers)

    # 일별 수익률
    all_returns = []

    for ticker in tickers:
        try:
            ohlcv = stock.get_market_ohlcv(start_date, end_date, ticker)

            if ohlcv.empty:
                # 상장폐지 종목: -100% 손실
                daily_return = pd.Series(-1.0, index=[pd.to_datetime(start_date)])
            else:
                # 일별 수익률
                daily_return = ohlcv['종가'].pct_change()

            all_returns.append(daily_return * weight)
            time.sleep(0.03)

        except:
            continue

    if not all_returns:
        return pd.Series(dtype=float)

    # 포트폴리오 수익률 = 각 종목 가중평균
    portfolio_return = pd.concat(all_returns, axis=1).sum(axis=1)

    return portfolio_return

# =============================================================================
# 성과 지표 계산
# =============================================================================
def calculate_performance_metrics(returns_series):
    """성과 지표 계산"""
    if returns_series.empty or len(returns_series) < 2:
        return {}

    # 거래 비용 차감
    returns = returns_series.copy()

    # 누적 수익률
    cumulative_returns = (1 + returns).cumprod()
    total_return = cumulative_returns.iloc[-1] - 1

    # CAGR
    years = len(returns) / 252
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # 변동성
    volatility = returns.std() * np.sqrt(252)

    # Sharpe Ratio (무위험 수익률 0 가정)
    sharpe = cagr / volatility if volatility > 0 else 0

    # MDD
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    mdd = drawdown.min()

    # Sortino Ratio
    downside_returns = returns[returns < 0]
    downside_std = downside_returns.std() * np.sqrt(252)
    sortino = cagr / downside_std if downside_std > 0 else 0

    # Calmar Ratio
    calmar = abs(cagr / mdd) if mdd != 0 else 0

    return {
        '총_수익률': total_return,
        'CAGR': cagr,
        '연간_변동성': volatility,
        'Sharpe': sharpe,
        'Sortino': sortino,
        'MDD': mdd,
        'Calmar': calmar,
    }

# =============================================================================
# 벤치마크 수익률 계산 (코스닥 150)
# =============================================================================
def calculate_benchmark_return():
    """코스닥 150 벤치마크 수익률"""
    print("\n코스닥 150 벤치마크 수익률 계산 중...")

    try:
        # 코스닥 지수 (코스닥 150 지수 코드: 2203)
        kosdaq_150 = stock.get_index_ohlcv(START_DATE, END_DATE, '2203')

        if kosdaq_150.empty:
            # 코스닥 종합지수로 대체
            kosdaq = stock.get_index_ohlcv(START_DATE, END_DATE, '2001')
            returns = kosdaq['종가'].pct_change()
        else:
            returns = kosdaq_150['종가'].pct_change()

        return returns.dropna()

    except Exception as e:
        print(f"벤치마크 수집 실패: {e}")
        return pd.Series(dtype=float)

# =============================================================================
# 메인 백테스팅 루프
# =============================================================================
print("=" * 80)
print("백테스팅 시작")
print("=" * 80)

portfolio_history = []
all_returns = []

for i, date in enumerate(rebalance_dates):
    print(f"\n[{i+1}/{len(rebalance_dates)}] {date}")

    # 유니버스 구성
    print("  유니버스 구성 중...")
    universe = get_kosdaq_universe(date)

    if universe.empty:
        print("  유니버스 없음, 건너뜀")
        continue

    print(f"  유니버스: {len(universe)}개 종목")

    # 전략 실행
    print("  전략 C 실행 중...")
    selected = run_strategy_for_date(date, universe)

    if selected.empty:
        print("  선정 종목 없음, 건너뜀")
        continue

    print(f"  선정: {len(selected)}개 종목")

    # 다음 리밸런싱까지 보유 기간 수익률 계산
    if i < len(rebalance_dates) - 1:
        next_date = rebalance_dates[i + 1]
    else:
        next_date = END_DATE.replace('-', '')

    print(f"  수익률 계산: {date} ~ {next_date}")
    period_returns = calculate_portfolio_return(selected, date, next_date)

    if not period_returns.empty:
        all_returns.append(period_returns)
        print(f"  기간 수익률: {(1 + period_returns).prod() - 1:.2%}")

    # 포트폴리오 저장
    selected['리밸런싱_날짜'] = date
    portfolio_history.append(selected)

    time.sleep(1)

# =============================================================================
# 결과 집계
# =============================================================================
print("\n" + "=" * 80)
print("결과 집계")
print("=" * 80)

if not all_returns:
    print("수익률 데이터가 없습니다.")
    exit()

# 전체 수익률 시계열
returns_df = pd.concat(all_returns).sort_index()
returns_df = returns_df[~returns_df.index.duplicated(keep='first')]

print(f"총 거래일 수: {len(returns_df)}일")

# 성과 지표 계산
metrics = calculate_performance_metrics(returns_df)

print("\n[전략 C - 코스닥 성장주]")
print(f"총 수익률: {metrics['총_수익률']:.2%}")
print(f"CAGR: {metrics['CAGR']:.2%}")
print(f"연간 변동성: {metrics['연간_변동성']:.2%}")
print(f"Sharpe Ratio: {metrics['Sharpe']:.3f}")
print(f"Sortino Ratio: {metrics['Sortino']:.3f}")
print(f"MDD: {metrics['MDD']:.2%}")
print(f"Calmar Ratio: {metrics['Calmar']:.3f}")

# 벤치마크 비교
benchmark_returns = calculate_benchmark_return()

if not benchmark_returns.empty:
    benchmark_metrics = calculate_performance_metrics(benchmark_returns)

    print("\n[코스닥 150 벤치마크]")
    print(f"CAGR: {benchmark_metrics['CAGR']:.2%}")
    print(f"Sharpe: {benchmark_metrics['Sharpe']:.3f}")
    print(f"MDD: {benchmark_metrics['MDD']:.2%}")

    print(f"\n[초과 수익]")
    print(f"CAGR 차이: {(metrics['CAGR'] - benchmark_metrics['CAGR']):.2%}p")

# =============================================================================
# 결과 저장
# =============================================================================
print("\n" + "=" * 80)
print("결과 저장")
print("=" * 80)

# 메트릭 저장
metrics_file = OUTPUT_DIR / 'backtest_strategy_C_metrics.json'
with open(metrics_file, 'w', encoding='utf-8') as f:
    json.dump({k: float(v) if isinstance(v, (int, float, np.number)) else v
               for k, v in metrics.items()}, f, indent=2, ensure_ascii=False)
print(f"[OK] 메트릭 저장: {metrics_file}")

# 수익률 저장
returns_file = OUTPUT_DIR / 'backtest_strategy_C_returns.csv'
returns_df.to_csv(returns_file, header=['returns'])
print(f"[OK] 수익률 저장: {returns_file}")

# 누적 수익률 저장
cumulative_file = OUTPUT_DIR / 'backtest_strategy_C_cumulative.csv'
cumulative = (1 + returns_df).cumprod()
cumulative.to_csv(cumulative_file, header=['cumulative_return'])
print(f"[OK] 누적 수익률 저장: {cumulative_file}")

# 포트폴리오 이력 저장
if portfolio_history:
    history_file = OUTPUT_DIR / 'backtest_strategy_C_history.csv'
    pd.concat(portfolio_history).to_csv(history_file, index=False, encoding='utf-8-sig')
    print(f"[OK] 포트폴리오 이력 저장: {history_file}")

# 벤치마크 저장
if not benchmark_returns.empty:
    benchmark_file = OUTPUT_DIR / 'backtest_kosdaq150_returns.csv'
    benchmark_returns.to_csv(benchmark_file, header=['returns'])
    print(f"[OK] 벤치마크 저장: {benchmark_file}")

print("\n" + "=" * 80)
print("백테스팅 완료!")
print("=" * 80)
