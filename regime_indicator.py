"""국면 판단 모듈 — KOSPI+KOSDAQ MA60 기반, 3일 확인

사용:
    from regime_indicator import get_current_regime
    regime = get_current_regime()  # 'boost' or 'cal3'
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
        'mode': 'cal3',
        'streak': 0,
        'streak_mode': 'cal3',
        'last_date': None,
        'history': [],
    }


def _save_state(state):
    STATE_DIR.mkdir(exist_ok=True)
    with open(REGIME_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_regime_signal(kospi_close, kospi_ma60, kosdaq_close, kosdaq_ma60):
    """KOSPI+KOSDAQ 둘 다 MA60 위면 'boost', 아니면 'cal3'"""
    if (kospi_close is not None and kospi_ma60 is not None and
        kosdaq_close is not None and kosdaq_ma60 is not None):
        if kospi_close >= kospi_ma60 and kosdaq_close >= kosdaq_ma60:
            return 'boost'
    return 'cal3'


def get_current_regime(kospi_close=None, kospi_ma60=None,
                        kosdaq_close=None, kosdaq_ma60=None,
                        date_str=None):
    """현재 국면 판단 (3일 확인).

    Args:
        kospi_close, kospi_ma60, kosdaq_close, kosdaq_ma60: 당일 값
        date_str: 날짜 (YYYYMMDD)

    Returns:
        dict: {
            'mode': 'boost' or 'cal3',
            'signal': 'boost' or 'cal3' (당일 신호, 확인 전),
            'streak': int (연속 일수),
            'switched': bool (오늘 전환되었는지),
            'prev_mode': str (이전 모드),
        }
    """
    state = _load_state()
    prev_mode = state['mode']

    # 당일 신호
    signal = check_regime_signal(kospi_close, kospi_ma60, kosdaq_close, kosdaq_ma60)

    # 연속 카운트
    if signal == state['streak_mode']:
        state['streak'] += 1
    else:
        state['streak'] = 1
        state['streak_mode'] = signal

    # 3일 확인
    switched = False
    if state['streak'] >= 3 and state['mode'] != signal:
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
            'V_W': 0.15, 'Q_W': 0.05, 'G_W': 0.65, 'M_W': 0.15,
            'G_REV': 1.0,
            'ENTRY_RANK': 3, 'EXIT_RANK': 4, 'MAX_SLOTS': 3,
            'USE_REV_ACCEL': False,
            'label': '공격 모드',
            'icon': '⚔️',
        }
    else:  # cal3
        return {
            'V_W': 0.20, 'Q_W': 0.20, 'G_W': 0.45, 'M_W': 0.15,
            'G_REV': 0.1,
            'ENTRY_RANK': 4, 'EXIT_RANK': 10, 'MAX_SLOTS': 5,
            'USE_REV_ACCEL': True,
            'label': '방어 모드',
            'icon': '🛡️',
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
