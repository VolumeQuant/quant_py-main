"""국면 판단 모듈 — KP_MA200_5d + Crash Cash (v77.1, 2026-04-14)

v77 기본 전략:
  공격: V5Q0G65M30, 3f rev+oca+gp(0.5/0.3/0.2), 12m-1m, E7X8S3, sl-10%, tr-15%
  방어: V30Q5G10M55, 2f raccel+opm(0.5), 6m-1m, E3X6S7, sl-10%, tr-15%
  국면: KOSPI > MA200 5일 확인 → 공격, 미만 → 방어

v77.1 Crash Cash (2026-04-14 추가):
  방어 모드 중 KOSPI 20일 수익률 < -20% 발동 시 → 전량 청산(현금)
  조건 해제 시 방어 모드 자동 재진입
  배경: COVID 급락 구간 방어로도 손실 큼 → BT 7.8년 Cal 1.35→1.50 개선

사용:
    from regime_indicator import get_current_regime
    regime = get_current_regime(kospi_close=5377, kospi_ma200=5200, kospi_ret20=-0.05)
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
    """국면 상태 로드. 없으면 기본값(cal3)."""
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
        'crash_active': False,  # v77.1: 현재 크래시 현금 상태인지
    }


def _save_state(state):
    STATE_DIR.mkdir(exist_ok=True)
    with open(REGIME_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_regime_signal(kospi_close=None, kospi_ma200=None, **kwargs):
    """KP_MA200: KOSPI > 200일 이동평균 = boost

    kospi_close: KOSPI 종가
    kospi_ma200: KOSPI 200일 이동평균
    """
    if kospi_close is not None and kospi_ma200 is not None:
        return 'boost' if kospi_close > kospi_ma200 else 'defense'
    return 'defense'


# v77.1 Crash Cash 파라미터
CRASH_RET20_THRESHOLD = -0.20  # KOSPI 20일 수익률 < -20% → 현금 전환
CONFIRM_DAYS = 5                # KP_MA200_5d


def check_crash_cash(kospi_ret20):
    """v77.1: KOSPI 20일 수익률 급락 체크

    Args:
        kospi_ret20: KOSPI 20일 수익률 (예: -0.25 = -25%)

    Returns:
        bool: True이면 크래시 현금 전환 신호
    """
    if kospi_ret20 is None:
        return False
    try:
        return float(kospi_ret20) < CRASH_RET20_THRESHOLD
    except (TypeError, ValueError):
        return False


def get_current_regime(kospi_close=None, kospi_ma200=None, date_str=None,
                       kospi_ret20=None, **kwargs):
    """현재 국면 판단 (KP_MA200_5d + Crash Cash).

    Args:
        kospi_close: KOSPI 종가
        kospi_ma200: KOSPI 200일 이동평균
        date_str: 날짜 (YYYYMMDD)
        kospi_ret20: KOSPI 20일 수익률 (v77.1 크래시 체크용, None이면 체크 스킵)

    Returns:
        dict: mode, signal, streak, switched, prev_mode, crash_active
        mode는 'boost'/'defense'/'cash' 중 하나.
        'cash'는 defense 상태 + 크래시 조건 발동 시에만 반환 (state['mode']는 defense로 유지).
    """
    state = _load_state()
    prev_mode_full = 'cash' if state.get('crash_active') else state['mode']

    # 당일 신호 (boost/defense)
    signal = check_regime_signal(kospi_close=kospi_close, kospi_ma200=kospi_ma200)

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

    # v77.1 크래시 현금 체크: defense 모드에서만 적용
    crash_signal = check_crash_cash(kospi_ret20)
    prev_crash = state.get('crash_active', False)
    # 공격(boost) 모드에서는 crash_active 자동 해제
    if state['mode'] == 'boost':
        state['crash_active'] = False
    else:  # defense
        state['crash_active'] = crash_signal

    crash_entered = (not prev_crash) and state['crash_active']
    crash_exited = prev_crash and (not state['crash_active'])

    # 최종 반환 mode
    if state['mode'] == 'defense' and state['crash_active']:
        final_mode = 'cash'
    else:
        final_mode = state['mode']

    # 히스토리 추가
    if date_str:
        state['last_date'] = date_str
        state['history'].append({
            'date': date_str,
            'signal': signal,
            'mode': state['mode'],
            'final_mode': final_mode,
            'switched': switched,
            'crash_active': state['crash_active'],
            'kospi_ret20': round(float(kospi_ret20), 4) if kospi_ret20 is not None else None,
        })
        # 최근 30일만 보관
        state['history'] = state['history'][-30:]

    _save_state(state)

    return {
        'mode': final_mode,  # 'boost' / 'defense' / 'cash'
        'underlying_mode': state['mode'],  # 'boost' / 'defense'
        'signal': signal,
        'streak': state['streak'],
        'switched': switched,  # boost↔defense 전환
        'crash_active': state['crash_active'],
        'crash_entered': crash_entered,
        'crash_exited': crash_exited,
        'prev_mode': prev_mode_full,
    }


def get_regime_params(mode):
    """국면에 따른 전략 파라미터 반환.

    mode: 'boost' / 'defense' / 'cash'

    Returns:
        dict: V_W, Q_W, G_W, M_W, G_REV, ENTRY_RANK, EXIT_RANK, MAX_SLOTS, USE_REV_ACCEL
        cash 모드는 MAX_SLOTS=0 (매수 없음, 전량 청산 상태 유지)
    """
    if mode == 'cash':
        return {
            'V_W': 0.0, 'Q_W': 0.0, 'G_W': 0.0, 'M_W': 0.0,
            'G_REV': 0.0,
            'G_SUB1': None, 'G_SUB2': None, 'G_SUB3': None,
            'G_W1': None, 'G_W2': None, 'G_W3': None,
            'MOM_PERIOD': '6m-1m',
            'ENTRY_RANK': 0, 'EXIT_RANK': 0, 'MAX_SLOTS': 0,  # 매수 없음
            'STOP_LOSS': None,
            'TRAILING_STOP': None,
            'CORR_THRESHOLD': None,
            'USE_REV_ACCEL': False,
            'label': '현금 도피 (KOSPI 급락)',
            'icon': '💵',
        }
    if mode == 'boost':
        return {
            'V_W': 0.05, 'Q_W': 0.00, 'G_W': 0.65, 'M_W': 0.30,
            'G_REV': 0.0,  # 3팩터 사용 시 무시됨
            'G_SUB1': 'rev_z',
            'G_SUB2': 'oca_z',
            'G_SUB3': 'gp_growth_z',       # 3팩터: 매출성장+영업이익변화+매출총이익성장
            'G_W1': 0.5, 'G_W2': 0.3, 'G_W3': 0.2,
            'MOM_PERIOD': '12m-1m',
            'ENTRY_RANK': 7, 'EXIT_RANK': 8, 'MAX_SLOTS': 3,
            'STOP_LOSS': -0.10,
            'TRAILING_STOP': -0.15,
            'CORR_THRESHOLD': None,
            'USE_REV_ACCEL': False,
            'label': '공격 모드 (Growth 65%)',
            'icon': '📈',
        }
    else:  # v77 방어 (defense)
        return {
            'V_W': 0.30, 'Q_W': 0.05, 'G_W': 0.10, 'M_W': 0.55,
            'G_REV': 0.5,
            'G_SUB1': 'rev_accel_z',       # 매출가속도 50%
            'G_SUB2': 'op_margin_z',       # 이익률변화 50%
            'G_SUB3': None,                # 2팩터
            'G_W1': None, 'G_W2': None, 'G_W3': None,
            'MOM_PERIOD': '6m-1m',
            'ENTRY_RANK': 3, 'EXIT_RANK': 6, 'MAX_SLOTS': 7,
            'STOP_LOSS': -0.10,
            'TRAILING_STOP': -0.15,
            'CORR_THRESHOLD': None,
            'USE_REV_ACCEL': False,
            'label': '방어 모드 (Momentum 55%)',
            'icon': '📉',
        }


if __name__ == '__main__':
    # 테스트
    sys.stdout.reconfigure(encoding='utf-8')
    result = get_current_regime(
        kospi_close=5377, kospi_ma60=5318,
        kosdaq_close=1100, kosdaq_ma60=1050,
        date_str='20260403'
    )
    print(f"모드: {result['mode']}")
    print(f"신호: {result['signal']}")
    print(f"연속: {result['streak']}일")
    print(f"전환: {result['switched']}")

    params = get_regime_params(result['mode'])
    print(f"\n파라미터: {params}")
