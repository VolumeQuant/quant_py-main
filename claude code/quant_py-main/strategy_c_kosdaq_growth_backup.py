"""
전략 C: 코스닥 성장주 전략
성장성 + 모멘텀 + 퀄리티 결합 (코스닥 특화)

정부의 코스닥 3000 목표 및 기관 자금 유입을 활용한 성장주 전략
"""

import pandas as pd
import numpy as np
from scipy import stats


class KosdaqGrowthStrategy:
    """코스닥 성장주 전략"""

    def __init__(self):
        self.name = "KOSDAQ Growth (Growth + Momentum + Quality)"

        # 팩터 가중치
        self.growth_weight = 0.50  # 성장성 50%
        self.momentum_weight = 0.30  # 모멘텀 30%
        self.quality_weight = 0.20  # 퀄리티 20%

    def calculate_growth_factors(self, data):
        """
        성장성 팩터 계산

        코스닥 특화: 매출/순이익 성장률이 핵심

        Args:
            data: 재무 데이터프레임 (현재 + 과거 데이터 필요)

        Returns:
            data: 성장성 팩터가 추가된 데이터프레임
        """
        # 매출 성장률 (YoY)
        if '매출액' in data.columns and '매출액_1y' in data.columns:
            data['매출성장률'] = (data['매출액'] / data['매출액_1y'] - 1) * 100
        elif '매출액' in data.columns:
            # 과거 데이터가 없으면 매출액 자체로 대체 (성장 기대)
            data['매출성장률'] = 0

        # 순이익 성장률 (YoY)
        if '당기순이익' in data.columns and '당기순이익_1y' in data.columns:
            data['순이익성장률'] = (data['당기순이익'] / data['당기순이익_1y'] - 1) * 100
        elif '당기순이익' in data.columns:
            data['순이익성장률'] = 0

        # 영업이익 성장률 (YoY)
        if '영업이익' in data.columns and '영업이익_1y' in data.columns:
            data['영업이익성장률'] = (data['영업이익'] / data['영업이익_1y'] - 1) * 100
        elif 'EBIT' in data.columns and 'EBIT_1y' in data.columns:
            data['영업이익성장률'] = (data['EBIT'] / data['EBIT_1y'] - 1) * 100
        else:
            data['영업이익성장률'] = 0

        # 극단치 처리 (성장률 -100% ~ 500% 범위로 제한)
        for col in ['매출성장률', '순이익성장률', '영업이익성장률']:
            if col in data.columns:
                data[col] = data[col].clip(-100, 500)

        return data

    def calculate_quality_factors(self, data):
        """
        퀄리티 팩터 계산

        코스닥 특화: 재무 안정성과 수익성

        Args:
            data: 재무 데이터프레임

        Returns:
            data: 퀄리티 팩터가 추가된 데이터프레임
        """
        # ROE (Return on Equity)
        if '당기순이익' in data.columns and '자본' in data.columns:
            data['ROE'] = data['당기순이익'] / data['자본'] * 100

        # 부채비율 (낮을수록 좋음)
        if '총부채' in data.columns and '자본' in data.columns:
            data['부채비율'] = data['총부채'] / data['자본'] * 100

        # 영업이익률
        if '영업이익' in data.columns and '매출액' in data.columns:
            data['영업이익률'] = data['영업이익'] / data['매출액'] * 100
        elif 'EBIT' in data.columns and '매출액' in data.columns:
            data['영업이익률'] = data['EBIT'] / data['매출액'] * 100

        # 극단치 처리
        if 'ROE' in data.columns:
            data['ROE'] = data['ROE'].clip(-100, 100)
        if '부채비율' in data.columns:
            data['부채비율'] = data['부채비율'].clip(0, 1000)
        if '영업이익률' in data.columns:
            data['영업이익률'] = data['영업이익률'].clip(-50, 100)

        return data

    def calculate_momentum(self, data, price_df):
        """
        모멘텀 팩터 계산

        코스닥 특화: 단기 모멘텀 중시 (3개월, 6개월)

        Args:
            data: 재무 데이터프레임
            price_df: 가격 데이터프레임 (날짜 인덱스, 종목코드 컬럼)

        Returns:
            data: 모멘텀 팩터가 추가된 데이터프레임
        """
        # 3개월 모멘텀 (단기)
        lookback_3m = 3 * 21  # 3개월
        skip_days = 5  # 최근 5일 제외 (단기 조정 회피)

        momentum_3m_dict = {}
        momentum_6m_dict = {}

        for ticker in data['종목코드']:
            if ticker in price_df.columns:
                prices = price_df[ticker].dropna()

                if len(prices) < lookback_3m + skip_days:
                    continue

                # 3개월 모멘텀
                end_price = prices.iloc[-(skip_days + 1)]
                start_price_3m = prices.iloc[-(lookback_3m + skip_days + 1)]
                momentum_3m = (end_price / start_price_3m - 1) * 100
                momentum_3m_dict[ticker] = momentum_3m

                # 6개월 모멘텀
                lookback_6m = 6 * 21
                if len(prices) >= lookback_6m + skip_days:
                    start_price_6m = prices.iloc[-(lookback_6m + skip_days + 1)]
                    momentum_6m = (end_price / start_price_6m - 1) * 100
                    momentum_6m_dict[ticker] = momentum_6m

        data['모멘텀_3M'] = data['종목코드'].map(momentum_3m_dict)
        data['모멘텀_6M'] = data['종목코드'].map(momentum_6m_dict)

        # 극단치 처리 (-80% ~ 300%)
        if '모멘텀_3M' in data.columns:
            data['모멘텀_3M'] = data['모멘텀_3M'].clip(-80, 300)
        if '모멘텀_6M' in data.columns:
            data['모멘텀_6M'] = data['모멘텀_6M'].clip(-80, 300)

        return data

    def calculate_zscore_by_sector(self, data, factor_col, sector_col='섹터'):
        """
        섹터별 Z-Score 계산 (섹터 중립화)

        Args:
            data: 데이터프레임
            factor_col: 팩터 컬럼명
            sector_col: 섹터 컬럼명

        Returns:
            zscore_series: Z-Score 시리즈
        """
        if sector_col not in data.columns or data[sector_col].nunique() <= 1:
            # 섹터 정보가 없거나 1개뿐이면 전체 평균으로 계산
            mean = data[factor_col].mean()
            std = data[factor_col].std()
            if std == 0 or pd.isna(std):
                return pd.Series(0, index=data.index)
            return (data[factor_col] - mean) / std
        else:
            # 섹터별 Z-Score
            def safe_zscore(x):
                if len(x) <= 1 or x.std() == 0:
                    return pd.Series(0, index=x.index)
                return (x - x.mean()) / x.std()

            return data.groupby(sector_col)[factor_col].transform(safe_zscore)

    def calculate_multifactor_score(self, data, price_df=None):
        """
        멀티팩터 종합 점수 계산

        Args:
            data: 재무 데이터프레임
            price_df: 가격 데이터프레임

        Returns:
            data: 멀티팩터 점수가 추가된 데이터프레임
        """
        # 1. 성장성 팩터 계산
        data = self.calculate_growth_factors(data)

        # 2. 퀄리티 팩터 계산
        data = self.calculate_quality_factors(data)

        # 3. 모멘텀 팩터 계산
        if price_df is not None:
            data = self.calculate_momentum(data, price_df)

        # 4. 각 팩터별 Z-Score 계산
        growth_factors = []
        quality_factors = []
        momentum_factors = []

        # 성장성 팩터 (높을수록 좋음)
        if '매출성장률' in data.columns:
            data['매출성장률_z'] = self.calculate_zscore_by_sector(data, '매출성장률')
            growth_factors.append('매출성장률_z')

        if '순이익성장률' in data.columns:
            data['순이익성장률_z'] = self.calculate_zscore_by_sector(data, '순이익성장률')
            growth_factors.append('순이익성장률_z')

        if '영업이익성장률' in data.columns:
            data['영업이익성장률_z'] = self.calculate_zscore_by_sector(data, '영업이익성장률')
            growth_factors.append('영업이익성장률_z')

        # 퀄리티 팩터
        if 'ROE' in data.columns:
            data['ROE_z'] = self.calculate_zscore_by_sector(data, 'ROE')
            quality_factors.append('ROE_z')

        if '부채비율' in data.columns:
            # 부채비율은 낮을수록 좋음 (음수로 변환)
            data['부채비율_z'] = -self.calculate_zscore_by_sector(data, '부채비율')
            quality_factors.append('부채비율_z')

        if '영업이익률' in data.columns:
            data['영업이익률_z'] = self.calculate_zscore_by_sector(data, '영업이익률')
            quality_factors.append('영업이익률_z')

        # 모멘텀 팩터 (높을수록 좋음)
        if '모멘텀_3M' in data.columns:
            data['모멘텀_3M_z'] = self.calculate_zscore_by_sector(data, '모멘텀_3M')
            momentum_factors.append('모멘텀_3M_z')

        if '모멘텀_6M' in data.columns:
            data['모멘텀_6M_z'] = self.calculate_zscore_by_sector(data, '모멘텀_6M')
            momentum_factors.append('모멘텀_6M_z')

        # 5. 카테고리별 점수 계산
        data['성장성_점수'] = data[growth_factors].mean(axis=1) if growth_factors else 0
        data['퀄리티_점수'] = data[quality_factors].mean(axis=1) if quality_factors else 0
        data['모멘텀_점수'] = data[momentum_factors].mean(axis=1) if momentum_factors else 0

        # 6. 최종 점수 (가중 평균)
        data['코스닥성장_점수'] = (
            data['성장성_점수'] * self.growth_weight +
            data['퀄리티_점수'] * self.quality_weight +
            data['모멘텀_점수'] * self.momentum_weight
        )

        # 순위 계산 (높을수록 좋음)
        data['코스닥성장_순위'] = data['코스닥성장_점수'].rank(ascending=False, na_option='bottom')

        return data

    def select_top_stocks(self, data, n_stocks=30):
        """
        상위 종목 선정

        Args:
            data: 멀티팩터 점수가 계산된 데이터프레임
            n_stocks: 선정할 종목 수

        Returns:
            selected: 선정된 종목 데이터프레임
        """
        # 결측치 제거
        data_clean = data.dropna(subset=['코스닥성장_순위'])

        # 점수 기준 정렬 (높은 점수가 좋음)
        data_sorted = data_clean.sort_values('코스닥성장_점수', ascending=False)

        # 상위 n개 선정
        selected = data_sorted.head(n_stocks)

        return selected

    def run(self, financial_data, price_df=None, n_stocks=30):
        """
        코스닥 성장주 전략 실행

        Args:
            financial_data: 재무 데이터프레임
            price_df: 가격 데이터프레임
            n_stocks: 선정할 종목 수

        Returns:
            selected_stocks: 선정된 종목 리스트
            full_data: 전체 종목 데이터 (점수 포함)
        """
        # 멀티팩터 점수 계산
        scored_data = self.calculate_multifactor_score(
            financial_data.copy(),
            price_df=price_df
        )

        # 상위 종목 선정
        selected_stocks = self.select_top_stocks(scored_data, n_stocks)

        return selected_stocks, scored_data


if __name__ == '__main__':
    # 테스트
    print("코스닥 성장주 전략 테스트")

    # 임시 테스트 데이터
    test_data = pd.DataFrame({
        '종목코드': ['035420', '035720', '068270', '095660', '086520'],
        '종목명': ['NAVER', '카카오', '셀트리온', '네오위즈', '에코프로'],
        '시가총액': [40_000_000, 25_000_000, 35_000_000, 2_000_000, 15_000_000],
        '매출액': [8_000_000, 6_000_000, 2_500_000, 800_000, 3_000_000],
        '매출액_1y': [7_000_000, 5_500_000, 2_000_000, 700_000, 1_500_000],
        '당기순이익': [1_500_000, 500_000, 800_000, 100_000, 600_000],
        '당기순이익_1y': [1_200_000, 400_000, 600_000, 80_000, 200_000],
        '영업이익': [2_000_000, 800_000, 1_000_000, 150_000, 800_000],
        '영업이익_1y': [1_800_000, 700_000, 800_000, 120_000, 300_000],
        'EBIT': [2_100_000, 850_000, 1_050_000, 160_000, 850_000],
        '자본': [15_000_000, 8_000_000, 10_000_000, 500_000, 5_000_000],
        '총부채': [8_000_000, 5_000_000, 6_000_000, 400_000, 3_000_000],
        '자산': [23_000_000, 12_000_000, 16_000_000, 900_000, 8_000_000],
        '섹터': ['IT', 'IT', '바이오', 'IT', '2차전지'],
    })

    # 전략 실행
    strategy = KosdaqGrowthStrategy()
    selected, full_data = strategy.run(test_data, price_df=None, n_stocks=3)

    print("\n선정된 종목:")
    print(selected[['종목코드', '종목명', '코스닥성장_점수', '성장성_점수', '퀄리티_점수', '모멘텀_점수']])

    print("\n전체 종목 점수:")
    cols = ['종목코드', '종목명', '코스닥성장_점수', '코스닥성장_순위',
            '매출성장률', '순이익성장률', 'ROE', '부채비율']
    print(full_data[cols].sort_values('코스닥성장_점수', ascending=False))
