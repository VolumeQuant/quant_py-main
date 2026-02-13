"""
신용시장 모니터링 — US HY Spread (FRED) + 한국 BBB- 신용스프레드 (ECOS)

Verdad 4분면 모델:
  수준: HY vs 10년 롤링 중위수 (넓/좁)
  방향: 현재 vs 63영업일(3개월) 전 (상승/하락)
  → Q1 회복(넓+하락), Q2 성장(좁+하락), Q3 과열(좁+상승), Q4 침체(넓+상승)

현금비중:
  Layer 1 (미국): US HY Spread 4분면 → 기본 현금비중 (0~70%)
  Layer 2 (한국): BBB- 신용스프레드 → 가감 조정 (±10~20%)
"""

import urllib.request
import io
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def fetch_hy_quadrant():
    """US HY Spread Verdad 4분면 + 해빙 신호 (FRED BAMLH0A0HYM2)

    Returns:
        dict or None
    """
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365 * 11)).strftime('%Y-%m-%d')
        url = (
            f"https://fred.stlouisfed.org/graph/fredgraph.csv"
            f"?id=BAMLH0A0HYM2&cosd={start_date}&coed={end_date}"
        )
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            csv_data = response.read().decode('utf-8')

        df = pd.read_csv(io.StringIO(csv_data), parse_dates=['observation_date'])
        df.columns = ['date', 'hy_spread']
        df = df.dropna(subset=['hy_spread'])
        df['hy_spread'] = pd.to_numeric(df['hy_spread'], errors='coerce')
        df = df.dropna().set_index('date').sort_index()

        if len(df) < 1260:
            print("  [HY] 데이터 부족 (최소 5년 필요)")
            return None

        # 10년 롤링 중위수 (min 5년)
        df['median_10y'] = df['hy_spread'].rolling(2520, min_periods=1260).median()

        hy_spread = df['hy_spread'].iloc[-1]
        hy_prev = df['hy_spread'].iloc[-2]
        median_10y = df['median_10y'].iloc[-1]

        if pd.isna(median_10y):
            print("  [HY] 중위수 계산 불가")
            return None

        # 3개월(63영업일) 전
        hy_3m_ago = df['hy_spread'].iloc[-63] if len(df) >= 63 else df['hy_spread'].iloc[0]

        # 분면 판정
        is_wide = hy_spread >= median_10y
        is_rising = hy_spread >= hy_3m_ago

        if is_wide and not is_rising:
            quadrant, label, icon = 'Q1', '회복기', '🟢'
        elif not is_wide and not is_rising:
            quadrant, label, icon = 'Q2', '성장기', '🟢'
        elif not is_wide and is_rising:
            quadrant, label, icon = 'Q3', '과열기', '🟡'
        else:
            quadrant, label, icon = 'Q4', '침체기', '🔴'

        # 해빙 신호 (= 적극 매수 기회)
        signals = []
        daily_change_bp = (hy_spread - hy_prev) * 100

        if 4 <= hy_spread <= 5 and daily_change_bp <= -20:
            signals.append(f'💎 HY {hy_spread:.2f}%, 전일 대비 {daily_change_bp:+.0f}bp 급락 — 반등 매수 기회에요!')

        if hy_prev >= 5 and hy_spread < 5:
            signals.append(f'💎 HY {hy_spread:.2f}%로 5% 밑으로 내려왔어요 — 적극 매수 구간이에요!')

        peak_60d = df['hy_spread'].rolling(60).max().iloc[-1]
        from_peak_bp = (hy_spread - peak_60d) * 100
        if from_peak_bp <= -300:
            signals.append(f'💎 60일 고점 대비 {from_peak_bp:.0f}bp 하락 — 바닥 신호, 적극 매수하세요!')

        # Q4→Q1 전환 감지
        prev_wide = hy_prev >= median_10y
        hy_3m_ago_prev = df['hy_spread'].iloc[-64] if len(df) >= 64 else df['hy_spread'].iloc[0]
        prev_rising = hy_prev >= hy_3m_ago_prev
        if (prev_wide and prev_rising) and (is_wide and not is_rising):
            signals.append('💎 침체기→회복기 전환 — 가장 좋은 매수 타이밍이에요!')

        # 분면 지속 일수 (최대 252영업일)
        df['hy_3m'] = df['hy_spread'].shift(63)
        valid_mask = df['median_10y'].notna() & df['hy_3m'].notna()
        df.loc[valid_mask, 'q'] = np.where(
            df.loc[valid_mask, 'hy_spread'] >= df.loc[valid_mask, 'median_10y'],
            np.where(df.loc[valid_mask, 'hy_spread'] >= df.loc[valid_mask, 'hy_3m'], 'Q4', 'Q1'),
            np.where(df.loc[valid_mask, 'hy_spread'] >= df.loc[valid_mask, 'hy_3m'], 'Q3', 'Q2')
        )
        q_days = 1
        for i in range(len(df) - 2, max(len(df) - 253, 0) - 1, -1):
            if i >= 0 and df['q'].iloc[i] == quadrant:
                q_days += 1
            else:
                break

        # 현금비중 + 행동 권장
        if quadrant == 'Q4':
            if q_days <= 20:
                cash_pct, action = 30, '신규 매수를 멈추고 관망하세요.'
            elif q_days <= 60:
                cash_pct, action = 50, '보유 종목을 줄이고 현금을 늘리세요.'
            else:
                cash_pct, action = 70, '현금을 최대한 확보하세요.'
        elif quadrant == 'Q3':
            if q_days >= 60:
                cash_pct, action = 30, '신규 매수를 줄여가세요.'
            else:
                cash_pct, action = 20, '매수할 때 신중하게 판단하세요.'
        elif quadrant == 'Q1':
            cash_pct, action = 0, '적극 매수하세요. 역사적으로 수익률이 가장 높은 구간이에요.'
        else:
            cash_pct, action = 20, '평소대로 투자하세요.'

        return {
            'hy_spread': hy_spread,
            'median_10y': median_10y,
            'hy_3m_ago': hy_3m_ago,
            'hy_prev': hy_prev,
            'quadrant': quadrant,
            'quadrant_label': label,
            'quadrant_icon': icon,
            'signals': signals,
            'q_days': q_days,
            'cash_pct': cash_pct,
            'action': action,
        }

    except Exception as e:
        print(f"  [HY] 수집 실패: {e}")
        return None


def fetch_kr_credit_spread(api_key: str = None):
    """한국 신용스프레드 = 회사채 BBB- 금리 - 국고채 3년 금리 (ECOS API)

    Args:
        api_key: ECOS API 인증키 (없으면 None 반환)

    Returns:
        dict or None
    """
    if not api_key:
        return None

    try:
        import requests

        # 5년치 일별 데이터
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=365 * 5)).strftime('%Y%m%d')

        def _fetch_ecos_rate(item_code, item_name):
            url = (
                f"https://ecos.bok.or.kr/api/StatisticSearch"
                f"/{api_key}/json/kr/1/10000"
                f"/817Y002/D/{start_date}/{end_date}/{item_code}"
            )
            resp = requests.get(url, timeout=15)
            data = resp.json()

            rows = data.get('StatisticSearch', {}).get('row', [])
            if not rows:
                print(f"  [KR] {item_name} 데이터 없음")
                return None

            records = []
            for row in rows:
                try:
                    records.append({
                        'date': pd.Timestamp(row['TIME']),
                        'rate': float(row['DATA_VALUE']),
                    })
                except (ValueError, KeyError):
                    continue

            df = pd.DataFrame(records).set_index('date').sort_index()
            df = df[~df.index.duplicated(keep='last')]
            return df

        # 국고채 3년 (010200000) + 회사채 BBB- (010320000)
        ktb_df = _fetch_ecos_rate('010200000', '국고채 3년')
        bbb_df = _fetch_ecos_rate('010320000', '회사채 BBB-')

        if ktb_df is None or bbb_df is None:
            return None

        # 스프레드 계산
        merged = ktb_df.join(bbb_df, lsuffix='_ktb', rsuffix='_bbb', how='inner')
        merged.columns = ['ktb_3y', 'bbb_rate']
        merged['spread'] = merged['bbb_rate'] - merged['ktb_3y']
        merged = merged.dropna()

        if len(merged) < 250:
            print(f"  [KR] 데이터 부족: {len(merged)}일")
            return None

        spread = merged['spread'].iloc[-1]
        spread_prev = merged['spread'].iloc[-2]

        # 5년 롤링 중위수
        median_5y = merged['spread'].rolling(1260, min_periods=500).median().iloc[-1]
        if pd.isna(median_5y):
            median_5y = merged['spread'].median()

        # 3개월 전 대비 추세
        spread_3m_ago = merged['spread'].iloc[-63] if len(merged) >= 63 else merged['spread'].iloc[0]
        is_rising = spread >= spread_3m_ago

        # 레짐 판단
        # 정상: < 중위수 + 1%p
        # 경계: 중위수 + 1%p ~ 중위수 + 2%p
        # 위기: > 중위수 + 2%p
        if spread >= median_5y + 2.0:
            regime = 'stress'
            regime_label = '위기'
            regime_icon = '🔴'
        elif spread >= median_5y + 1.0:
            regime = 'caution'
            regime_label = '경계'
            regime_icon = '🟡'
        else:
            regime = 'normal'
            regime_label = '정상'
            regime_icon = '🟢'

        # 현금비중 가감
        if regime == 'stress':
            if is_rising:
                adjustment = 20   # 위기 + 악화 중
            else:
                adjustment = 10   # 위기 + 개선 중
        elif regime == 'caution':
            if is_rising:
                adjustment = 10   # 경계 + 악화 중
            else:
                adjustment = 0    # 경계 + 개선 중
        else:
            adjustment = 0        # 정상

        return {
            'spread': spread,
            'spread_prev': spread_prev,
            'median_5y': median_5y,
            'spread_3m_ago': spread_3m_ago,
            'regime': regime,
            'regime_label': regime_label,
            'regime_icon': regime_icon,
            'adjustment': adjustment,
            'ktb_3y': merged['ktb_3y'].iloc[-1],
            'bbb_rate': merged['bbb_rate'].iloc[-1],
        }

    except Exception as e:
        print(f"  [KR] 신용스프레드 수집 실패: {e}")
        return None


def get_credit_status(ecos_api_key: str = None):
    """신용시장 통합 상태 조회

    Returns:
        dict {
            'hy': dict or None,          # US HY Spread 결과
            'kr': dict or None,          # 한국 BBB- 스프레드 결과
            'final_cash_pct': int,       # 최종 현금비중 (0~70)
            'final_action': str,         # 최종 행동 권장
            'summary_line': str,         # 텔레그램 요약 한 줄
        }
    """
    print("\n[신용시장 모니터링]")

    # Layer 1: US HY Spread
    print("  US HY Spread 조회 중...")
    hy = fetch_hy_quadrant()
    if hy:
        print(f"  [HY] {hy['hy_spread']:.2f}% | 중위 {hy['median_10y']:.2f}% | "
              f"{hy['quadrant']} {hy['quadrant_label']} ({hy['q_days']}일째)")
        print(f"  [HY] 기본 현금 {hy['cash_pct']}% · {hy['action']}")
        if hy['signals']:
            for sig in hy['signals']:
                print(f"  [HY] 해빙: {sig}")
    else:
        print("  [HY] 수집 실패 — 기본값(현금 20%) 적용")

    # Layer 2: 한국 BBB- 신용스프레드
    kr = None
    if ecos_api_key:
        print("  한국 BBB- 스프레드 조회 중...")
        kr = fetch_kr_credit_spread(ecos_api_key)
        if kr:
            print(f"  [KR] BBB- {kr['bbb_rate']:.2f}% - 국고채 {kr['ktb_3y']:.2f}% = "
                  f"스프레드 {kr['spread']:.2f}%p ({kr['regime_label']})")
            print(f"  [KR] 현금비중 가감: {kr['adjustment']:+d}%")
        else:
            print("  [KR] 수집 실패 — 가감 없이 진행")

    # 최종 현금비중 산출
    if hy:
        base_cash = hy['cash_pct']
        kr_adj = kr['adjustment'] if kr else 0
        final_cash = max(0, min(70, base_cash + kr_adj))

        # 양쪽 모두 극단일 때 오버라이드
        if hy['quadrant'] == 'Q4' and kr and kr['regime'] == 'stress':
            final_cash = 70
        elif hy['quadrant'] == 'Q1' and (kr is None or kr['regime'] == 'normal'):
            final_cash = 0

        final_action = hy['action']
    else:
        final_cash = 20
        final_action = '데이터 수집 실패로 기본값을 적용했어요.'

    print(f"  → 최종 현금비중: {final_cash}%")

    return {
        'hy': hy,
        'kr': kr,
        'final_cash_pct': final_cash,
        'final_action': final_action,
    }


def format_credit_section(credit: dict, n_picks: int = 5) -> str:
    """텔레그램 메시지용 신용시장 섹션 포맷팅

    Args:
        credit: get_credit_status() 반환값
        n_picks: 최종 종목 수 (비중 계산용)

    Returns:
        str: 텔레그램 메시지 블록
    """
    hy = credit['hy']
    kr = credit['kr']
    final_cash = credit['final_cash_pct']
    final_action = credit['final_action']

    lines = ['─────────────────']

    if hy:
        lines.append(f"{hy['quadrant_icon']} <b>신용시장</b> — {hy['quadrant_label']}")

        # HY 수치 + 맥락 해석
        hy_val = hy['hy_spread']
        med_val = hy['median_10y']
        q = hy['quadrant']
        if q == 'Q1':
            interp = f"평균({med_val:.2f}%)보다 높지만 빠르게 내려오고 있어요."
        elif q == 'Q2':
            interp = f"평균({med_val:.2f}%)보다 낮아서 안정적이에요."
        elif q == 'Q3':
            interp = f"평균({med_val:.2f}%) 이하지만 올라가는 중이에요."
        else:
            interp = f"평균({med_val:.2f}%)보다 높고 계속 올라가고 있어요."
        lines.append(f"HY Spread(부도위험) {hy_val:.2f}%")
        lines.append(interp)

        if kr:
            kr_interp = {'정상': '정상 범위에요.', '경계': '경계 수준이에요.', '위기': '위험 수준이에요.'}
            lines.append(f"한국 BBB-(회사채) {kr['spread']:.1f}%p")
            lines.append(kr_interp.get(kr['regime_label'], kr['regime_label']))

        # 투자 비중
        if final_cash == 0:
            lines.append('📊 투자 100%')
        else:
            lines.append(f"📊 투자 {100 - final_cash}% + 현금 {final_cash}%")

        # 행동 가이드 (자연어)
        lines.append(f"→ {final_action}")

        # 해빙 신호
        for sig in hy.get('signals', []):
            lines.append(sig)
    else:
        lines.append('📊 <b>신용시장</b> — 데이터 수집 실패')
        lines.append(f'📊 기본 현금 {final_cash}%')

    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    # 단독 테스트
    ecos_key = None
    try:
        from config import ECOS_API_KEY
        ecos_key = ECOS_API_KEY
    except (ImportError, AttributeError):
        pass
    result = get_credit_status(ecos_api_key=ecos_key)
    print("\n" + "=" * 50)
    print(format_credit_section(result))
