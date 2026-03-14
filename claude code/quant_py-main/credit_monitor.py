"""
신용시장 모니터링 — US HY Spread (FRED) + 한국 BBB- 신용스프레드 (ECOS) + VIX (FRED)

v18.2: 현금비중 % 제거 → 행동 등급(Action) 기반 시스템
  - 표시하는 숫자와 실제 행동이 일치해야 한다
  - VIX: 절대값 기준 → 252일 퍼센타일 기반 레짐
  - HY: cash_pct 제거, q_days 기반 행동 강화
  - KR: adjustment 제거, 레짐 정보만 유지
  - _synthesize_action: HY 분면 × VIX 방향 → (action_text, max_picks) + KR 에스컬레이션

Verdad 4분면 모델:
  수준: HY vs 10년 롤링 중위수 (넓/좁)
  방향: 현재 vs 63영업일(3개월) 전 (상승/하락)
  → Q1 회복(넓+하락), Q2 성장(좁+하락), Q3 과열(좁+상승), Q4 침체(넓+상승)

핵심 설계 원칙 (30년 데이터 근거):
  - Q4 초기(≤20일) = 가장 위험 (20일 수익 -0.5~0%)
  - Q4 중기(20~60일) = 턴어라운드 시작 (60일 수익 +0.5~1.5%)
  - Q4 후기(>60일) = 사실상 Q1 수준 (60일 수익 +1.5~2.5%), 분할 매수 사전 포석
  - Q4→Q1 전환 = 역사적 최고 매수 기회 (250일 수익 +8~12%)
  - VIX 40+ 하락 전환 = 12개월 평균 +23.4% → 해빙 신호 동급
  - HY = 방향타, VIX = 속도계 → VIX 단독 결정 불가
"""

import urllib.request
import json as _json
import io
import os
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def _fetch_fred_data(series_id: str, start_date: str, end_date: str, retries: int = 3) -> pd.DataFrame:
    """FRED 데이터 수집 — 공식 API(JSON) 우선, fallback CSV

    Returns:
        DataFrame with columns ['date', 'value'] (date as datetime, value as str)
    """
    fred_key = os.environ.get('FRED_API_KEY', '')
    if not fred_key:
        try:
            from config import FRED_API_KEY
            fred_key = FRED_API_KEY
        except (ImportError, AttributeError):
            pass

    for attempt in range(retries):
        try:
            if fred_key:
                # FRED 공식 API (JSON) — 안정적
                url = (f"https://api.stlouisfed.org/fred/series/observations"
                       f"?series_id={series_id}&api_key={fred_key}&file_type=json"
                       f"&observation_start={start_date}&observation_end={end_date}")
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = _json.loads(response.read().decode('utf-8'))
                rows = [(r['date'], r['value']) for r in data['observations'] if r['value'] != '.']
                df = pd.DataFrame(rows, columns=['date', 'value'])
                df['date'] = pd.to_datetime(df['date'])
                return df
            else:
                # fallback: CSV 엔드포인트
                url = (f"https://fred.stlouisfed.org/graph/fredgraph.csv"
                       f"?id={series_id}&cosd={start_date}&coed={end_date}")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    csv_data = response.read().decode('utf-8')
                df = pd.read_csv(io.StringIO(csv_data), parse_dates=['observation_date'])
                df.columns = ['date', 'value']
                return df
        except Exception as e:
            if attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"  [FRED] {series_id} 시도 {attempt+1}/{retries} 실패: {e} → {wait}초 후 재시도")
                time.sleep(wait)
            else:
                raise


def fetch_hy_quadrant():
    """US HY Spread Verdad 4분면 + 해빙 신호 (FRED BAMLH0A0HYM2)

    Returns:
        dict or None: cash_pct 없음, action은 q_days 기반
    """
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=365 * 11)).strftime('%Y-%m-%d')
        df = _fetch_fred_data('BAMLH0A0HYM2', start_date, end_date)

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
            quadrant, label, icon = 'Q1', '봄(회복국면)', '🌸'
        elif not is_wide and not is_rising:
            quadrant, label, icon = 'Q2', '여름(성장국면)', '☀️'
        elif not is_wide and is_rising:
            quadrant, label, icon = 'Q3', '가을(과열국면)', '🍂'
        else:
            quadrant, label, icon = 'Q4', '겨울(침체국면)', '❄️'

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
            signals.append('💎 겨울→봄 전환 — 가장 좋은 매수 타이밍이에요!')

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

        # 행동 권장 (q_days 기반, 30년 데이터 근거)
        if quadrant == 'Q4':
            if q_days <= 20:
                action = '침체에 진입했어요. 신규 매수를 멈추고 보유 종목을 줄이세요.'
            elif q_days <= 60:
                action = '침체가 지속 중이에요. 신규 매수를 멈추고 관망하세요.'
            else:
                action = '바닥권에 접근하고 있어요. 분할 매수를 시작하세요.'
        elif quadrant == 'Q3':
            if q_days >= 60:
                action = '신규 매수를 줄여가세요.'
            else:
                action = '신규 매수 시 신중하게 판단하세요.'
        elif quadrant == 'Q1':
            action = '적극 매수하세요. 역사적으로 수익률이 가장 높은 구간이에요.'
        else:
            action = '평소대로 투자하세요.'

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
            'action': action,
        }

    except Exception as e:
        print(f"  [HY] 수집 실패: {e}")
        return None


def fetch_vix_data():
    """VIX(CBOE 변동성 지수) 252일 퍼센타일 기반 레짐 판단 (FRED VIXCLS)

    Returns:
        dict or None: cash_adjustment=0 (호환성), vix_pct(퍼센타일) 추가
    """
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=600)).strftime('%Y-%m-%d')
        df = _fetch_fred_data('VIXCLS', start_date, end_date)

        df.columns = ['date', 'vix']
        df['vix'] = pd.to_numeric(df['vix'], errors='coerce')
        df = df.dropna().set_index('date').sort_index()

        if len(df) < 20:
            print("  [VIX] 데이터 부족")
            return None

        vix_current = float(df['vix'].iloc[-1])
        vix_5d_ago = float(df['vix'].iloc[-5]) if len(df) >= 5 else float(df['vix'].iloc[0])
        vix_slope = vix_current - vix_5d_ago
        vix_ma_20 = float(df['vix'].rolling(20).mean().iloc[-1])

        # 252일 퍼센타일 계산
        if len(df) >= 252:
            recent_252 = df['vix'].iloc[-252:]
            vix_pct = float((recent_252 < vix_current).sum() / len(recent_252) * 100)
        else:
            vix_pct = float((df['vix'] < vix_current).sum() / len(df) * 100)

        # Slope direction (±0.5 threshold to avoid noise)
        if vix_slope > 0.5:
            slope_dir = 'rising'
        elif vix_slope < -0.5:
            slope_dir = 'falling'
        else:
            slope_dir = 'flat'

        # 퍼센타일 기반 레짐
        if vix_pct >= 90:
            if slope_dir in ('rising', 'flat'):
                regime, label, icon = 'crisis', '위기', '🔴'
            else:
                regime, label, icon = 'crisis_relief', '공포완화', '💎'
        elif vix_pct >= 80:
            if slope_dir == 'rising':
                regime, label, icon = 'high', '상승경보', '🔶'
            else:
                regime, label, icon = 'high_stable', '높지만안정', '🟡'
        elif vix_pct >= 67:
            if slope_dir == 'rising':
                regime, label, icon = 'elevated', '경계', '⚠️'
            elif slope_dir == 'falling':
                regime, label, icon = 'stabilizing', '안정화', '🟢'
            else:
                regime, label, icon = 'elevated_flat', '보통', '🟡'
        elif vix_pct < 10:
            regime, label, icon = 'complacency', '안일', '⚠️'
        else:  # 10~67 normal
            regime, label, icon = 'normal', '안정', '🟢'

        # Simplified direction for concordance check
        direction = 'warn' if regime in ('crisis', 'high', 'elevated', 'complacency') else 'stable'

        return {
            'vix_current': vix_current,
            'vix_5d_ago': vix_5d_ago,
            'vix_slope': vix_slope,
            'vix_slope_dir': slope_dir,
            'vix_ma_20': vix_ma_20,
            'vix_pct': vix_pct,
            'regime': regime,
            'regime_label': label,
            'regime_icon': icon,
            'cash_adjustment': 0,
            'direction': direction,
        }

    except Exception as e:
        print(f"  [VIX] 수집 실패: {e}")
        return None


def fetch_kr_credit_spread(api_key: str = None):
    """한국 신용스프레드 = 회사채 BBB- 금리 - 국고채 3년 금리 (ECOS API)

    Returns:
        dict or None: adjustment 제거, 레짐 정보만 유지
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

        # 레짐 판단
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

        return {
            'spread': spread,
            'spread_prev': spread_prev,
            'median_5y': median_5y,
            'spread_3m_ago': spread_3m_ago,
            'regime': regime,
            'regime_label': regime_label,
            'regime_icon': regime_icon,
            'ktb_3y': merged['ktb_3y'].iloc[-1],
            'bbb_rate': merged['bbb_rate'].iloc[-1],
        }

    except Exception as e:
        print(f"  [KR] 신용스프레드 수집 실패: {e}")
        return None


def _synthesize_action(hy, kr, vix):
    """HY 분면 × q_days × VIX 방향 → 행동 가이드 + max_picks

    1단계: HY 분면 × VIX 방향으로 기본 액션 결정
    2단계: KR BBB- 에스컬레이션 (경계=경고 추가, 위기=한 단계 하향)

    톤 스펙트럼:
    적극 매수 → 정상 매수 → 매수 유지 → 매수 축소
    → 매수 보류/중단 → 비중 축소 → 매도 검토

    Returns:
        (action_text, max_picks) 튜플
    """
    q = hy['quadrant']
    q_days = hy.get('q_days', 1)
    vix_ok = vix is None or vix['direction'] == 'stable'

    # 1단계: HY × VIX 기본 액션
    if q == 'Q1':
        if vix_ok:
            text, picks = '적극 매수 구간이에요 (과거 연 +14.3%)', 5
        else:
            text, picks = '변동성이 높지만, 분할 매수 유효 구간이에요', 5
    elif q == 'Q2':
        if vix_ok:
            text, picks = '정상 매수 구간이에요 (과거 연 +9.4%)', 5
        else:
            text, picks = '매수 유지, 변동성에 유의하세요', 5
    elif q == 'Q3':
        if q_days < 60:
            if vix_ok:
                text, picks = '매수 유지, 시장 변화에 주의하세요', 5
            else:
                text, picks = '매수 유지하되, 신중하게 접근하세요', 5
        else:
            if vix_ok:
                text, picks = '신규 매수는 신중하게, 보유 종목 점검하세요', 5
            else:
                text, picks = '신규 매수는 보수적으로 접근하세요', 5
    else:  # Q4
        if q_days <= 20:
            if vix_ok:
                text, picks = '급매도 불필요, 관망하세요', 5
            else:
                text, picks = '매수 중단, 관망하세요', 5
        elif q_days <= 60:
            if vix_ok:
                text, picks = '신규 매수 대기, 보유는 유지하세요', 5
            else:
                text, picks = '보유 비중 축소를 검토하세요', 5
        else:
            if vix_ok:
                text, picks = '회복 초입, 분할 매수를 검토하세요', 5
            else:
                text, picks = '바닥권 추정, 소액 분할 매수를 검토하세요', 5

    # 2단계: KR BBB- 에스컬레이션
    kr_regime = kr['regime_label'] if kr else '정상'

    if kr_regime == '위기':
        picks = max(picks - 2, 0)  # 한 단계 하향 (5→3, 3→0)
        # picks=5→3, picks=3→1→0으로 맞추기
        if picks == 1:
            picks = 0
        text = '국내 신용시장이 위험 수준이에요. ' + text
    elif kr_regime == '경계':
        text += ' (국내 신용시장 경계)'

    return text, picks


def get_credit_status(ecos_api_key: str = None):
    """신용시장 통합 상태 조회 (HY + BBB- + VIX + Concordance)

    Returns:
        dict {
            'hy': dict or None,
            'kr': dict or None,
            'vix': dict or None,
            'concordance': str,          # 'both_warn'|'hy_only'|'vix_only'|'both_stable'
            'final_action': str,         # 최종 행동 권장
        }
    """
    print("\n[신용시장 모니터링]")

    # Layer 1: US HY Spread
    print("  US HY Spread 조회 중...")
    hy = fetch_hy_quadrant()
    if hy:
        print(f"  [HY] {hy['hy_spread']:.2f}% | 중위 {hy['median_10y']:.2f}% | "
              f"{hy['quadrant']} {hy['quadrant_label']} ({hy['q_days']}일째)")
        print(f"  [HY] {hy['action']}")
        if hy['signals']:
            for sig in hy['signals']:
                print(f"  [HY] 해빙: {sig}")
    else:
        print("  [HY] 수집 실패 — 기본값 적용")

    # Layer 2: 한국 BBB- 신용스프레드
    kr = None
    if ecos_api_key:
        print("  한국 BBB- 스프레드 조회 중...")
        kr = fetch_kr_credit_spread(ecos_api_key)
        if kr:
            print(f"  [KR] BBB- {kr['bbb_rate']:.2f}% - 국고채 {kr['ktb_3y']:.2f}% = "
                  f"스프레드 {kr['spread']:.2f}%p ({kr['regime_label']})")
        else:
            print("  [KR] 수집 실패")

    # Layer 3: VIX (퍼센타일 기반)
    print("  VIX 조회 중...")
    vix = fetch_vix_data()
    if vix:
        print(f"  [VIX] {vix['vix_current']:.1f} | 퍼센타일 {vix['vix_pct']:.0f}% | "
              f"slope {vix['vix_slope']:+.1f} ({vix['vix_slope_dir']})")
        print(f"  [VIX] 레짐: {vix['regime_label']}")
    else:
        print("  [VIX] 수집 실패")

    # Concordance Check (HY direction vs VIX direction)
    hy_dir = 'warn' if hy and hy['quadrant'] in ('Q3', 'Q4') else 'stable'
    vix_dir = vix['direction'] if vix else 'stable'

    if hy_dir == 'warn' and vix_dir == 'warn':
        concordance = 'both_warn'
    elif hy_dir == 'warn' and vix_dir == 'stable':
        concordance = 'hy_only'
    elif hy_dir == 'stable' and vix_dir == 'warn':
        concordance = 'vix_only'
    else:
        concordance = 'both_stable'

    # 최종 행동 멘트
    if hy:
        final_action, action_max_picks = _synthesize_action(hy, kr, vix)
    else:
        vix_ok = vix is None or vix.get('direction') == 'stable'
        if not vix_ok:
            final_action, action_max_picks = '신규 매수 보수적 접근', 5
        else:
            final_action, action_max_picks = '', 5

    print(f"  → 행동: {final_action}")

    return {
        'hy': hy,
        'kr': kr,
        'vix': vix,
        'concordance': concordance,
        'final_action': final_action,
        'action_max_picks': action_max_picks,
    }


def format_credit_section(credit: dict) -> str:
    """텔레그램 메시지용 시장 위험 지표 섹션 포맷팅

    Args:
        credit: get_credit_status() 반환값

    Returns:
        str: 텔레그램 메시지 블록
    """
    hy = credit['hy']
    kr = credit['kr']
    vix = credit.get('vix')
    final_action = credit['final_action']

    lines = ['─────────────────']

    # 타이틀
    lines.append('🌡️ <b>시장 위험 지표</b>')

    # ── 신용시장 카테고리 ──
    lines.append('')
    lines.append('🏦 <b>신용시장</b>')

    if hy:
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
        lines.append(f"▸ HY Spread(부도위험) {hy_val:.2f}%")
        lines.append(f"  {interp}")
    else:
        lines.append('▸ HY Spread — 수집 실패')

    if kr:
        kr_interp = {'정상': '정상 범위에요.', '경계': '경계 수준이에요.', '위기': '위험 수준이에요.'}
        lines.append(f"▸ 한국 BBB-(회사채) {kr['spread']:.1f}%p")
        lines.append(f"  {kr_interp.get(kr['regime_label'], kr['regime_label'])}")

    # ── 변동성 카테고리 ──
    if vix:
        lines.append('')
        lines.append('⚡ <b>변동성</b>')
        v = vix['vix_current']
        pct = vix['vix_pct']
        slope_arrow = '↑' if vix['vix_slope_dir'] == 'rising' else ('↓' if vix['vix_slope_dir'] == 'falling' else '')
        if vix['regime'] == 'normal':
            lines.append(f"▸ VIX {v:.1f} (1년 중 {pct:.0f}번째)")
            lines.append(f"  안정적이에요.")
        else:
            lines.append(f"▸ VIX {v:.1f}{slope_arrow} (1년 중 {pct:.0f}번째)")
            lines.append(f"  {vix['regime_label']} 구간이에요.")

    # ── 결론 ──
    signals = []
    if hy:
        hy_ok = hy['quadrant'] in ('Q1', 'Q2')
        signals.append(('HY', hy_ok))
    if kr:
        kr_ok = kr['regime'] == 'normal'
        signals.append(('KR', kr_ok))
    if vix:
        vix_ok = vix['direction'] == 'stable'
        signals.append(('VIX', vix_ok))

    lines.append('')
    if signals:
        n_ok = sum(1 for _, ok in signals if ok)
        n_total = len(signals)
        dots = ''.join('🟢' if ok else '🔴' for _, ok in signals)
        if n_ok == n_total:
            conf = '확실한 신호'
        elif n_ok >= n_total - 1 and n_total >= 2:
            conf = '대체로 안정'
        elif n_ok == 0:
            conf = '위험 신호'
        else:
            conf = '엇갈린 신호'
        lines.append(f"{dots} {n_ok}/{n_total} 안정 — {conf}")

        # 봄(Q1) + ALL 안정 → 특별 강조
        if hy and hy['quadrant'] == 'Q1' and n_ok == n_total:
            lines.append('💎 역사적 매수 기회 — 적극 투자하세요!')

    lines.append(f"→ {final_action}")

    # 해빙 신호
    if hy:
        for sig in hy.get('signals', []):
            lines.append(sig)

    return '\n'.join(lines)


def _indicator_icon(indicator: str, data: dict) -> str:
    """개별 지표의 🟢🟡🔴 아이콘 판정"""
    if indicator == 'hy':
        q = data['quadrant']
        q_days = data.get('q_days', 1)
        if q in ('Q1', 'Q2'):
            return '🟢'
        elif q == 'Q3' and q_days < 60:
            return '🟡'
        else:  # Q3 60일+ or Q4
            return '🔴'
    elif indicator == 'vix':
        pct = data['vix_pct']
        if pct < 67:
            return '🟢'
        elif pct < 80:
            return '🟡'
        else:
            return '🔴'
    elif indicator == 'kr':
        regime = data['regime']
        if regime == 'normal':
            return '🟢'
        elif regime == 'caution':
            return '🟡'
        else:
            return '🔴'
    return '🟢'


def _pct_label(pct: float) -> str:
    """퍼센타일 → '상위 N%, 매우 높음' 형태로 변환"""
    if pct >= 90:
        return f"상위 {100 - pct:.0f}%, 매우 높음"
    elif pct >= 67:
        return f"상위 {100 - pct:.0f}%, 높음"
    elif pct <= 10:
        return f"하위 {pct:.0f}%, 매우 낮음"
    elif pct <= 33:
        return f"하위 {pct:.0f}%, 낮음"
    else:
        return "보통"


def _yellow_message(hy_icon, vix_icon, kr_icon):
    """🟡 상태의 구체적 메시지 (톤: '~한 구간')"""
    problems = []
    if hy_icon and hy_icon != '🟢':
        problems.append('신용')
    if vix_icon and vix_icon != '🟢':
        problems.append('변동성')
    if kr_icon and kr_icon != '🟢':
        problems.append('한국신용')

    if problems == ['변동성']:
        return '단기 변동성 확대 — 신규 진입에 신중한 구간'
    elif problems == ['한국신용']:
        return '한국 신용시장 주의 — 국내 포지션에 신중한 구간'
    elif problems == ['신용']:
        return '신용 지표 변화 감지 — 시장 변화에 주의가 필요한 구간'
    else:
        return '일부 지표 주의 — 신규 진입에 신중한 구간'


def _overall_status(hy_icon, vix_icon, kr_icon):
    """HY 우선 종합 판정

    | 종합 | 조건 |
    | 🟢 | 전부 🟢 |
    | 🟡 | HY 🟢 + 나머지 중 비정상 있음 |
    | 🟠 | HY 🔴 단독, 또는 🔴 2개 |
    | 🔴 | HY 🔴 + 다른 🔴 1개 이상 |
    """
    icons = [i for i in [hy_icon, vix_icon, kr_icon] if i is not None]
    hy_red = (hy_icon == '🔴')
    other_reds = sum(1 for i in [vix_icon, kr_icon] if i == '🔴')
    any_non_green = any(i != '🟢' for i in icons)

    if not any_non_green:
        return '🟢', '안정적인 구간'
    elif hy_red and other_reds >= 1:
        return '🔴', '신용·변동성 동반 악화 — 신규 매수 보류가 유리한 구간'
    elif hy_red or other_reds >= 2:
        return '🟠', '복수 지표 악화 — 보수적 비중 조절이 필요한 구간'
    else:
        return '🟡', _yellow_message(hy_icon, vix_icon, kr_icon)


def format_credit_compact(credit: dict) -> list:
    """AI Risk 메시지용 — 1줄 결론 + 개별 근거 (v64)

    Format:
    🟡 단기 변동성 확대 — 신규 진입에 신중한 구간

      🔴 부도위험(HY): 3.17% Q3 과열 12일째
      🟢 공포지수(VIX): 27.3 ↓ (1년 중 상위 6%, 매우 높음)
      🟢 한국신용(BBB-): 6.4%p 정상
    """
    hy = credit.get('hy')
    kr = credit.get('kr')
    vix = credit.get('vix')

    # 데이터 전부 실패
    if not hy and not vix and not kr:
        return ['⚠️ 시장 지표 수집 실패 — 보수적으로 접근하세요']

    # 개별 아이콘 판정
    hy_icon = _indicator_icon('hy', hy) if hy else None
    vix_icon = _indicator_icon('vix', vix) if vix else None
    kr_icon = _indicator_icon('kr', kr) if kr else None

    # 종합 판정 (HY 우선)
    overall_icon, overall_msg = _overall_status(hy_icon, vix_icon, kr_icon)

    lines = [f'<b>{overall_icon} {overall_msg}</b>', '']

    # 개별 근거 (아이콘 없이 텍스트만)
    if hy:
        q = hy['quadrant']
        if q in ('Q1', 'Q2'):
            hy_status = '안정' if q == 'Q2' else '회복 중'
        elif q == 'Q3':
            hy_status = '주의'
        else:
            hy_status = '위험'
        lines.append(f'  부도위험(HY) {hy["hy_spread"]:.2f}% — {hy_status}')

    if vix:
        v = vix['vix_current']
        pct_text = _pct_label(vix['vix_pct'])
        lines.append(f'  공포지수(VIX) {v:.1f} — {pct_text}')

    if kr:
        lines.append(f'  한국신용(BBB-) {kr["spread"]:.1f}%p — {kr["regime_label"]}')

    # VKOSPI 괴리 플래그 (Phase 2: fetch_vkospi_data 구현 후 활성화)
    # vkospi = credit.get('vkospi')
    # if vkospi and vix and vkospi['divergent']:
    #     lines.append(f'  ⚠️ VKOSPI {vkospi["value"]:.1f} {vkospi["slope"]} '
    #                  f'— 한국 변동성 독자 확대')

    return lines


def get_market_pick_level(credit_status: dict) -> dict:
    """시장 위험 상태에 따른 추천 종목 수 결정

    _synthesize_action이 반환한 action_max_picks를 직접 사용.
    종목 레벨 매도(Death List)와 별개로, 시스템 레벨에서 추천을 제한.

    Returns:
        dict: {'max_picks': int, 'label': str, 'warning': str or None}
    """
    max_picks = credit_status.get('action_max_picks', 5)
    action = credit_status.get('final_action', '')

    if max_picks == 0:
        if '매도 검토' in action:
            return {'max_picks': 0, 'label': '매도 검토',
                    'warning': '⚠️ 시장 위험으로 매수를 중단합니다. 보유 종목 매도를 검토하세요.'}
        elif '관망' in action:
            return {'max_picks': 0, 'label': '관망',
                    'warning': '시장 불확실성으로 관망합니다.'}
        else:
            return {'max_picks': 0, 'label': '매수 중단',
                    'warning': '⚠️ 시장 위험으로 신규 매수를 중단합니다.'}
    elif max_picks == 3:
        return {'max_picks': 3, 'label': '축소', 'warning': None}
    else:
        return {'max_picks': 5, 'label': '정상', 'warning': None}


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
    pick_level = get_market_pick_level(result)
    print(f"\n추천 레벨: {pick_level}")
    print("\n" + "=" * 50)
    print("[텔레그램 압축 포맷 v64]")
    for line in format_credit_compact(result):
        print(line)
