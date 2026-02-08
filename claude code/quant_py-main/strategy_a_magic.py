"""
전략 A: 마법공식 (Magic Formula)
조엘 그린블라트의 마법공식 구현
"""

import pandas as pd
import numpy as np


class MagicFormulaStrategy:
    """마법공식 전략"""

    def __init__(self):
        self.name = "Magic Formula"

    def calculate_earnings_yield(self, data):
        """
        이익수익률 계산 = EBIT / EV

        EBIT = 영업이익 (이자비용/법인세 차감 전)
        EV = 시가총액 + 총부채 - 여유자금
        여유자금 = 현금 - max(0, 유동부채 - 유동자산 + 현금)

        Args:
            data: 재무 데이터프레임 (종목코드, 시가총액, 재무제표 항목 포함)

        Returns:
            earnings_yield: 이익수익률 시리즈
        """
        # EBIT = 영업이익 (이자비용·법인세 차감 전 이익)
        if '영업이익' in data.columns:
            ebit = data['영업이익']
        elif '세전계속사업이익' in data.columns:
            ebit = data['세전계속사업이익']
        else:
            ebit = data['당기순이익'] + data['법인세비용']

        # 여유자금 계산
        excess_cash = (data['현금'] -
                      np.maximum(0, data['유동부채'] - data['유동자산'] + data['현금']))

        # EV (기업가치) 계산
        ev = data['시가총액'] + data['총부채'] - excess_cash

        # 이익수익률
        earnings_yield = ebit / ev

        return earnings_yield

    def calculate_roc(self, data):
        """
        투하자본수익률 계산 = EBIT / IC

        IC (투하자본) = (유동자산 - 유동부채) + 비유동자산
        ※ 비유동자산은 재무상태표 기준 순장부가 (감가상각누계액 차감 후)

        Args:
            data: 재무 데이터프레임

        Returns:
            roc: 투하자본수익률 시리즈
        """
        # EBIT = 영업이익 (이자비용·법인세 차감 전 이익)
        if '영업이익' in data.columns:
            ebit = data['영업이익']
        elif '세전계속사업이익' in data.columns:
            ebit = data['세전계속사업이익']
        else:
            ebit = data['당기순이익'] + data['법인세비용']

        # 투하자본 계산 (비유동자산은 BS상 순장부가이므로 감가상각비 별도 차감 불필요)
        ic = (data['유동자산'] - data['유동부채']) + data['비유동자산']

        # 투하자본수익률
        roc = ebit / ic

        return roc

    def calculate_magic_formula_score(self, data):
        """
        마법공식 점수 계산

        1. 이익수익률 순위 계산 (높을수록 좋음)
        2. 투하자본수익률 순위 계산 (높을수록 좋음)
        3. 두 순위의 합 계산
        4. 합계 기준 순위 재계산

        Args:
            data: 재무 데이터프레임

        Returns:
            data: 마법공식 점수가 추가된 데이터프레임
        """
        # 이익수익률 계산
        data['이익수익률'] = self.calculate_earnings_yield(data)

        # 투하자본수익률 계산
        data['투하자본수익률'] = self.calculate_roc(data)

        # 이상치 제거 (inf, -inf, nan)
        data['이익수익률'] = data['이익수익률'].replace([np.inf, -np.inf], np.nan)
        data['투하자본수익률'] = data['투하자본수익률'].replace([np.inf, -np.inf], np.nan)

        # 순위 계산 (높을수록 좋으므로 ascending=False)
        ey_rank = data['이익수익률'].rank(ascending=False, method='first', na_option='bottom')
        roc_rank = data['투하자본수익률'].rank(ascending=False, method='first', na_option='bottom')

        # 순위 합산
        combined_rank = ey_rank + roc_rank

        # 최종 순위 (낮을수록 좋음)
        data['마법공식_순위'] = combined_rank.rank(ascending=True, method='first', na_option='bottom')

        return data

    def select_top_stocks(self, data, n_stocks=20):
        """
        상위 종목 선정

        Args:
            data: 마법공식 점수가 계산된 데이터프레임
            n_stocks: 선정할 종목 수

        Returns:
            selected: 선정된 종목 데이터프레임
        """
        # 결측치 제거
        data_clean = data.dropna(subset=['마법공식_순위'])

        # 순위 기준 정렬
        data_sorted = data_clean.sort_values('마법공식_순위')

        # 상위 n개 선정
        selected = data_sorted.head(n_stocks)

        return selected

    def run(self, financial_data, n_stocks=20):
        """
        마법공식 전략 실행

        Args:
            financial_data: 재무 데이터프레임
            n_stocks: 선정할 종목 수

        Returns:
            selected_stocks: 선정된 종목 리스트
            full_data: 전체 종목 데이터 (점수 포함)
        """
        # 마법공식 점수 계산
        scored_data = self.calculate_magic_formula_score(financial_data.copy())

        # 상위 종목 선정
        selected_stocks = self.select_top_stocks(scored_data, n_stocks)

        return selected_stocks, scored_data


if __name__ == '__main__':
    # 테스트 데이터 생성
    print("마법공식 전략 테스트")

    # 임시 테스트 데이터
    test_data = pd.DataFrame({
        '종목코드': ['005930', '000660', '035420', '051910', '035720'],
        '종목명': ['삼성전자', 'SK하이닉스', 'NAVER', 'LG화학', '카카오'],
        '시가총액': [400_000_000_000_000, 80_000_000_000_000, 40_000_000_000_000,
                   30_000_000_000_000, 25_000_000_000_000],
        '당기순이익': [30_000_000, 8_000_000, 1_500_000, 3_000_000, 500_000],
        '법인세비용': [5_000_000, 1_500_000, 300_000, 600_000, 100_000],
        '이자비용': [1_000_000, 200_000, 50_000, 100_000, 20_000],
        '총부채': [100_000_000, 30_000_000, 5_000_000, 15_000_000, 3_000_000],
        '유동부채': [50_000_000, 15_000_000, 2_500_000, 7_000_000, 1_500_000],
        '유동자산': [150_000_000, 40_000_000, 8_000_000, 20_000_000, 4_000_000],
        '현금': [80_000_000, 20_000_000, 4_000_000, 10_000_000, 2_000_000],
        '비유동자산': [200_000_000, 50_000_000, 10_000_000, 30_000_000, 6_000_000],
        '감가상각비': [20_000_000, 8_000_000, 1_000_000, 4_000_000, 500_000],
    })

    # 전략 실행
    strategy = MagicFormulaStrategy()
    selected, full_data = strategy.run(test_data, n_stocks=3)

    print("\n선정된 종목:")
    print(selected[['종목코드', '종목명', '이익수익률', '투하자본수익률', '마법공식_순위']])

    print("\n전체 종목 점수:")
    print(full_data[['종목코드', '종목명', '이익수익률', '투하자본수익률', '마법공식_순위']].sort_values('마법공식_순위'))
