"""
전략 B: 멀티팩터 전략
밸류 + 퀄리티 + 모멘텀 결합
"""

import pandas as pd
import numpy as np
from scipy import stats


class MultiFactorStrategy:
    """멀티팩터 전략"""

    def __init__(self):
        self.name = "Multi-Factor (Value + Quality + Momentum)"

    def calculate_value_factors(self, data):
        """
        밸류 팩터 계산

        - PER, PBR, PCR, PSR: 낮을수록 좋음
        - 배당수익률: 높을수록 좋음

        Args:
            data: 재무 데이터프레임

        Returns:
            data: 밸류 팩터가 추가된 데이터프레임
        """
        # PER (Price to Earnings Ratio)
        # 시가총액 / 당기순이익
        if '당기순이익' in data.columns:
            data['PER'] = data['시가총액'] / data['당기순이익']
        elif 'EPS' in data.columns and '주가' in data.columns:
            data['PER'] = data['주가'] / data['EPS']

        # PBR (Price to Book Ratio)
        # 시가총액 / 순자산 (자본)
        if '자본' in data.columns:
            data['PBR'] = data['시가총액'] / data['자본']
        elif 'BPS' in data.columns and '주가' in data.columns:
            data['PBR'] = data['주가'] / data['BPS']

        # PCR (Price to Cashflow Ratio)
        # 시가총액 / 영업현금흐름
        if '영업현금흐름' in data.columns:
            data['PCR'] = data['시가총액'] / data['영업현금흐름']

        # PSR (Price to Sales Ratio)
        # 시가총액 / 매출액
        if '매출액' in data.columns:
            data['PSR'] = data['시가총액'] / data['매출액']

        # 배당수익률
        if '배당금' in data.columns:
            data['배당수익률'] = data['배당금'] / data['시가총액'] * 100
        elif 'DPS' in data.columns and '주가' in data.columns:
            data['배당수익률'] = data['DPS'] / data['주가'] * 100

        return data

    def calculate_quality_factors(self, data):
        """
        퀄리티 팩터 계산

        - ROE (Return on Equity): 높을수록 좋음
        - GPA (Gross Profit to Asset): 높을수록 좋음
        - CFO (Cash Flow to Asset): 높을수록 좋음

        Args:
            data: 재무 데이터프레임

        Returns:
            data: 퀄리티 팩터가 추가된 데이터프레임
        """
        # ROE (Return on Equity)
        # 당기순이익 / 자본
        if '당기순이익' in data.columns and '자본' in data.columns:
            data['ROE'] = data['당기순이익'] / data['자본'] * 100

        # GPA (Gross Profitability to Asset)
        # 매출총이익 / 자산
        if '매출총이익' in data.columns and '자산' in data.columns:
            data['GPA'] = data['매출총이익'] / data['자산'] * 100

        # CFO (Cash Flow to Asset)
        # 영업현금흐름 / 자산
        if '영업현금흐름' in data.columns and '자산' in data.columns:
            data['CFO'] = data['영업현금흐름'] / data['자산'] * 100

        return data

    def calculate_momentum(self, data, price_df):
        """
        모멘텀 팩터 계산

        12개월 수익률 (최근 1개월 제외)

        Args:
            data: 재무 데이터프레임
            price_df: 가격 데이터프레임 (날짜 인덱스, 종목코드 컬럼)

        Returns:
            data: 모멘텀 팩터가 추가된 데이터프레임
        """
        lookback_days = 12 * 21  # 12개월
        skip_days = 1 * 21  # 1개월

        if len(price_df) < lookback_days + skip_days:
            print(f"경고: 가격 데이터가 부족합니다.")
            data['모멘텀'] = np.nan
            return data

        # 모멘텀 계산
        momentum_dict = {}
        for ticker in data['종목코드']:
            if ticker in price_df.columns:
                prices = price_df[ticker].dropna()

                if len(prices) < lookback_days + skip_days:
                    continue

                # 최근 1개월을 제외한 12개월 수익률
                end_price = prices.iloc[-(skip_days + 1)]
                start_price = prices.iloc[-(lookback_days + skip_days + 1)]

                momentum = (end_price / start_price - 1) * 100
                momentum_dict[ticker] = momentum

        data['모멘텀'] = data['종목코드'].map(momentum_dict)

        return data

    def calculate_zscore_by_sector(self, data, factor_col, sector_col='섹터'):
        """
        섹터별 Z-Score 계산

        Args:
            data: 데이터프레임
            factor_col: 팩터 컬럼명
            sector_col: 섹터 컬럼명

        Returns:
            zscore_series: Z-Score 시리즈
        """
        if sector_col not in data.columns:
            # 섹터 정보가 없으면 전체 평균으로 계산
            mean = data[factor_col].mean()
            std = data[factor_col].std()
            return (data[factor_col] - mean) / std
        else:
            # 섹터별 Z-Score
            return data.groupby(sector_col)[factor_col].transform(
                lambda x: (x - x.mean()) / x.std()
            )

    def calculate_multifactor_score(self, data, price_df=None, has_sector=False):
        """
        멀티팩터 종합 점수 계산

        Args:
            data: 재무 데이터프레임
            price_df: 가격 데이터프레임 (모멘텀 계산용)
            has_sector: 섹터 정보 유무

        Returns:
            data: 멀티팩터 점수가 추가된 데이터프레임
        """
        # 1. 밸류 팩터 계산
        data = self.calculate_value_factors(data)

        # 2. 퀄리티 팩터 계산
        data = self.calculate_quality_factors(data)

        # 3. 모멘텀 팩터 계산
        if price_df is not None:
            data = self.calculate_momentum(data, price_df)

        # 4. 각 팩터별 Z-Score 계산
        value_factors = []
        quality_factors = []

        # 밸류 팩터 (낮을수록 좋음 → 음수로 변환)
        if 'PER' in data.columns:
            data['PER_z'] = -self.calculate_zscore_by_sector(data, 'PER')
            value_factors.append('PER_z')

        if 'PBR' in data.columns:
            data['PBR_z'] = -self.calculate_zscore_by_sector(data, 'PBR')
            value_factors.append('PBR_z')

        if 'PCR' in data.columns:
            data['PCR_z'] = -self.calculate_zscore_by_sector(data, 'PCR')
            value_factors.append('PCR_z')

        if 'PSR' in data.columns:
            data['PSR_z'] = -self.calculate_zscore_by_sector(data, 'PSR')
            value_factors.append('PSR_z')

        if '배당수익률' in data.columns:
            data['배당_z'] = self.calculate_zscore_by_sector(data, '배당수익률')
            value_factors.append('배당_z')

        # 퀄리티 팩터 (높을수록 좋음)
        if 'ROE' in data.columns:
            data['ROE_z'] = self.calculate_zscore_by_sector(data, 'ROE')
            quality_factors.append('ROE_z')

        if 'GPA' in data.columns:
            data['GPA_z'] = self.calculate_zscore_by_sector(data, 'GPA')
            quality_factors.append('GPA_z')

        if 'CFO' in data.columns:
            data['CFO_z'] = self.calculate_zscore_by_sector(data, 'CFO')
            quality_factors.append('CFO_z')

        # 모멘텀 팩터 (높을수록 좋음)
        if '모멘텀' in data.columns:
            data['모멘텀_z'] = self.calculate_zscore_by_sector(data, '모멘텀')
            momentum_factors = ['모멘텀_z']
        else:
            momentum_factors = []

        # 5. 종합 점수 계산 (각 팩터 카테고리의 평균)
        data['밸류_점수'] = data[value_factors].mean(axis=1) if value_factors else 0
        data['퀄리티_점수'] = data[quality_factors].mean(axis=1) if quality_factors else 0
        data['모멘텀_점수'] = data[momentum_factors].mean(axis=1) if momentum_factors else 0

        # 최종 점수 (가중 평균 또는 단순 평균)
        # 여기서는 단순 평균 사용
        data['멀티팩터_점수'] = (data['밸류_점수'] +
                                data['퀄리티_점수'] +
                                data['모멘텀_점수']) / 3

        # 순위 계산 (높을수록 좋음)
        data['멀티팩터_순위'] = data['멀티팩터_점수'].rank(ascending=False, na_option='bottom')

        return data

    def select_top_stocks(self, data, n_stocks=20):
        """
        상위 종목 선정

        Args:
            data: 멀티팩터 점수가 계산된 데이터프레임
            n_stocks: 선정할 종목 수

        Returns:
            selected: 선정된 종목 데이터프레임
        """
        # 결측치 제거
        data_clean = data.dropna(subset=['멀티팩터_순위'])

        # 점수 기준 정렬 (높은 점수가 좋음)
        data_sorted = data_clean.sort_values('멀티팩터_점수', ascending=False)

        # 상위 n개 선정
        selected = data_sorted.head(n_stocks)

        return selected

    def run(self, financial_data, price_df=None, n_stocks=20):
        """
        멀티팩터 전략 실행

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
    print("멀티팩터 전략 테스트")

    # 임시 테스트 데이터
    test_data = pd.DataFrame({
        '종목코드': ['005930', '000660', '035420', '051910', '035720'],
        '종목명': ['삼성전자', 'SK하이닉스', 'NAVER', 'LG화학', '카카오'],
        '시가총액': [400_000_000_000_000, 80_000_000_000_000, 40_000_000_000_000,
                   30_000_000_000_000, 25_000_000_000_000],
        '당기순이익': [30_000_000, 8_000_000, 1_500_000, 3_000_000, 500_000],
        '자본': [200_000_000, 50_000_000, 15_000_000, 20_000_000, 8_000_000],
        '자산': [350_000_000, 80_000_000, 23_000_000, 50_000_000, 12_000_000],
        '매출액': [250_000_000, 40_000_000, 8_000_000, 40_000_000, 6_000_000],
        '매출총이익': [100_000_000, 18_000_000, 5_000_000, 15_000_000, 3_000_000],
        '영업현금흐름': [40_000_000, 12_000_000, 2_000_000, 5_000_000, 1_000_000],
    })

    # 전략 실행
    strategy = MultiFactorStrategy()
    selected, full_data = strategy.run(test_data, price_df=None, n_stocks=3)

    print("\n선정된 종목:")
    print(selected[['종목코드', '종목명', '멀티팩터_점수', '밸류_점수', '퀄리티_점수']])

    print("\n전체 종목 점수:")
    print(full_data[['종목코드', '종목명', '멀티팩터_점수', '멀티팩터_순위']].sort_values('멀티팩터_점수', ascending=False))
