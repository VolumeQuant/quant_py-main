"""국면 판단 모듈 — KP_MA200_10d (v80.15, 2026-05-19)

v80.15 전략:
  공격: V15Q0G55M30, 3f rev+oca+gp_growth(0.4/0.4/0.2), 12m, E3X6S5, sl-10%, tr-8%
  방어: V35Q15G15M35, 2f rev+oca(0.8/0.2), 6m-1m, E5X8S5, sl-10%, tr-8%
  국면: KOSPI > MA200 10일 확인 → 공격, 미만 → 방어 (v80.15: MA220→200 OOS robust)
  계절성 패널티: SEASONALITY_FORMULA=curr, PENALTY=0.3, RATIO=1.4
  QoQ 패널티 (D6, v80.12): boost + KOSPI>MA220×1.06 시 op_qoq<+20% → G×0.7
  wr 가중치 (v80.13): T-0×0.4 + T-1×0.35 + T-2×0.25 (당일 비중 ↓, 3일 검증 강화)

진화:
  v80 (04-18): MA170 8d, 2f rev+oca, E3X6S3, tr-15%
  v80.6 (05-13): MA250 8d, slots 5, tr-8%, V35M35 (defense)
  v80.6.1 (05-15): boost G 3팩터 (rev+oca+gp_growth_z 0.4/0.4/0.2)
  v80.7 (05-16): 계절성 패널티 (Q2+Q4/Q1+Q3>1.4 시 G×0.5)
  v80.8 (05-16): bi 양방향 + 매매조건 (entry 2→3, ts_cd 2→1)
  v80.9 (05-16 저녁): curr 복귀 + defense E4→8 / S4→5 (사용자 통찰 보호)
  v80.10 (05-17): 진정 가속 면제 (min/max 4Q > 0.2)
  v80.11 (05-18): MA250→220 (Cal +0.21, WF CV -22%)
  v80.12 (05-18): QoQ 패널티 D6 + SG6 강한 boost (Cal +29%, MDD -6%p)
  v80.13 (05-18): wr 가중치 50:30:20 → 40:35:25 (Cal +17%, 노이즈 매수 차단)
  v80.14 (05-19): regime CONFIRM_DAYS 8→10 (Cal +0.19, 전환 39→35, whipsaw -3.5%p)
  v80.15 (05-19): regime MA220→200 (OOS robust — 220 cherry-pick 의심 해소, 표준값)
  v80.16 (05-24): defense ENTRY 5→0 (cash 100%, 약세장 한계 인정)
  v80.17 (05-25): boost EXIT 6→4, MAX_SLOTS 5→4
  v80.18 (05-25): regime MA200 → MA20/MA80 cross (5d), Cal +43%, WFmin +1.66
  v80.19 (05-27): boost MAX_SLOTS 4→3 (자율주행 검증, Cal +22%, 현실 알파 +0.30)

사용:
    from regime_indicator import get_current_regime
    regime = get_current_regime(kospi_close=5377, kospi_ma200=5200)
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
STATE_DIR = Path(__file__).parent / 'state'
REGIME_STATE_FILE = STATE_DIR / 'regime_state.json'


def _load_state():
    """국면 상태 로드. 없으면 기본값(defense)."""
    if REGIME_STATE_FILE.exists():
        try:
            with open(REGIME_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        'mode': 'defense',
        'streak': 0,
        'streak_mode': 'defense',
        'last_date': None,
        'history': [],
    }


def _save_state(state):
    STATE_DIR.mkdir(exist_ok=True)
    with open(REGIME_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


MA_PERIOD = 200                 # 호환용 (v80.18에서 cross로 변경, 옛 코드 유지)
SHORT_MA = 20                   # v80.18 (2026-05-25): MA cross 도입 (단기 MA)
LONG_MA = 80                    # v80.18: 장기 MA
CONFIRM_DAYS = 5                # v80.18: MA cross 적합 confirm (옛 10일은 단순 MA용)


def check_regime_signal(kospi_close=None, kospi_ma=None, kospi_ma200=None,
                         kospi_short_ma=None, kospi_long_ma=None, **kwargs):
    """KP_MA_CROSS (v80.18): KOSPI MA20 > MA80 = boost

    v80.18 (2026-05-25): 단순 MA200 → MA cross 변경
    BT: Cal 2.601 → 3.233 (+24%), MDD 22.16% (거의 동일), 2022 약세장 +11% (단순 MA는 0%)
    Whipsaw: 7년 17회 전환 (단순 MA200 13회 대비 +4회만, 안정성 양호)

    우선순위: kospi_short_ma/long_ma > kospi_close/ma (호환)
    """
    # 신규: MA cross (v80.18)
    if kospi_short_ma is not None and kospi_long_ma is not None:
        return 'boost' if kospi_short_ma > kospi_long_ma else 'defense'
    # 호환: 단순 MA 비교 (옛 v80.15)
    ma_val = kospi_ma if kospi_ma is not None else kospi_ma200
    if kospi_close is not None and ma_val is not None:
        return 'boost' if kospi_close > ma_val else 'defense'
    return 'defense'


def get_current_regime(kospi_close=None, kospi_ma200=None, kospi_ma=None,
                        kospi_short_ma=None, kospi_long_ma=None,
                        date_str=None, **kwargs):
    """현재 국면 판단 (KP_MA_CROSS, v80.18).

    Args:
        kospi_short_ma: KOSPI MA20 (v80.18 신규)
        kospi_long_ma: KOSPI MA80 (v80.18 신규)
        kospi_close, kospi_ma, kospi_ma200: 호환용 (옛 v80.15)
        date_str: 날짜 (YYYYMMDD)

    Returns:
        dict: mode, signal, streak, switched, prev_mode
        mode는 'boost'/'defense' 중 하나 (v79: cash 모드 제거).
    """
    state = _load_state()
    prev_mode = state['mode']

    # 당일 신호 (boost/defense) — v80.18: MA cross 우선
    signal = check_regime_signal(kospi_close=kospi_close, kospi_ma=kospi_ma, kospi_ma200=kospi_ma200,
                                  kospi_short_ma=kospi_short_ma, kospi_long_ma=kospi_long_ma)

    # 연속 카운트
    if signal == state['streak_mode']:
        state['streak'] += 1
    else:
        state['streak'] = 1
        state['streak_mode'] = signal

    switched = False
    if state['streak'] >= CONFIRM_DAYS and state['mode'] != signal:
        state['mode'] = signal
        switched = True

    final_mode = state['mode']

    # 히스토리 추가
    if date_str:
        state['last_date'] = date_str
        state['history'].append({
            'date': date_str,
            'signal': signal,
            'mode': state['mode'],
            'switched': switched,
        })
        # 최근 30일만 보관
        state['history'] = state['history'][-30:]

    _save_state(state)

    return {
        'mode': final_mode,  # 'boost' / 'defense'
        'underlying_mode': state['mode'],
        'signal': signal,
        'streak': state['streak'],
        'switched': switched,
        'prev_mode': prev_mode,
    }


def get_regime_params(mode):
    """국면에 따른 전략 파라미터 반환 (v80).

    mode: 'boost' / 'defense'

    Returns:
        dict: V_W, Q_W, G_W, M_W, G_REV, ENTRY_RANK, EXIT_RANK, MAX_SLOTS
    """
    if mode == 'boost':
        return {
            'V_W': 0.15, 'Q_W': 0.00, 'G_W': 0.55, 'M_W': 0.30,
            'G_REV': 0.5,                   # 2팩터 폴백 (3팩터 모드에선 미사용)
            'G_SUB1': 'rev_z',
            'G_SUB2': 'oca_z',
            'G_SUB3': 'gp_growth_z',        # v80.6.1 (2026-05-15): 3팩터 도입
            'G_W1': 0.4, 'G_W2': 0.4, 'G_W3': 0.2,  # rev/oca/gp_growth 비율
            'MOM_PERIOD': '12m',
            # v80.17 (2026-05-25): EXIT_RANK 6→4, MAX_SLOTS 5→4
            # v80.19 (2026-05-27): MAX_SLOTS 4→3 (자율주행 검증)
            # 7년 BT: Cal 1.991 → 2.432 (+22%), OOS 3.23→4.17 (+29%)
            # 현실 알파 (slippage 0.1+0.3%): 1.169 → 1.474 (+0.305)
            # 매도 -12% (486→425), WFmin +0.15 (1.45→1.60)
            # 약세장 22-23 -0.75 (boost 단기 진입 시 단일종목 손실 ↑)
            # → defense cash 100% + 손절 -10%로 보호
            'ENTRY_RANK': 3, 'EXIT_RANK': 4, 'MAX_SLOTS': 3,
            'STOP_LOSS': -0.10,
            'TRAILING_STOP': -0.08,
            'TS_COOLDOWN': 1,                                  # v80.8: 2→1
            'USE_REV_ACCEL': False,
            # v80.12 (2026-05-18): QoQ 패널티 + 강한 boost (SG6)
            # 강한 boost (KOSPI > MA220 × 1.06) 일 때 영업이익 QoQ < +20% 종목 G × 0.7
            # 7년 BT: Cal 1.846 → 2.374 (+29%), MDD 33%→27%, 2020-21 회복기 +52%
            'G_QOQ_PENALTY': 'D6',
            'G_QOQ_PENALTY_THRESHOLD': 20,
            'G_QOQ_PENALTY_MULTIPLIER': 0.7,
            'G_QOQ_SG6_THRESH': 0.06,
            'label': '공격 모드 (Growth 55%, 3팩터, QoQ-D6-SG6)',
            'icon': '📈',
        }
    else:  # defense
        return {
            'V_W': 0.35, 'Q_W': 0.15, 'G_W': 0.15, 'M_W': 0.35,  # v80.6: V 0.30→0.35, M 0.40→0.35
            'G_REV': 0.8,                   # v80.6: 0.7→0.8 (rev 비중↑)
            'G_SUB1': 'rev_z',
            'G_SUB2': 'oca_z',
            'G_SUB3': None,
            'G_W1': None, 'G_W2': None, 'G_W3': None,
            'MOM_PERIOD': '6m-1m',
            # v80.16 (2026-05-24): defense ENTRY_RANK 5 → 0 (cash 100%)
            # 7년 BT: Cal 1.797→2.261 (+26%), MDD 33→21% (-12%p), IS/OOS 둘 다 우월
            # 약세장 (22-23) -0.04 → +0.72 대전환
            # 메커니즘: defense 거래 785건 평균 +0.5% (boost +4.6%의 1/10), 알파 거의 X
            # 약세장은 시스템 한계 인정 → 매수 안 하고 cash 보유가 정답
            'ENTRY_RANK': 0, 'EXIT_RANK': 8, 'MAX_SLOTS': 5,
            'STOP_LOSS': -0.10,
            'TRAILING_STOP': -0.08,
            'TS_COOLDOWN': 1,
            'USE_REV_ACCEL': False,
            'label': '방어 모드 (Momentum 40%)',
            'icon': '📉',
        }


if __name__ == '__main__':
    # 테스트
    sys.stdout.reconfigure(encoding='utf-8')
    result = get_current_regime(
        kospi_close=5967, kospi_ma=4172,
        date_str='20260418'
    )
    print(f"모드: {result['mode']}")
    print(f"신호: {result['signal']}")
    print(f"연속: {result['streak']}일")
    print(f"전환: {result['switched']}")

    params = get_regime_params(result['mode'])
    print(f"\n파라미터: V={params['V_W']} Q={params['Q_W']} G={params['G_W']} M={params['M_W']}")
    print(f"G_SUB: {params['G_SUB1']}/{params['G_SUB2']}/{params['G_SUB3']}")
    print(f"MOM: {params['MOM_PERIOD']}")
    print(f"E/X/S: {params['ENTRY_RANK']}/{params['EXIT_RANK']}/{params['MAX_SLOTS']}")
