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

        pykrx 실시간 데이터(PER_live, PBR_live, DIV_live)가 있으면 우선 사용,
        없으면 FnGuide 캐시에서 계산 (fallback).

        Args:
            data: 재무 데이터프레임

        Returns:
            data: 밸류 팩터가 추가된 데이터프레임
        """
        # PER (Price to Earnings Ratio) — pykrx 실시간 우선
        if 'PER_live' in data.columns:
            data['PER'] = data['PER_live']
            # pykrx PER이 0이거나 음수인 경우 캐시 fallback
            mask = (data['PER'] <= 0) | data['PER'].isna()
            if mask.any() and '당기순이익' in data.columns:
                data.loc[mask, 'PER'] = data.loc[mask, '시가총액'] / data.loc[mask, '당기순이익']
        elif '당기순이익' in data.columns:
            data['PER'] = data['시가총액'] / data['당기순이익']
        elif 'EPS' in data.columns and '주가' in data.columns:
            data['PER'] = data['주가'] / data['EPS']

        # PBR (Price to Book Ratio) — pykrx 실시간 우선
        if 'PBR_live' in data.columns:
            data['PBR'] = data['PBR_live']
            mask = (data['PBR'] <= 0) | data['PBR'].isna()
            if mask.any() and '자본' in data.columns:
                data.loc[mask, 'PBR'] = data.loc[mask, '시가총액'] / data.loc[mask, '자본']
        elif '자본' in data.columns:
            data['PBR'] = data['시가총액'] / data['자본']
        elif 'BPS' in data.columns and '주가' in data.columns:
            data['PBR'] = data['주가'] / data['BPS']

        # PCR (Price to Cashflow Ratio) — 캐시 유지 (pykrx 미제공)
        if '영업현금흐름' in data.columns:
            data['PCR'] = data['시가총액'] / data['영업현금흐름']

        # PSR (Price to Sales Ratio) — 캐시 유지 (pykrx 미제공)
        if '매출액' in data.columns:
            data['PSR'] = data['시가총액'] / data['매출액']

        # 배당수익률 — pykrx 실시간 우선
        if 'DIV_live' in data.columns:
            data['배당수익률'] = data['DIV_live']
            mask = data['배당수익률'].isna()
            if mask.any() and '배당금' in data.columns:
                data.loc[mask, '배당수익률'] = data.loc[mask, '배당금'] / data.loc[mask, '시가총액'] * 100
        elif '배당금' in data.columns:
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
        - EPS개선도 (Trailing PER vs Forward PER): 높을수록 좋음

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

        # EPS개선도 (Forward PER vs Trailing PER)
        # Trailing PER > Forward PER = 실적 개선 중 (양수)
        # Trailing PER < Forward PER = 실적 악화 중 (음수)
        if 'forward_per' in data.columns and 'PER' in data.columns:
            mask = (data['forward_per'] > 0) & (data['PER'] > 0)
            data['EPS개선도'] = np.nan
            data.loc[mask, 'EPS개선도'] = (
                (data.loc[mask, 'PER'] - data.loc[mask, 'forward_per'])
                / data.loc[mask, 'PER'] * 100
            )
            eps_count = data['EPS개선도'].notna().sum()
            fill_count = data['EPS개선도'].isna().sum()
            # FWD PER 없는 종목 = NaN 유지 → rank percentile에서 bottom 처리
            # 매출성장률도 없으면 G=0.3 페널티 (calculate_multifactor_score에서)
            print(f"EPS개선도 계산: {eps_count}/{len(data)}개 종목 (Forward PER 기반, {fill_count}개 미커버)")

        return data

    def calculate_momentum(self, data, price_df):
        """
        모멘텀 팩터 계산 — 리스크 조정 6M 모멘텀

        Score = 6M수익률 / 6M변동성(연환산)
        - 6개월 중기 추세 포착 (정책/회복 국면에 최적)
        - 변동성 하한선 15% (저변동 종목 점수 폭발 방지)
        """
        LOOKBACK_6M = 6 * 21    # 126 거래일
        VOL_FLOOR = 15.0

        if price_df is None or price_df.empty:
            print(f"경고: 가격 데이터가 없습니다.")
            data['모멘텀'] = np.nan
            return data

        min_required = LOOKBACK_6M + 1

        if len(price_df) < min_required:
            print(f"경고: 가격 데이터가 부족합니다. (현재: {len(price_df)}일, 필요: {min_required}일)")
            data['모멘텀'] = np.nan
            return data

        momentum_dict = {}
        matched_count = 0

        for ticker in data['종목코드']:
            if ticker in price_df.columns:
                prices = price_df[ticker].dropna()

                if len(prices) < min_required:
                    continue

                try:
                    price_current = prices.iloc[-1]
                    price_6m_ago = prices.iloc[-(LOOKBACK_6M + 1)]

                    if price_6m_ago <= 0:
                        continue

                    ret_6m = (price_current / price_6m_ago - 1) * 100

                    # 6M 변동성 (연환산)
                    daily_returns = prices.iloc[-(LOOKBACK_6M + 1):].pct_change().dropna()
                    annual_vol = daily_returns.std() * np.sqrt(252) * 100
                    annual_vol = max(annual_vol, VOL_FLOOR)

                    momentum = ret_6m / annual_vol
                    momentum_dict[ticker] = momentum
                    matched_count += 1
                except (IndexError, KeyError):
                    continue

        data['모멘텀'] = data['종목코드'].map(momentum_dict)
        print(f"모멘텀 계산 완료: {matched_count}/{len(data)}개 매칭")
        print(f"  공식: 6M수익률 / 변동성(연환산, floor={VOL_FLOOR}%)")

        return data

    def _winsorize(self, series, lower=0.01, upper=0.99):
        """상하위 극단값 클리핑 (윈저라이징)"""
        q_low = series.quantile(lower)
        q_high = series.quantile(upper)
        return series.clip(q_low, q_high)

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
            mean = data[factor_col].mean()
            std = data[factor_col].std()
            if std == 0 or pd.isna(std):
                return pd.Series(0.0, index=data.index)
            return (data[factor_col] - mean) / std
        else:
            def safe_zscore(x):
                std = x.std()
                if std == 0 or pd.isna(std):
                    return pd.Series(0.0, index=x.index)
                return (x - x.mean()) / std
            return data.groupby(sector_col)[factor_col].transform(safe_zscore)

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

        # 3.5. 이상치 전처리 — PER/PBR 0 이하 → NaN
        for col in ['PER', 'PBR']:
            if col in data.columns:
                data.loc[data[col] <= 0, col] = np.nan

        # 4. Winsorized z-score + 카테고리 재표준화 (v51)
        #    크기 정보 보존 + 이상치 억제 + 카테고리 간 분산 통일
        def winsorized_zscore(series, invert=False, lower=0.025, upper=0.975):
            valid = series.dropna()
            if len(valid) < 5:
                return pd.Series(np.nan, index=series.index)
            q_lo, q_hi = valid.quantile(lower), valid.quantile(upper)
            clipped = series.clip(q_lo, q_hi)
            mean_val, std_val = clipped.mean(), clipped.std()
            if std_val == 0 or pd.isna(std_val):
                return pd.Series(0.0, index=series.index)
            z = (clipped - mean_val) / std_val
            if invert:
                z = -z
            return z

        # 서브팩터별 Winsorized z-score
        value_zs = []
        for col in ['PER', 'PBR']:
            if col in data.columns:
                data[f'{col}_z'] = winsorized_zscore(data[col], invert=True)
                value_zs.append(f'{col}_z')

        quality_zs = []
        for col in ['ROE', 'GPA', 'CFO']:
            if col in data.columns:
                data[f'{col}_z'] = winsorized_zscore(data[col])
                quality_zs.append(f'{col}_z')

        growth_zs = []
        for col in ['EPS개선도', '매출성장률']:
            if col in data.columns and data[col].notna().sum() > 0:
                data[f'{col}_z'] = winsorized_zscore(data[col])
                growth_zs.append(f'{col}_z')

        momentum_zs = []
        if '모멘텀' in data.columns:
            data['모멘텀_z'] = winsorized_zscore(data['모멘텀'])
            momentum_zs.append('모멘텀_z')

        print(f"Winsorized z-score: V{len(value_zs)} Q{len(quality_zs)} G{len(growth_zs)} M{len(momentum_zs)}")

        # 5. 카테고리 평균
        data['밸류_raw'] = data[value_zs].mean(axis=1) if value_zs else 0
        data['퀄리티_raw'] = data[quality_zs].mean(axis=1) if quality_zs else 0

        # Growth: NaN은 keep → 부분 결측은 있는 것만, 둘 다 없으면 페널티
        if growth_zs:
            data['성장_raw'] = data[growth_zs].mean(axis=1)
            growth_missing = data['성장_raw'].isna().sum()
            if growth_missing > 0:
                data['성장_raw'] = data['성장_raw'].fillna(-0.5)
                print(f"Growth 둘 다 없는 종목: {growth_missing}개 → G=-0.5σ 페널티")
        else:
            data['성장_raw'] = 0

        data['모멘텀_raw'] = data[momentum_zs].mean(axis=1) if momentum_zs else 0

        # 6. 카테고리별 재표준화 (std=1) — 서브팩터 수 차이로 인한 분산 불균형 해소
        for raw_col, score_col in [('밸류_raw', '밸류_점수'), ('퀄리티_raw', '퀄리티_점수'),
                                    ('성장_raw', '성장_점수'), ('모멘텀_raw', '모멘텀_점수')]:
            cat_mean = data[raw_col].mean()
            cat_std = data[raw_col].std()
            if cat_std > 0:
                data[score_col] = (data[raw_col] - cat_mean) / cat_std
            else:
                data[score_col] = 0.0

        # 7. 과락 필터: 4개 카테고리 중 2개 이상 -0.5σ 미만 → 제외
        FAIL_THRESHOLD = -0.5
        FAIL_COUNT = 2
        cat_cols = ['밸류_점수', '퀄리티_점수', '성장_점수', '모멘텀_점수']
        fail_mask = (data[cat_cols] < FAIL_THRESHOLD).sum(axis=1) >= FAIL_COUNT
        fail_count = fail_mask.sum()
        if fail_count > 0:
            failed_names = data.loc[fail_mask, '종목명'].tolist() if '종목명' in data.columns else []
            data = data[~fail_mask].copy()
            print(f"과락 필터: {fail_count}개 제외 (2개 이상 <-0.5σ) {failed_names[:5]}")

        # 8. 최종 가중합 (V25 + Q25 + G30 + M20)
        if momentum_zs:
            before_count = len(data)
            data = data[data['모멘텀_점수'].notna()].copy()
            excluded = before_count - len(data)
            if excluded > 0:
                print(f"모멘텀 데이터 없는 종목 제외: {excluded}개 → {len(data)}개 남음")

            data['멀티팩터_점수'] = (data['밸류_점수'] * 0.25 +
                                    data['퀄리티_점수'] * 0.25 +
                                    data['성장_점수'] * 0.30 +
                                    data['모멘텀_점수'] * 0.20)
            print("멀티팩터 가중치: V25 + Q25 + G30 + M20 (WZ+Renorm)")
        else:
            data['멀티팩터_점수'] = (data['밸류_점수'] * 0.5 +
                                    data['퀄리티_점수'] * 0.5)
            print("멀티팩터 가중치: Value 50% + Quality 50% (모멘텀 없음)")

        # 순위 계산 (높을수록 좋음)
        data['멀티팩터_순위'] = data['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')

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
