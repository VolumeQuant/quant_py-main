"""국면 판단 모듈 — KP_MA200_5d (KOSPI > 200일선, 5일 확인)

v77 확정:
  공격: V5Q0G65M30, 3f rev+oca+gp(0.5/0.3/0.2), 12m-1m, E7X8S3, sl-10%, tr-15%
  방어: V30Q5G10M55, 2f raccel+opm(0.5), 6m-1m, E3X6S7, sl-10%, tr-15%
  국면: KOSPI > MA200 5일 확인 → 공격, 미만 → 방어

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


def get_current_regime(kospi_close=None, kospi_ma200=None, date_str=None, **kwargs):
    """현재 국면 판단 (KP_MA200_5d: KOSPI > MA200, 5일 확인).

    Args:
        kospi_close: KOSPI 종가
        kospi_ma200: KOSPI 200일 이동평균
        date_str: 날짜 (YYYYMMDD)

    Returns:
        dict: mode, signal, streak, switched, prev_mode
    """
    state = _load_state()
    prev_mode = state['mode']

    # 당일 신호
    signal = check_regime_signal(kospi_close=kospi_close, kospi_ma200=kospi_ma200)

    # 연속 카운트
    if signal == state['streak_mode']:
        state['streak'] += 1
    else:
        state['streak'] = 1
        state['streak_mode'] = signal

    # 확인일수만으로 whipsaw 방지 (cooldown 삭제)
    CONFIRM_DAYS = 5  # v76: KP_MA200_5d
    switched = False

    if state['streak'] >= CONFIRM_DAYS and state['mode'] != signal:
        state['mode'] = signal
        switched = True

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
        'mode': state['mode'],
        'signal': signal,
        'streak': state['streak'],
        'switched': switched,
        'prev_mode': prev_mode,
    }


def get_regime_params(mode):
    """국면에 따른 전략 파라미터 반환.

    Returns:
        dict: V_W, Q_W, G_W, M_W, G_REV, ENTRY_RANK, EXIT_RANK, MAX_SLOTS, USE_REV_ACCEL
    """
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
