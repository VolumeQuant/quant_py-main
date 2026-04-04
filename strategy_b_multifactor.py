"""
전략 B: 멀티팩터 전략 v71 — 4팩터 동일가중 (V+Q+G+M = 25% each)

헨리(이현열) 원본 rank z-score 기반 + 실시간/전방성 강화
V25(PER+PBR+PCR+PSR) + Q25(ROE+GPA+CFO) + G25(TTM매출YoY+op_change_asset) + M25(6M/Vol+K_ratio)
V/Q: 전체 유니버스 rank z-score (절대 비교)
M: 섹터 내 rank z-score (섹터 추세 제거)
G: 전체 유니버스 rank z-score (매출TTM 50% + op_change_asset 50%, 연간 폴백)
+ FWD_PER 보너스 (커버 종목 가산)
"""

import os
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

        - PER = pykrx fundamental (KRX 공식, 지배주주 기준)
        - PBR = pykrx fundamental (KRX 공식, 지배주주 기준)
        - PCR = 시가총액 / 영업현금흐름 (DART)
        - PSR = 시가총액 / 매출액 (DART)
        낮을수록 좋음. 분모 ≤ 0이면 NaN.
        """
        import numpy as np

        # PER — pykrx fundamental (KRX 공식, 지배주주 기준). 없으면 NaN.
        if 'pykrx_PER' in data.columns:
            data['PER'] = data['pykrx_PER'].where(data['pykrx_PER'] > 0, np.nan)
        else:
            data['PER'] = np.nan

        # PBR — pykrx fundamental. 없으면 NaN.
        if 'pykrx_PBR' in data.columns:
            data['PBR'] = data['pykrx_PBR'].where(data['pykrx_PBR'] > 0, np.nan)
        else:
            data['PBR'] = np.nan

        # PCR (Price to Cashflow Ratio)
        if '영업현금흐름' in data.columns and '시가총액' in data.columns:
            data['PCR'] = np.where(
                data['영업현금흐름'] > 0,
                data['시가총액'] / data['영업현금흐름'],
                np.nan
            )

        # PSR (Price to Sales Ratio)
        if '매출액' in data.columns and '시가총액' in data.columns:
            data['PSR'] = np.where(
                data['매출액'] > 0,
                data['시가총액'] / data['매출액'],
                np.nan
            )

        return data

    def calculate_quality_factors(self, data):
        """
        퀄리티 팩터 계산 — v69: 순수 실적 품질 3팩터

        - ROE (Return on Equity): 높을수록 좋음
        - GPA (Gross Profit to Asset): 높을수록 좋음
        - CFO (Cash Flow to Asset): 높을수록 좋음
        """
        # ROE — pykrx EPS/BPS (지배주주 기준). 없으면 NaN.
        if 'pykrx_EPS' in data.columns and 'pykrx_BPS' in data.columns:
            data['ROE'] = np.where(
                data['pykrx_BPS'] > 0,
                data['pykrx_EPS'] / data['pykrx_BPS'] * 100,
                np.nan
            )
        else:
            data['ROE'] = np.nan

        if '매출총이익' in data.columns and '자산' in data.columns:
            data['GPA'] = data['매출총이익'] / data['자산'] * 100

        if '영업현금흐름' in data.columns and '자산' in data.columns:
            data['CFO'] = data['영업현금흐름'] / data['자산'] * 100

        return data

    def _calc_ttm_yoy(self, fs, account, base_dt=None, cutoff_date=None):
        """단일 계정 TTM YoY 계산 (내부 헬퍼)"""
        q_data = fs[(fs['공시구분'] == 'q') & (fs['계정'] == account)].copy()
        if q_data.empty:
            return None

        # point-in-time 필터
        if base_dt and 'rcept_dt' in q_data.columns:
            has_rcept = q_data['rcept_dt'].notna()
            rcept_ok = q_data['rcept_dt'] <= base_dt
            cutoff_ok = q_data['기준일'] <= cutoff_date if cutoff_date else True
            q_data = q_data[(has_rcept & rcept_ok) | (~has_rcept & cutoff_ok)]
        elif cutoff_date is not None:
            q_data = q_data[q_data['기준일'] <= cutoff_date]

        q_data = q_data.sort_values('기준일')
        q_dates = sorted(q_data['기준일'].unique(), reverse=True)

        if len(q_dates) >= 8:
            recent_4 = q_dates[:4]
            prev_4 = q_dates[4:8]
            ttm_recent = q_data[q_data['기준일'].isin(recent_4)]['값'].sum()
            ttm_prev = q_data[q_data['기준일'].isin(prev_4)]['값'].sum()
            if ttm_prev > 0 and pd.notna(ttm_recent) and pd.notna(ttm_prev):
                return (ttm_recent / ttm_prev - 1) * 100
        return None

    def _calc_annual_yoy(self, fs, account, base_dt=None, cutoff_date=None):
        """단일 계정 연간 YoY 계산 (내부 헬퍼, TTM 폴백용)"""
        y_data = fs[(fs['공시구분'] == 'y') & (fs['계정'] == account)].copy()
        if y_data.empty:
            return None

        if base_dt and 'rcept_dt' in y_data.columns:
            has_rcept = y_data['rcept_dt'].notna()
            rcept_ok = y_data['rcept_dt'] <= base_dt
            cutoff_ok = y_data['기준일'] <= cutoff_date if cutoff_date else True
            y_data = y_data[(has_rcept & rcept_ok) | (~has_rcept & cutoff_ok)]
        elif cutoff_date is not None:
            y_data = y_data[y_data['기준일'] <= cutoff_date]

        y_data = y_data.sort_values('기준일')
        if len(y_data) >= 2:
            latest = y_data.iloc[-1]['값']
            prev = y_data.iloc[-2]['값']
            if prev > 0 and pd.notna(latest) and pd.notna(prev):
                return (latest / prev - 1) * 100
        return None

    def _calc_op_change_asset(self, fs, base_dt=None, cutoff_date=None):
        """op_change_asset = (영업이익TTM - 영업이익TTM_prev) / 총자산_prev

        SUE 유사 지표: 분모가 총자산이라 음수/극단값 문제 없음.
        """
        q_data = fs[fs['공시구분'] == 'q'].copy()
        if q_data.empty:
            return None

        # point-in-time 필터
        if base_dt and 'rcept_dt' in q_data.columns:
            has_rcept = q_data['rcept_dt'].notna()
            rcept_ok = q_data['rcept_dt'] <= base_dt
            cutoff_ok = q_data['기준일'] <= cutoff_date if cutoff_date else True
            q_data = q_data[(has_rcept & rcept_ok) | (~has_rcept & cutoff_ok)]
        elif cutoff_date is not None:
            q_data = q_data[q_data['기준일'] <= cutoff_date]

        op = q_data[q_data['계정'] == '영업이익'].sort_values('기준일')
        dates = sorted(op['기준일'].unique(), reverse=True)
        if len(dates) < 8:
            return None

        recent_4 = dates[:4]
        prev_4 = dates[4:8]
        op_recent = op[op['기준일'].isin(recent_4)]['값'].sum()
        op_prev = op[op['기준일'].isin(prev_4)]['값'].sum()

        # 전기 총자산 (직전 4분기 중 가장 최근)
        assets = q_data[q_data['계정'] == '자산'].sort_values('기준일')
        prev_assets = assets[assets['기준일'].isin(prev_4)]
        if prev_assets.empty:
            return None
        prev_asset = prev_assets.iloc[-1]['값']

        if prev_asset > 0 and pd.notna(op_recent) and pd.notna(op_prev):
            return (op_recent - op_prev) / prev_asset * 100
        return None

    def _calc_revenue_acceleration(self, fs, base_dt=None, cutoff_date=None):
        """Revenue Acceleration = 현재 TTM YoY - 직전 이벤트의 TTM YoY

        fast_generate_rankings_v2와 동일 로직:
        - 분기별 이벤트를 공시접수일(rcept_dt) 기반으로 정렬
        - 각 이벤트에서 TTM YoY 계산
        - 직전 이벤트의 TTM YoY와의 차이 = Revenue Acceleration
        """
        from datetime import timedelta

        q_data = fs[fs['공시구분'] == 'q'].copy()
        if q_data.empty:
            return None

        has_rcept = 'rcept_dt' in q_data.columns

        # point-in-time 필터
        if base_dt and has_rcept:
            rcept_ok = q_data['rcept_dt'].notna() & (q_data['rcept_dt'] <= base_dt)
            cutoff_ok = q_data['기준일'] <= cutoff_date if cutoff_date else True
            q_data = q_data[rcept_ok | (~q_data['rcept_dt'].notna() & cutoff_ok)]
        elif cutoff_date is not None:
            q_data = q_data[q_data['기준일'] <= cutoff_date]

        # 분기별 값 dict: {(기준일, 계정) → 값}
        q_vals = {}
        q_rcept_map = {}
        for _, row in q_data.iterrows():
            key = (row['기준일'], row['계정'])
            if key not in q_vals and pd.notna(row['값']):
                q_vals[key] = row['값']
            if has_rcept and row['기준일'] not in q_rcept_map and pd.notna(row.get('rcept_dt')):
                q_rcept_map[row['기준일']] = row['rcept_dt']

        q_dates_all = sorted(set(d for d, _ in q_vals.keys()))

        # 각 분기별 TTM YoY 이벤트 체인 구축
        prev_rev_yoy = None
        last_accel = None

        for qi, qd in enumerate(q_dates_all):
            # effective date (공시접수일 or 기준일+90일)
            if qd in q_rcept_map:
                eff_date = q_rcept_map[qd]
                if isinstance(eff_date, str):
                    eff_date = pd.Timestamp(eff_date)
            else:
                eff_date = qd + timedelta(days=90)

            # base_dt 이후 이벤트는 무시
            if base_dt and eff_date > base_dt:
                continue

            avail = sorted(q_dates_all[:qi+1], reverse=True)
            if len(avail) < 8:
                continue

            recent_4 = avail[:4]
            prev_4 = avail[4:8]
            r4 = sum(q_vals.get((d, '매출액'), 0) for d in recent_4)
            p4 = sum(q_vals.get((d, '매출액'), 0) for d in prev_4)

            if p4 <= 0:
                continue
            rev_yoy = (r4 / p4 - 1) * 100

            # Revenue Acceleration
            if prev_rev_yoy is not None:
                last_accel = rev_yoy - prev_rev_yoy
            prev_rev_yoy = rev_yoy

        return last_accel

    def calculate_growth_factors(self, data, base_date=None):
        """
        성장 팩터 계산 — 2서브팩터

        G = 매출성장률(TTM YoY) × g_rev + 이익변화량(or RevAccel) × (1-g_rev)
          매출성장률: (최근4Q매출합 / 직전4Q매출합) - 1
          이익변화량: op_change_asset (기본) 또는 Revenue Acceleration (USE_REV_ACCEL=1)
        """
        from pathlib import Path
        from datetime import datetime, timedelta

        base_dt = datetime.strptime(base_date, '%Y%m%d') if base_date else None
        cutoff_date = base_dt - timedelta(days=90) if base_dt else None

        rev_dict = {}
        oca_dict = {}
        stats = {'rev_ttm': 0, 'rev_annual': 0, 'oca': 0}

        for ticker in data['종목코드']:
            try:
                dart_file = Path('data_cache') / f'fs_dart_{ticker}.parquet'
                fn_file = Path('data_cache') / f'fs_fnguide_{ticker}.parquet'

                candidates = []
                if dart_file.exists() and fn_file.exists():
                    try:
                        from create_current_portfolio import _check_data_mismatch
                        d_df = pd.read_parquet(dart_file)
                        f_df = pd.read_parquet(fn_file)
                        if _check_data_mismatch(d_df, f_df):
                            candidates = [fn_file, dart_file]
                        else:
                            candidates = [dart_file, fn_file]
                    except Exception:
                        candidates = [dart_file, fn_file]
                elif dart_file.exists():
                    candidates = [dart_file]
                elif fn_file.exists():
                    candidates = [fn_file]
                else:
                    continue

                for cache_file in candidates:
                    fs = pd.read_parquet(cache_file)

                    # 매출 TTM YoY → 연간 폴백
                    if ticker not in rev_dict:
                        rev = self._calc_ttm_yoy(fs, '매출액', base_dt, cutoff_date)
                        if rev is not None:
                            rev_dict[ticker] = rev
                            stats['rev_ttm'] += 1
                        else:
                            rev = self._calc_annual_yoy(fs, '매출액', base_dt, cutoff_date)
                            if rev is not None:
                                rev_dict[ticker] = rev
                                stats['rev_annual'] += 1

                    # op_change_asset 또는 Revenue Acceleration
                    if ticker not in oca_dict:
                        use_rev_accel = os.environ.get('USE_REV_ACCEL') == '1'
                        if use_rev_accel:
                            oca = self._calc_revenue_acceleration(fs, base_dt, cutoff_date)
                        else:
                            oca = self._calc_op_change_asset(fs, base_dt, cutoff_date)
                        if oca is not None:
                            oca_dict[ticker] = oca
                            stats['oca'] += 1

                    # 둘 다 찾았으면 다음 후보 불필요
                    if ticker in rev_dict and ticker in oca_dict:
                        break

            except Exception:
                continue

        data['매출성장률'] = data['종목코드'].map(rev_dict)
        data['이익변화량'] = data['종목코드'].map(oca_dict)

        rev_cover = data['매출성장률'].notna().sum()
        oca_cover = data['이익변화량'].notna().sum()
        print(f"매출성장률(TTM YoY): {rev_cover}/{len(data)}개 (TTM:{stats['rev_ttm']} 연간:{stats['rev_annual']})")
        oca_label = "매출가속도(RevAccel)" if os.environ.get('USE_REV_ACCEL') == '1' else "이익변화량(op_change_asset)"
        print(f"{oca_label}: {oca_cover}/{len(data)}개")

        return data

    def calculate_momentum(self, data, price_df, mom_period='6m'):
        """
        모멘텀 팩터 계산 — 리스크 조정 모멘텀

        mom_period: '6m'(현행), '6m-1m', '12m-1m', '12m'
        Score = 수익률 / 변동성(연환산)
        """
        LOOKBACK_6M = 6 * 21    # 126 거래일
        LOOKBACK_12M = 12 * 21  # 252 거래일
        LOOKBACK_1M = 21        # 21 거래일
        VOL_FLOOR = 15.0

        if mom_period in ('12m', '12m-1m'):
            min_required = LOOKBACK_12M + 1
        else:
            min_required = LOOKBACK_6M + 1

        if price_df is None or price_df.empty:
            print(f"경고: 가격 데이터가 없습니다.")
            data['모멘텀'] = np.nan
            return data

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

                    if mom_period == '6m':
                        price_start = prices.iloc[-(LOOKBACK_6M + 1)]
                        if price_start <= 0: continue
                        ret = (price_current / price_start - 1) * 100
                        daily_returns = prices.iloc[-(LOOKBACK_6M + 1):].pct_change().dropna()
                    elif mom_period == '6m-1m':
                        price_start = prices.iloc[-(LOOKBACK_6M + 1)]
                        price_1m = prices.iloc[-(LOOKBACK_1M + 1)]
                        if price_start <= 0 or price_1m <= 0: continue
                        ret = (price_1m / price_start - 1) * 100
                        daily_returns = prices.iloc[-(LOOKBACK_6M + 1):-(LOOKBACK_1M)].pct_change().dropna()
                    elif mom_period == '12m-1m':
                        price_start = prices.iloc[-(LOOKBACK_12M + 1)]
                        price_1m = prices.iloc[-(LOOKBACK_1M + 1)]
                        if price_start <= 0 or price_1m <= 0: continue
                        ret = (price_1m / price_start - 1) * 100
                        daily_returns = prices.iloc[-(LOOKBACK_12M + 1):-(LOOKBACK_1M)].pct_change().dropna()
                    elif mom_period == '12m':
                        price_start = prices.iloc[-(LOOKBACK_12M + 1)]
                        if price_start <= 0: continue
                        ret = (price_current / price_start - 1) * 100
                        daily_returns = prices.iloc[-(LOOKBACK_12M + 1):].pct_change().dropna()
                    else:
                        continue

                    annual_vol = daily_returns.std() * np.sqrt(252) * 100
                    annual_vol = max(annual_vol, VOL_FLOOR)

                    momentum = ret / annual_vol
                    momentum_dict[ticker] = momentum
                    matched_count += 1
                except (IndexError, KeyError):
                    continue

        data['모멘텀'] = data['종목코드'].map(momentum_dict)
        print(f"모멘텀({mom_period}/Vol) 계산 완료: {matched_count}/{len(data)}개 매칭")
        print(f"  공식: {mom_period}수익률 / 변동성(연환산, floor={VOL_FLOOR}%)")

        # K_ratio: 추세 일관성 (log-price 회귀 기울기 / 표준오차)
        kratio_dict = {}
        kr_count = 0
        for ticker in data['종목코드']:
            if ticker in price_df.columns:
                prices = price_df[ticker].dropna()
                if len(prices) < min_required:
                    continue
                try:
                    log_prices = np.log(prices.iloc[-(LOOKBACK_6M + 1):].values)
                    x = np.arange(len(log_prices))
                    slope, _, _, _, std_err = stats.linregress(x, log_prices)
                    if std_err > 0:
                        kratio_dict[ticker] = slope / std_err
                        kr_count += 1
                except (ValueError, IndexError):
                    continue

        data['K_ratio'] = data['종목코드'].map(kratio_dict)
        print(f"K_ratio 계산 완료: {kr_count}/{len(data)}개 매칭")

        return data

    def _winsorize(self, series, lower=0.01, upper=0.99):
        """상하위 극단값 클리핑 (윈저라이징)"""
        q_low = series.quantile(lower)
        q_high = series.quantile(upper)
        return series.clip(q_low, q_high)

    def calculate_multifactor_score(self, data, price_df=None, sector_map=None, base_date=None, mom_period='6m'):
        """
        멀티팩터 종합 점수 계산 — v69 4팩터 동일가중 (V+Q+G+M = 25% each)

        헨리 원본 rank z-score 기반 + 실시간/전방성 강화
        V/Q/G: 전체 유니버스 rank z-score (절대 비교)
        M: 섹터 내 rank z-score (섹터 추세 제거)
        + FWD_PER 보너스

        Args:
            data: 재무 데이터프레임
            price_df: 가격 데이터프레임 (모멘텀 계산용)
            sector_map: 섹터 맵 (dict: ticker -> sector_name), None이면 전체 유니버스 z-score
            base_date: 기준일 (YYYYMMDD), 성장팩터 point-in-time 필터용
        """
        # 1. 밸류 팩터 계산
        data = self.calculate_value_factors(data)

        # 2. 퀄리티 팩터 계산
        data = self.calculate_quality_factors(data)

        # 2.5. 성장 팩터 계산 (v69 신규)
        data = self.calculate_growth_factors(data, base_date=base_date)

        # 3. 모멘텀 팩터 계산
        if price_df is not None:
            data = self.calculate_momentum(data, price_df, mom_period=mom_period)

        # 3.3. 섹터 정보 매핑
        if sector_map:
            data['섹터'] = data['종목코드'].map(sector_map).fillna('기타')
            sector_coverage = data['섹터'].notna().sum()
            sector_counts = data['섹터'].value_counts()
            large = (sector_counts >= 5).sum()
            small = (sector_counts < 5).sum()
            print(f"섹터 매핑: {sector_coverage}/{len(data)}개 종목, {large}개 대형섹터(≥5), {small}개 소형섹터(<5)")

        # 3.5. 이상치 전처리 — 밸류 지표 0 이하 → NaN
        for col in ['PER', 'PBR', 'PCR', 'PSR']:
            if col in data.columns:
                data.loc[data[col] <= 0, col] = np.nan

        # 3.6. PER > 200 제외 — 실질 이익 없는 기업 (잔존가치 없음)
        if 'PER' in data.columns:
            extreme_per_mask = data['PER'] > 200
            extreme_per_count = extreme_per_mask.sum()
            if extreme_per_count > 0:
                extreme_per_names = data.loc[extreme_per_mask, '종목명'].tolist() if '종목명' in data.columns else []
                data = data[~extreme_per_mask].copy()
                print(f"PER>200 제외: {extreme_per_count}개 (잔존가치 없음) {extreme_per_names[:5]}")

        # 4. Rank-based z-score (이현열 원본 방식 + 섹터 중립화 통합)
        # 순위 → 균등분포 → 정규 z-score 변환
        # 장점: 원값 분포와 무관하게 대칭 분포 보장, 팩터 간 동일 스케일
        MIN_SECTOR_SIZE = 10  # rank 해상도 확보 (5→10 상향)
        from scipy.stats import norm

        def rank_zscore(series, ascending=True, sectors=None):
            """Rank-based z-score, 선택적 섹터 중립
            ascending=True: 값이 높을수록 좋음 (ROE, GPA 등)
            ascending=False: 값이 낮을수록 좋음 (PER, PBR 등)
            """
            valid = series.dropna()
            if len(valid) < 5:
                return pd.Series(np.nan, index=series.index)

            def _rank_to_z(vals):
                """순위 → 균등분포 → 정규 z-score"""
                n = len(vals)
                if n < 3:
                    return pd.Series(0.0, index=vals.index)
                ranks = vals.rank(ascending=ascending, method='average')
                # Blom 변환: (rank - 3/8) / (n + 1/4) → 정규분포 ppf
                uniform = (ranks - 0.375) / (n + 0.25)
                uniform = uniform.clip(0.001, 0.999)  # ppf 안전 범위
                return pd.Series(norm.ppf(uniform), index=vals.index)

            if sectors is None:
                # 전체 유니버스 rank z-score
                result = pd.Series(np.nan, index=series.index)
                valid_mask = series.notna()
                result[valid_mask] = _rank_to_z(series[valid_mask])
                return result

            # 섹터 중립 rank z-score (섹터 내 rank = 중립화 통합)
            result = pd.Series(np.nan, index=series.index)
            valid_mask = series.notna()

            # 전체 유니버스 rank z-score (소형 섹터 fallback용)
            full_z = pd.Series(np.nan, index=series.index)
            full_z[valid_mask] = _rank_to_z(series[valid_mask])

            for sector_name in sectors[valid_mask].unique():
                sector_mask = (sectors == sector_name) & valid_mask
                count = sector_mask.sum()

                if count >= MIN_SECTOR_SIZE:
                    # 대형 섹터: 섹터 내 rank z-score
                    result[sector_mask] = _rank_to_z(series[sector_mask])
                else:
                    # 소형 섹터: 전체 유니버스 fallback
                    result[sector_mask] = full_z[sector_mask]

            return result

        # 섹터 시리즈 준비
        sectors = data['섹터'] if sector_map else None

        # 서브팩터별 Rank-based z-score (이현열 원본 방식)
        # V, Q, G: 전체 유니버스 rank z-score (절대 비교)
        # M: 섹터 내 rank z-score (섹터 추세 제거)
        value_zs = []
        for col in ['PER', 'PBR', 'PCR', 'PSR']:
            if col in data.columns:
                data[f'{col}_z'] = rank_zscore(data[col], ascending=False, sectors=None)
                value_zs.append(f'{col}_z')
                valid_count = data[col].notna().sum()
                print(f"  {col} 커버리지: {valid_count}/{len(data)}개 ({valid_count/len(data)*100:.0f}%)")

        quality_zs = []
        for col in ['ROE', 'GPA', 'CFO']:
            if col in data.columns and data[col].notna().sum() > 0:
                data[f'{col}_z'] = rank_zscore(data[col], ascending=True, sectors=None)
                quality_zs.append(f'{col}_z')

        growth_zs = []
        if '매출성장률' in data.columns and data['매출성장률'].notna().sum() > 0:
            data['매출성장률_z'] = rank_zscore(data['매출성장률'], ascending=True, sectors=None)
            growth_zs.append('매출성장률_z')
        if '이익변화량' in data.columns and data['이익변화량'].notna().sum() > 0:
            data['이익변화량_z'] = rank_zscore(data['이익변화량'], ascending=True, sectors=None)
            growth_zs.append('이익변화량_z')

        momentum_zs = []
        if '모멘텀' in data.columns:
            data['모멘텀_z'] = rank_zscore(data['모멘텀'], ascending=True, sectors=sectors)
            momentum_zs.append('모멘텀_z')
        if 'K_ratio' in data.columns and data['K_ratio'].notna().sum() > 0:
            data['K_ratio_z'] = rank_zscore(data['K_ratio'], ascending=True, sectors=sectors)
            momentum_zs.append('K_ratio_z')

        sn_tag = "SectorNeutral" if sector_map else "FullUniverse"
        print(f"Rank z-score ({sn_tag}): V{len(value_zs)} Q{len(quality_zs)} G{len(growth_zs)} M{len(momentum_zs)}")

        # 5. 카테고리 평균 (NaN 처리 + 스케일 통일)
        # Growth 특별 처리: 이익변화량 NaN → 매출 z-score로 대체 (데이터 부족 종목 공정성)
        if '이익변화량_z' in growth_zs and '매출성장률_z' in growth_zs:
            oca_nan = data['이익변화량_z'].isna()
            data.loc[oca_nan, '이익변화량_z'] = data.loc[oca_nan, '매출성장률_z']

        for zs in [value_zs, quality_zs, growth_zs, momentum_zs]:
            for col in zs:
                data[col] = data[col].fillna(0.0)

        data['밸류_raw'] = data[value_zs].mean(axis=1) if value_zs else 0
        data['퀄리티_raw'] = data[quality_zs].mean(axis=1) if quality_zs else 0

        # Growth: 매출성장률 vs 이익변화량 가중 평균 (G_REVENUE_WEIGHT 환경변수로 조절)
        # 기본값 0.5 = 50:50 동일가중, 0.7 = 매출70:이익30, 0.3 = 매출30:이익70
        if len(growth_zs) == 2 and '매출성장률_z' in growth_zs and '이익변화량_z' in growth_zs:
            g_rev_w = float(os.environ.get('G_REVENUE_WEIGHT', '0.7'))
            g_oca_w = 1.0 - g_rev_w
            data['성장_raw'] = data['매출성장률_z'] * g_rev_w + data['이익변화량_z'] * g_oca_w
            print(f"Growth 가중: 매출 {g_rev_w*100:.0f}% + 이익변화량 {g_oca_w*100:.0f}%")
        else:
            data['성장_raw'] = data[growth_zs].mean(axis=1) if growth_zs else 0

        data['모멘텀_raw'] = data[momentum_zs].mean(axis=1) if momentum_zs else 0

        # 6. 카테고리별 재표준화 (std=1, 헨리 원본 동일)
        for raw_col, score_col in [('밸류_raw', '밸류_점수'), ('퀄리티_raw', '퀄리티_점수'),
                                    ('성장_raw', '성장_점수'), ('모멘텀_raw', '모멘텀_점수')]:
            valid = data[raw_col].dropna()
            cat_mean = valid.mean() if len(valid) > 0 else 0
            cat_std = valid.std() if len(valid) > 0 else 0
            if cat_std > 0:
                data[score_col] = (data[raw_col] - cat_mean) / cat_std
            else:
                data[score_col] = 0.0
            data[score_col] = data[score_col].fillna(0.0)

        # 6.5. ROE 하드게이트: ROE <= 0% (적자 기업) → 무조건 제외
        # pykrx는 적자 시 EPS=0 반환 → ROE=0이 되므로 <= 0으로 필터
        if 'ROE' in data.columns:
            roe_neg_mask = data['ROE'] <= 0
            roe_neg_count = roe_neg_mask.sum()
            if roe_neg_count > 0:
                roe_neg_names = data.loc[roe_neg_mask, '종목명'].tolist() if '종목명' in data.columns else []
                data = data[~roe_neg_mask].copy()
                print(f"ROE 하드게이트: {roe_neg_count}개 제외 (ROE<0%) {roe_neg_names[:5]}")

        # 7. 단일팩터 바닥 — 4팩터 동일가중에서 자연 방어 부족 보완
        # 3팩터: (-3+3+3)/3=1.0σ 자연 방어 OK, 4팩터: (-3+3+3+3)/4=1.5σ 방어 부족
        EXTREME_THRESHOLD = -1.5  # rank z-score 하위 ~7%
        cat_cols_4 = ['밸류_점수', '퀄리티_점수', '성장_점수', '모멘텀_점수']
        extreme_mask = (data[cat_cols_4] < EXTREME_THRESHOLD).any(axis=1)
        extreme_count = extreme_mask.sum()
        if extreme_count > 0:
            extreme_names = data.loc[extreme_mask, '종목명'].tolist() if '종목명' in data.columns else []
            data = data[~extreme_mask].copy()
            print(f"단일팩터 바닥: {extreme_count}개 제외 (1개라도 <{EXTREME_THRESHOLD}σ) {extreme_names[:5]}")

        # 8. 최종 가중합 (환경변수로 동적 설정 가능)
        V_W = float(os.environ.get('FACTOR_V_W', '0.20'))
        Q_W = float(os.environ.get('FACTOR_Q_W', '0.20'))
        G_W = float(os.environ.get('FACTOR_G_W', '0.45'))
        M_W = float(os.environ.get('FACTOR_M_W', '0.15'))

        if momentum_zs:
            data['멀티팩터_점수'] = (data['밸류_점수'] * V_W +
                                    data['퀄리티_점수'] * Q_W +
                                    data['성장_점수'] * G_W +
                                    data['모멘텀_점수'] * M_W)
            print(f"멀티팩터 가중치: V{int(V_W*100)} + Q{int(Q_W*100)} + G{int(G_W*100)} + M{int(M_W*100)} ({sn_tag})")
        else:
            data['멀티팩터_점수'] = (data['밸류_점수'] * 0.5 +
                                    data['퀄리티_점수'] * 0.5)
            print("멀티팩터 가중치: Value 50% + Quality 50% (모멘텀 없음)")

        # 8.5 FWD_PER 보너스: 컨센서스 있고 EPS 개선 시 가산
        # DISABLE_FWD_BONUS=1 → 백테스트 시 과거 컨센서스 없으므로 비활성화
        if os.environ.get('DISABLE_FWD_BONUS') == '1':
            pass  # 보너스 스킵
        elif 'forward_per' in data.columns and 'PER' in data.columns:
            fwd_mask = (data['forward_per'] > 0) & (data['PER'] > 0)
            eps_improving = fwd_mask & (data['forward_per'] < data['PER'])  # FWD_PER < PER = 실적 개선
            bonus_count = eps_improving.sum()
            if bonus_count > 0:
                # 보너스 크기: 전체 점수 std의 10%
                score_std = data['멀티팩터_점수'].std()
                BONUS_ALPHA = 0.10
                data.loc[eps_improving, '멀티팩터_점수'] += score_std * BONUS_ALPHA
                print(f"FWD_PER 보너스: {bonus_count}개 종목 (EPS 개선 기대, +{BONUS_ALPHA*100:.0f}% std)")

        # 순위 계산 (높을수록 좋음)
        data['멀티팩터_순위'] = data['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')

        return data

    def select_top_stocks(self, data, n_stocks=20):
        """상위 종목 선정"""
        data_clean = data.dropna(subset=['멀티팩터_순위'])
        data_sorted = data_clean.sort_values('멀티팩터_점수', ascending=False)
        selected = data_sorted.head(n_stocks)
        return selected

    def run(self, financial_data, price_df=None, n_stocks=20, sector_map=None, base_date=None, mom_period='6m'):
        """
        멀티팩터 전략 실행

        Args:
            financial_data: 재무 데이터프레임
            price_df: 가격 데이터프레임
            n_stocks: 선정할 종목 수
            sector_map: 섹터 맵 (dict: ticker -> sector_name)
            base_date: 기준일 (YYYYMMDD), point-in-time 필터용
            mom_period: 모멘텀 기간 ('6m', '6m-1m', '12m-1m', '12m')
        """
        scored_data = self.calculate_multifactor_score(
            financial_data.copy(),
            price_df=price_df,
            sector_map=sector_map,
            base_date=base_date,
            mom_period=mom_period,
        )
        selected_stocks = self.select_top_stocks(scored_data, n_stocks)
        return selected_stocks, scored_data


if __name__ == '__main__':
    print("멀티팩터 전략 테스트")

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

    strategy = MultiFactorStrategy()
    selected, full_data = strategy.run(test_data, price_df=None, n_stocks=3)

    print("\n선정된 종목:")
    print(selected[['종목코드', '종목명', '멀티팩터_점수', '밸류_점수', '퀄리티_점수']])

    print("\n전체 종목 점수:")
    print(full_data[['종목코드', '종목명', '멀티팩터_점수', '멀티팩터_순위']].sort_values('멀티팩터_점수', ascending=False))
