"""
전체 백테스트 실행 스크립트 (개선 버전)
- 전략 A, B, C + 벤치마크 비교
- 안정적인 데이터 수집
- 상장폐지 처리 개선
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from pykrx import stock
import json
import time
import warnings

warnings.filterwarnings('ignore')

# 설정
START_DATE = '20150101'
END_DATE = '20250131'
IS_END_DATE = '20231231'
N_STOCKS = 20
MIN_MARKET_CAP = 1000  # 억원
MIN_TRADING_VALUE = 30  # 억원

# 거래비용
COMMISSION = 0.00015
TAX = 0.0023
SLIPPAGE = 0.001

OUTPUT_DIR = Path(__file__).parent / 'backtest_results'
OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print("한국 주식 멀티팩터 전략 백테스팅 시스템 (개선 버전)")
print(f"기간: {START_DATE} ~ {END_DATE}")
print("=" * 80)


def get_rebalance_dates(start_year=2015, end_year=2025):
    """분기별 리밸런싱 날짜 생성"""
    dates = []
    for year in range(start_year, end_year + 1):
        for month in [3, 6, 9, 12]:
            if month == 12:
                date = f"{year}1231"
            else:
                next_month = month + 1
                last_day = (datetime(year, next_month, 1) - timedelta(days=1)).day
                date = f"{year}{month:02d}{last_day:02d}"

            # 유효한 거래일 찾기
            for i in range(10):
                try_date = (datetime.strptime(date, '%Y%m%d') - timedelta(days=i)).strftime('%Y%m%d')
                try:
                    if try_date > END_DATE:
                        continue
                    mcap = stock.get_market_cap(try_date, market='KOSPI')
                    if not mcap.empty:
                        dates.append(try_date)
                        break
                except:
                    continue

    return sorted(set(dates))


def get_universe(date, market='ALL'):
    """유니버스 구성"""
    try:
        if market == 'ALL':
            kospi = stock.get_market_cap(date, market='KOSPI')
            kosdaq = stock.get_market_cap(date, market='KOSDAQ')
            kospi['시장'] = 'KOSPI'
            kosdaq['시장'] = 'KOSDAQ'
            df = pd.concat([kospi, kosdaq])
        else:
            df = stock.get_market_cap(date, market=market)
            df['시장'] = market

        # 시가총액 필터 (억원)
        df['시가총액_억'] = df['시가총액'] / 100_000_000
        df = df[df['시가총액_억'] >= MIN_MARKET_CAP]

        # 거래대금 필터 (억원)
        df['거래대금_억'] = df['거래대금'] / 100_000_000
        df = df[df['거래대금_억'] >= MIN_TRADING_VALUE]

        # 종목명 추가
        names = {}
        for ticker in df.index[:200]:  # 상위 200개만
            try:
                names[ticker] = stock.get_market_ticker_name(ticker)
            except:
                names[ticker] = ticker
        df['종목명'] = df.index.map(names)

        # 금융/지주/스팩 제외
        exclude = ['금융', '은행', '증권', '보험', '지주', '홀딩스', 'SPAC', '스팩', '리츠']
        for kw in exclude:
            df = df[~df['종목명'].fillna('').str.contains(kw)]

        return df

    except Exception as e:
        print(f"유니버스 구성 실패 ({date}): {e}")
        return pd.DataFrame()


def get_fundamentals(tickers, date, market='ALL'):
    """기본적 지표 계산 (PER, PBR 기반)"""
    try:
        # Fundamental 데이터 조회
        if market == 'KOSDAQ':
            fund_data = stock.get_market_fundamental(date, market='KOSDAQ')
        elif market == 'KOSPI':
            fund_data = stock.get_market_fundamental(date, market='KOSPI')
        else:
            # ALL: 코스피 + 코스닥 합치기
            kospi_fund = stock.get_market_fundamental(date, market='KOSPI')
            kosdaq_fund = stock.get_market_fundamental(date, market='KOSDAQ')
            fund_data = pd.concat([kospi_fund, kosdaq_fund])

        if fund_data.empty:
            return pd.DataFrame()

        # 유효한 티커만 필터
        valid_tickers = [t for t in tickers if t in fund_data.index]

        if not valid_tickers:
            return pd.DataFrame()

        result = fund_data.loc[valid_tickers].copy()
        result['종목코드'] = result.index

        return result

    except Exception as e:
        print(f"Fundamental 조회 실패: {e}")
        return pd.DataFrame()


def calculate_value_score(fund_df):
    """밸류 점수 계산 (PER, PBR 역수)"""
    df = fund_df.copy()

    # PER 점수 (낮을수록 좋음, 양수만)
    df['PER'] = pd.to_numeric(df['PER'], errors='coerce')
    df = df[(df['PER'] > 0) & (df['PER'] < 100)]  # 이상치 제거

    if df.empty:
        return df

    df['PER_점수'] = 1 - (df['PER'].rank(pct=True))

    # PBR 점수 (낮을수록 좋음, 양수만)
    df['PBR'] = pd.to_numeric(df['PBR'], errors='coerce')
    df = df[(df['PBR'] > 0) & (df['PBR'] < 10)]
    df['PBR_점수'] = 1 - (df['PBR'].rank(pct=True))

    # 밸류 점수 = PER 50% + PBR 50%
    df['밸류_점수'] = df['PER_점수'] * 0.5 + df['PBR_점수'] * 0.5

    return df


def calculate_momentum_score(tickers, end_date):
    """모멘텀 점수 계산 (12개월 - 1개월)"""
    end_dt = datetime.strptime(end_date, '%Y%m%d')
    start_12m = (end_dt - timedelta(days=365)).strftime('%Y%m%d')
    start_1m = (end_dt - timedelta(days=30)).strftime('%Y%m%d')

    momentum_data = {}

    for ticker in tickers:
        try:
            ohlcv = stock.get_market_ohlcv(start_12m, end_date, ticker)

            if len(ohlcv) < 60:  # 최소 60일 데이터 필요
                continue

            # 12개월 수익률
            first_price = ohlcv['종가'].iloc[0]
            last_price = ohlcv['종가'].iloc[-1]
            mom_12m = (last_price / first_price) - 1

            # 최근 1개월 수익률 (제외할 부분)
            ohlcv_1m = ohlcv[ohlcv.index >= start_1m]
            if len(ohlcv_1m) >= 5:
                mom_1m = (ohlcv_1m['종가'].iloc[-1] / ohlcv_1m['종가'].iloc[0]) - 1
            else:
                mom_1m = 0

            # 12-1 모멘텀
            momentum_data[ticker] = mom_12m - mom_1m

        except:
            continue

    if not momentum_data:
        return pd.DataFrame()

    mom_df = pd.DataFrame.from_dict(momentum_data, orient='index', columns=['모멘텀'])
    mom_df['종목코드'] = mom_df.index
    mom_df['모멘텀_점수'] = mom_df['모멘텀'].rank(pct=True)

    return mom_df


def run_strategy_a(universe_df, date):
    """전략 A: 마법공식 (PER + ROE 기반 간소화)"""
    tickers = universe_df.index.tolist()[:100]

    fund_df = get_fundamentals(tickers, date)
    if fund_df.empty:
        return pd.DataFrame()

    # 밸류 점수
    fund_df = calculate_value_score(fund_df)
    if fund_df.empty:
        return pd.DataFrame()

    # 퀄리티 점수 (DIV 사용, 없으면 0)
    fund_df['DIV'] = pd.to_numeric(fund_df.get('DIV', 0), errors='coerce').fillna(0)
    fund_df['퀄리티_점수'] = fund_df['DIV'].rank(pct=True)

    # 마법공식 점수 = 밸류 50% + 퀄리티 50%
    fund_df['마법공식_점수'] = fund_df['밸류_점수'] * 0.5 + fund_df['퀄리티_점수'] * 0.5

    # 상위 N개 선정
    selected = fund_df.nlargest(N_STOCKS, '마법공식_점수')

    # 종목명 추가
    selected['종목명'] = selected['종목코드'].map(universe_df['종목명'])
    selected['시가총액'] = selected['종목코드'].map(universe_df['시가총액_억'])

    return selected[['종목코드', '종목명', '시가총액', 'PER', 'PBR', '마법공식_점수']]


def run_strategy_b(universe_df, date):
    """전략 B: 멀티팩터 (밸류 + 모멘텀)"""
    tickers = universe_df.index.tolist()[:100]

    # 밸류 점수
    fund_df = get_fundamentals(tickers, date)
    if fund_df.empty:
        return pd.DataFrame()

    fund_df = calculate_value_score(fund_df)
    if fund_df.empty:
        return pd.DataFrame()

    # 모멘텀 점수
    mom_df = calculate_momentum_score(fund_df['종목코드'].tolist(), date)

    if mom_df.empty:
        # 모멘텀 없으면 밸류만으로 선정
        fund_df['멀티팩터_점수'] = fund_df['밸류_점수']
    else:
        # 병합
        fund_df = fund_df.merge(mom_df[['종목코드', '모멘텀_점수']], on='종목코드', how='left')
        fund_df['모멘텀_점수'] = fund_df['모멘텀_점수'].fillna(0.5)

        # 멀티팩터 점수 = 밸류 60% + 모멘텀 40%
        fund_df['멀티팩터_점수'] = fund_df['밸류_점수'] * 0.6 + fund_df['모멘텀_점수'] * 0.4

    # 상위 N개 선정
    selected = fund_df.nlargest(N_STOCKS, '멀티팩터_점수')

    selected['종목명'] = selected['종목코드'].map(universe_df['종목명'])
    selected['시가총액'] = selected['종목코드'].map(universe_df['시가총액_억'])

    return selected[['종목코드', '종목명', '시가총액', 'PER', 'PBR', '멀티팩터_점수']]


def run_strategy_c(date):
    """전략 C: 코스닥 성장주"""
    try:
        # 코스닥 시가총액 조회
        kosdaq_df = stock.get_market_cap(date, market='KOSDAQ')

        if kosdaq_df.empty:
            return pd.DataFrame()

        # 시가총액 필터 (억원)
        kosdaq_df['시가총액_억'] = kosdaq_df['시가총액'] / 100_000_000
        kosdaq_df = kosdaq_df[kosdaq_df['시가총액_억'] >= 500]  # 코스닥은 500억 이상

        # 거래대금 필터
        kosdaq_df['거래대금_억'] = kosdaq_df['거래대금'] / 100_000_000
        kosdaq_df = kosdaq_df[kosdaq_df['거래대금_억'] >= 20]  # 20억 이상

        # 종목명 추가
        names = {}
        for ticker in kosdaq_df.index[:150]:
            try:
                names[ticker] = stock.get_market_ticker_name(ticker)
            except:
                names[ticker] = ticker
        kosdaq_df['종목명'] = kosdaq_df.index.map(names)

        # 금융/스팩 제외
        exclude = ['금융', '증권', '보험', '스팩', 'SPAC', '리츠']
        for kw in exclude:
            kosdaq_df = kosdaq_df[~kosdaq_df['종목명'].fillna('').str.contains(kw)]

        tickers = kosdaq_df.index.tolist()[:100]

        # Fundamental 조회 (코스닥 전용)
        fund_df = get_fundamentals(tickers, date, market='KOSDAQ')
        if fund_df.empty:
            return pd.DataFrame()

        fund_df = calculate_value_score(fund_df)
        if fund_df.empty:
            return pd.DataFrame()

        # 모멘텀 점수
        mom_df = calculate_momentum_score(fund_df['종목코드'].tolist(), date)

        if not mom_df.empty:
            fund_df = fund_df.merge(mom_df[['종목코드', '모멘텀_점수']], on='종목코드', how='left')
            fund_df['모멘텀_점수'] = fund_df['모멘텀_점수'].fillna(0.5)
        else:
            fund_df['모멘텀_점수'] = 0.5

        # 코스닥 성장주 점수 = 밸류 40% + 모멘텀 60%
        fund_df['성장주_점수'] = fund_df['밸류_점수'] * 0.4 + fund_df['모멘텀_점수'] * 0.6

        # 상위 N개 선정
        selected = fund_df.nlargest(N_STOCKS, '성장주_점수')

        selected['종목명'] = selected['종목코드'].map(kosdaq_df['종목명'])
        selected['시가총액'] = selected['종목코드'].map(kosdaq_df['시가총액_억'])

        return selected[['종목코드', '종목명', '시가총액', 'PER', 'PBR', '성장주_점수']]

    except Exception as e:
        print(f"전략 C 실행 실패: {e}")
        return pd.DataFrame()


def calculate_portfolio_return(portfolio_df, start_date, end_date):
    """포트폴리오 수익률 계산 (개선된 버전)"""
    if portfolio_df.empty:
        return pd.Series(dtype=float)

    tickers = portfolio_df['종목코드'].tolist()
    weight = 1.0 / len(tickers)

    all_returns = []
    valid_count = 0

    for ticker in tickers:
        try:
            ohlcv = stock.get_market_ohlcv(start_date, end_date, ticker)

            if ohlcv.empty or len(ohlcv) < 5:
                continue  # 데이터 없으면 스킵 (상장폐지 -100% 대신)

            daily_return = ohlcv['종가'].pct_change()
            all_returns.append(daily_return * weight)
            valid_count += 1

        except:
            continue

    if not all_returns:
        return pd.Series(dtype=float)

    # 가중치 재조정 (유효한 종목만으로)
    if valid_count < len(tickers):
        adjustment = len(tickers) / valid_count
        all_returns = [r * adjustment for r in all_returns]

    portfolio_return = pd.concat(all_returns, axis=1).sum(axis=1)

    # 거래비용 차감 (첫날: 매수, 마지막날: 매도)
    total_cost = COMMISSION + SLIPPAGE  # 매수
    if len(portfolio_return) > 0:
        portfolio_return.iloc[0] -= total_cost
    if len(portfolio_return) > 1:
        portfolio_return.iloc[-1] -= (COMMISSION + TAX + SLIPPAGE)  # 매도

    return portfolio_return


def calculate_metrics(returns):
    """성과 지표 계산"""
    if returns.empty or len(returns) < 20:
        return {}

    # 누적 수익률
    cumulative = (1 + returns).cumprod()
    total_return = cumulative.iloc[-1] - 1

    # 연간 거래일
    years = len(returns) / 252

    # CAGR
    if cumulative.iloc[-1] > 0:
        cagr = (cumulative.iloc[-1]) ** (1 / years) - 1
    else:
        cagr = -1

    # 변동성
    volatility = returns.std() * np.sqrt(252)

    # MDD
    peak = cumulative.cummax()
    drawdown = (cumulative - peak) / peak
    mdd = drawdown.min()

    # Sharpe (무위험 수익률 3% 가정)
    rf = 0.03
    sharpe = (cagr - rf) / volatility if volatility > 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 0
    sortino = (cagr - rf) / downside_std if downside_std > 0 else 0

    # Win Rate
    win_rate = (returns > 0).sum() / len(returns) * 100

    return {
        'total_return': total_return * 100,
        'cagr': cagr * 100,
        'volatility': volatility * 100,
        'mdd': mdd * 100,
        'sharpe': sharpe,
        'sortino': sortino,
        'win_rate': win_rate,
        'trading_days': len(returns)
    }


def run_benchmark():
    """벤치마크 (코스피200, 코스닥150) 수익률"""
    benchmarks = {}

    for code, name in [('1028', '코스피200'), ('2203', '코스닥150')]:
        try:
            idx = stock.get_index_ohlcv(START_DATE, END_DATE, code)

            if idx.empty:
                continue

            # 종가 컬럼 찾기
            close_col = [c for c in idx.columns if '종가' in c]
            if close_col:
                returns = idx[close_col[0]].pct_change().dropna()
            else:
                returns = idx.iloc[:, 3].pct_change().dropna()

            benchmarks[name] = {
                'returns': returns,
                'metrics': calculate_metrics(returns)
            }

            print(f"\n[벤치마크 - {name}]")
            print(f"  CAGR: {benchmarks[name]['metrics'].get('cagr', 0):.2f}%")
            print(f"  MDD: {benchmarks[name]['metrics'].get('mdd', 0):.2f}%")
            print(f"  Sharpe: {benchmarks[name]['metrics'].get('sharpe', 0):.2f}")

        except Exception as e:
            print(f"벤치마크 {name} 실패: {e}")

    return benchmarks


def run_backtest(strategy_func, strategy_name, rebalance_dates, universe_func=None):
    """백테스트 실행"""
    print(f"\n{'='*80}")
    print(f"전략 {strategy_name} 백테스트 시작")
    print(f"{'='*80}")

    all_returns = []
    portfolio_history = []

    for i, date in enumerate(rebalance_dates[:-1]):
        next_date = rebalance_dates[i + 1]
        print(f"\n[{i+1}/{len(rebalance_dates)-1}] {date} → {next_date}")

        # 유니버스
        if universe_func:
            universe_df = universe_func(date)
        else:
            universe_df = get_universe(date)

        if universe_df.empty:
            print("  유니버스 없음, 스킵")
            continue

        print(f"  유니버스: {len(universe_df)}개")

        # 전략 실행
        if strategy_name == 'C':
            selected = strategy_func(date)
        else:
            selected = strategy_func(universe_df, date)

        if selected.empty:
            print("  선정 종목 없음, 스킵")
            continue

        print(f"  선정: {len(selected)}개 종목")

        # 수익률 계산
        period_returns = calculate_portfolio_return(selected, date, next_date)

        if not period_returns.empty:
            all_returns.append(period_returns)
            period_total = (1 + period_returns).prod() - 1
            print(f"  기간 수익률: {period_total*100:.2f}%")

        # 이력 저장
        selected['rebalance_date'] = date
        portfolio_history.append(selected)

        time.sleep(0.5)  # API 부하 방지

    # 결과 집계
    if not all_returns:
        print("수익률 데이터 없음")
        return pd.Series(dtype=float), {}

    full_returns = pd.concat(all_returns)
    full_returns = full_returns[~full_returns.index.duplicated(keep='first')]
    full_returns = full_returns.sort_index()

    # 성과 지표
    metrics = calculate_metrics(full_returns)

    # IS/OOS 분리
    is_returns = full_returns[full_returns.index <= IS_END_DATE]
    oos_returns = full_returns[full_returns.index > IS_END_DATE]

    is_metrics = calculate_metrics(is_returns)
    oos_metrics = calculate_metrics(oos_returns)

    # 결과 출력
    print(f"\n{'='*80}")
    print(f"전략 {strategy_name} 결과")
    print(f"{'='*80}")
    print(f"\n[전체 기간]")
    print(f"  총 수익률: {metrics.get('total_return', 0):.2f}%")
    print(f"  CAGR: {metrics.get('cagr', 0):.2f}%")
    print(f"  변동성: {metrics.get('volatility', 0):.2f}%")
    print(f"  MDD: {metrics.get('mdd', 0):.2f}%")
    print(f"  Sharpe: {metrics.get('sharpe', 0):.2f}")
    print(f"  Sortino: {metrics.get('sortino', 0):.2f}")
    print(f"  Win Rate: {metrics.get('win_rate', 0):.2f}%")

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
        'strategy': strategy_name,
        'period': f"{START_DATE} ~ {END_DATE}",
        'full_metrics': metrics,
        'is_metrics': is_metrics,
        'oos_metrics': oos_metrics,
        'n_rebalances': len(portfolio_history)
    }

    # 파일 저장
    with open(OUTPUT_DIR / f'backtest_strategy_{strategy_name}_metrics.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    full_returns.to_csv(OUTPUT_DIR / f'backtest_strategy_{strategy_name}_returns.csv')

    cumulative = (1 + full_returns).cumprod()
    cumulative.to_csv(OUTPUT_DIR / f'backtest_strategy_{strategy_name}_cumulative.csv')

    if portfolio_history:
        pd.concat(portfolio_history).to_csv(
            OUTPUT_DIR / f'backtest_strategy_{strategy_name}_history.csv',
            index=False, encoding='utf-8-sig'
        )

    return full_returns, results


def main():
    """메인 실행"""
    # 리밸런싱 날짜
    print("\n리밸런싱 날짜 생성 중...")
    rebalance_dates = get_rebalance_dates(2015, 2025)
    print(f"총 {len(rebalance_dates)}회 리밸런싱")

    # 벤치마크
    print("\n벤치마크 계산 중...")
    benchmarks = run_benchmark()

    # 벤치마크 저장
    for name, data in benchmarks.items():
        filename = f"backtest_{name.replace(' ', '_')}_returns.csv"
        data['returns'].to_csv(OUTPUT_DIR / filename)

    # 전략 백테스트
    results = {}

    # 전략 A
    returns_a, results_a = run_backtest(run_strategy_a, 'A', rebalance_dates)
    results['A'] = results_a

    # 전략 B
    returns_b, results_b = run_backtest(run_strategy_b, 'B', rebalance_dates)
    results['B'] = results_b

    # 전략 C
    returns_c, results_c = run_backtest(run_strategy_c, 'C', rebalance_dates)
    results['C'] = results_c

    # 최종 비교
    print("\n" + "=" * 80)
    print("최종 비교 리포트")
    print("=" * 80)

    comparison_data = {}

    # 벤치마크
    for name, data in benchmarks.items():
        comparison_data[name] = data['metrics']

    # 전략
    for strategy_name, result in results.items():
        if result:
            comparison_data[f'전략 {strategy_name}'] = result.get('full_metrics', {})

    comparison = pd.DataFrame(comparison_data).T
    print(comparison.to_string())

    # 비교 결과 저장
    comparison.to_csv(OUTPUT_DIR / 'backtest_comparison.csv', encoding='utf-8-sig')

    print(f"\n모든 결과 저장 완료: {OUTPUT_DIR}")
    print("=" * 80)

    return comparison


if __name__ == '__main__':
    comparison = main()
