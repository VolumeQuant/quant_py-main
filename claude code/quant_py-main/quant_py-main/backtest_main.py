"""
한국 주식 멀티팩터 전략 백테스팅 메인 스크립트

전략 A: 마법공식
전략 B: 멀티팩터 (밸류 + 퀄리티 + 모멘텀)
벤치마크: 코스피 지수

IS: 2015-2023
OOS: 2024-2025
"""

import pandas as pd
import numpy as np
import bt
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 로컬 모듈
from data_collector import DataCollector
from utils import filter_universe, get_rebalancing_dates
from strategy_a_magic import MagicFormulaStrategy
from strategy_b_multifactor import MultiFactorStrategy

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False


class FactorBacktest:
    """팩터 백테스트 클래스"""

    def __init__(self, start_date='20150101', end_date='20251231'):
        self.start_date = start_date
        self.end_date = end_date
        self.collector = DataCollector(start_date, end_date)

        # 전략 초기화
        self.strategy_a = MagicFormulaStrategy()
        self.strategy_b = MultiFactorStrategy()

        # 리밸런싱 날짜 (분기별: 3, 6, 9, 12월 말)
        self.rebalancing_dates = None

        # 데이터 저장
        self.price_data = None
        self.benchmark_data = None
        self.universe = None

    def load_data(self):
        """데이터 로드"""
        print("=" * 80)
        print("1. 데이터 로드 중...")
        print("=" * 80)

        # 코스피 벤치마크 데이터
        print("\n[벤치마크] 코스피 지수 로드")
        self.benchmark_data = self.collector.get_index_ohlcv(ticker='1001')
        print(f"코스피 데이터: {len(self.benchmark_data)} days")

        # 종목 리스트 (최신 시점 기준)
        print("\n[종목] 종목 리스트 로드")
        tickers_df = self.collector.get_ticker_list('20251231', market='ALL')
        tickers = tickers_df['종목코드'].tolist()
        print(f"전체 종목 수: {len(tickers)}")

        # 주가 데이터 로드
        print("\n[주가] OHLCV 데이터 로드 (캐시 사용 권장)")
        self.price_data = self.collector.get_all_ohlcv(tickers)
        print(f"주가 데이터: {self.price_data.shape}")

        return True

    def filter_universe_by_date(self, date):
        """특정 날짜의 유니버스 필터링"""

        # 시가총액 데이터
        market_cap_df = self.collector.get_market_cap(date, market='ALL')

        # 펀더멘털 데이터
        tickers = market_cap_df.index.tolist()
        fundamental_df = self.collector.get_all_fundamentals(date, tickers)

        # 유니버스 필터링
        universe = filter_universe(
            market_cap_df,
            self.price_data,
            fundamental_df,
            min_market_cap=100_000_000_000,  # 1,000억
            min_avg_trading_value=1_000_000_000,  # 10억
        )

        return universe, market_cap_df, fundamental_df

    def run_strategy_on_date(self, date, strategy_type='A'):
        """특정 날짜에 전략 실행하여 종목 선정"""

        print(f"\n[{date}] {strategy_type} 전략 실행 중...")

        # 유니버스 필터링
        universe, market_cap_df, fundamental_df = self.filter_universe_by_date(date)

        if strategy_type == 'A':
            # 마법공식
            # 재무제표 데이터 필요 (실제 구현 시 추가)
            # 여기서는 임시로 빈 리스트 반환
            print("  주의: 마법공식은 상세 재무제표 데이터가 필요합니다.")
            selected_tickers = []

        elif strategy_type == 'B':
            # 멀티팩터
            # 펀더멘털 데이터로 팩터 계산
            selected_tickers, scored_data = self.strategy_b.run(
                fundamental_df,
                price_df=self.price_data,
                n_stocks=20
            )
            selected_tickers = selected_tickers['종목코드'].tolist()

        print(f"  선정 종목: {len(selected_tickers)}개")
        return selected_tickers

    def create_bt_strategy(self, strategy_name, rebalancing_func, price_data):
        """bt 패키지용 전략 생성

        Args:
            strategy_name: 전략 이름
            rebalancing_func: 리밸런싱 함수 (날짜별 종목 선정)
            price_data: 가격 데이터

        Returns:
            bt.Backtest 객체
        """
        # 동일비중 + 분기별 리밸런싱 전략
        strategy = bt.Strategy(
            strategy_name,
            [
                bt.algos.SelectAll(),
                bt.algos.WeighEqually(),
                bt.algos.RunQuarterly(),  # 분기별
                bt.algos.Rebalance()
            ]
        )

        # 백테스트 생성
        backtest = bt.Backtest(
            strategy,
            price_data,
            commissions=lambda q, p: abs(q) * p * 0.005  # 0.5% 거래비용
        )

        return backtest

    def run_backtest(self):
        """백테스트 실행"""

        print("\n" + "=" * 80)
        print("2. 백테스트 실행 중...")
        print("=" * 80)

        # 벤치마크 (코스피)
        benchmark_prices = self.benchmark_data[['종가']].copy()
        benchmark_prices.columns = ['KOSPI']

        # 간단한 예제: 전체 기간 동일비중 백테스트
        # 실제로는 리밸런싱 날짜마다 종목 선정 필요

        # 예시: 상위 50개 종목으로 포트폴리오 구성
        top_tickers = self.price_data.iloc[-1].nlargest(50).index.tolist()
        portfolio_prices = self.price_data[top_tickers].dropna()

        # 전략 A (임시)
        strategy_a_bt = self.create_bt_strategy(
            '전략A_마법공식',
            None,
            portfolio_prices
        )

        # 전략 B (임시)
        strategy_b_bt = self.create_bt_strategy(
            '전략B_멀티팩터',
            None,
            portfolio_prices
        )

        # 벤치마크
        benchmark_bt = bt.Backtest(
            bt.Strategy('코스피', [
                bt.algos.SelectAll(),
                bt.algos.WeighEqually(),
                bt.algos.RunOnce(),
                bt.algos.Rebalance()
            ]),
            benchmark_prices
        )

        # 백테스트 실행
        print("\nbt.run() 실행 중...")
        result = bt.run(strategy_a_bt, strategy_b_bt, benchmark_bt)

        return result

    def analyze_results(self, result, is_period_name='IS', oos_period_name='OOS'):
        """백테스트 결과 분석"""

        print("\n" + "=" * 80)
        print("3. 성과 분석 중...")
        print("=" * 80)

        # 전체 기간 성과
        print("\n[전체 기간 성과 지표]")
        result.display()

        # IS vs OOS 분리 분석
        # (실제 구현 시 날짜로 분리)

        return result

    def visualize_results(self, result):
        """결과 시각화"""

        print("\n" + "=" * 80)
        print("4. 시각화 중...")
        print("=" * 80)

        # 1. 누적수익률 차트
        fig, axes = plt.subplots(3, 1, figsize=(14, 12))

        # 누적수익률
        result.prices.plot(ax=axes[0], title='누적수익률', lw=2)
        axes[0].set_ylabel('Index (Base=100)')
        axes[0].legend(loc='best')
        axes[0].grid(True, alpha=0.3)

        # 연도별 수익률
        yearly_returns = result.prices.resample('Y').last().pct_change()
        yearly_returns.plot(kind='bar', ax=axes[1], title='연도별 수익률')
        axes[1].set_ylabel('Return (%)')
        axes[1].legend(loc='best')
        axes[1].grid(True, alpha=0.3)

        # Drawdown
        result.prices.to_drawdown_series().plot(ax=axes[2], title='Drawdown', lw=2)
        axes[2].set_ylabel('Drawdown (%)')
        axes[2].legend(loc='best')
        axes[2].grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig('backtest_results.png', dpi=150, bbox_inches='tight')
        print("\n차트 저장: backtest_results.png")

        plt.show()

    def get_current_portfolio(self, date='20251231', strategy_type='A', n_stocks=20):
        """현재 포트폴리오 조회 (2026년 1월 기준 = 2025년 12월 말 리밸런싱)"""

        print("\n" + "=" * 80)
        print(f"5. {strategy_type} 전략 현재 포트폴리오 ({date})")
        print("=" * 80)

        selected_tickers = self.run_strategy_on_date(date, strategy_type)

        # 종목 정보 조회
        portfolio_info = []
        for ticker in selected_tickers:
            # 종목 상세 정보 (임시)
            portfolio_info.append({
                '순위': len(portfolio_info) + 1,
                '종목코드': ticker,
                '종목명': '-',  # 실제로는 조회 필요
                '섹터': '-',
                '팩터값': '-'
            })

        portfolio_df = pd.DataFrame(portfolio_info)
        print(portfolio_df.to_string(index=False))

        return portfolio_df

    def run_full_backtest(self):
        """전체 백테스트 파이프라인 실행"""

        # 1. 데이터 로드
        self.load_data()

        # 2. 백테스트 실행
        result = self.run_backtest()

        # 3. 결과 분석
        self.analyze_results(result)

        # 4. 시각화
        self.visualize_results(result)

        # 5. 현재 포트폴리오
        portfolio_a = self.get_current_portfolio(strategy_type='A')
        portfolio_b = self.get_current_portfolio(strategy_type='B')

        return result, portfolio_a, portfolio_b


if __name__ == '__main__':
    print("=" * 80)
    print("한국 주식 멀티팩터 전략 백테스팅 시스템")
    print("=" * 80)

    # 백테스트 실행
    backtest = FactorBacktest(start_date='20150101', end_date='20251231')

    # 전체 파이프라인 실행
    result, portfolio_a, portfolio_b = backtest.run_full_backtest()

    print("\n" + "=" * 80)
    print("백테스트 완료!")
    print("=" * 80)
