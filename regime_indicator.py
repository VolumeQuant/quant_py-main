"""국면 판단 모듈 — B126_40 (시총1000억+ 126일+ 종목 MA120 위 비율 ≥40%) 기반, 1일 확인

v75 확정: KP120_3d+VIX25 (KOSPI>MA120 3일확인 + VIX<25)
  방어: V20 Q10 G20 M50, g_rev=0.6, mom=6m-1m, E5 X8 S7, sl=-10%, trail=-15%, corr=0.6
  공격: V25 Q0 G50 M25, g_rev=0.3, mom=12m-1m, E3 X4 S7, trail=-20%

사용:
    from regime_indicator import get_current_regime
    regime = get_current_regime()  # 'boost' or 'defense'
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


def check_regime_signal(kospi_close=None, kospi_ma120=None,
                        vix=None, breadth_ratio=None,
                        kospi_ma60=None, kosdaq_close=None, kosdaq_ma60=None):
    """KP120 + VIX25: KOSPI > MA120 AND VIX < 25 = boost

    Primary: kospi_close > kospi_ma120 AND vix < 25
    Fallback: breadth_ratio >= 0.40
    """
    if kospi_close is not None and kospi_ma120 is not None and vix is not None:
        if kospi_close > kospi_ma120 and vix < 25:
            return 'boost'
        return 'defense'
    if breadth_ratio is not None:
        return 'boost' if breadth_ratio >= 0.40 else 'defense'
    if (kospi_close is not None and kospi_ma60 is not None and
        kosdaq_close is not None and kosdaq_ma60 is not None):
        if kospi_close >= kospi_ma60 and kosdaq_close >= kosdaq_ma60:
            return 'boost'
    return 'defense'


def get_current_regime(kospi_close=None, kospi_ma120=None,
                        vix=None, breadth_ratio=None,
                        kospi_ma60=None, kosdaq_close=None, kosdaq_ma60=None,
                        date_str=None):
    """현재 국면 판단 (3일 확인, KP120+VIX25 기반).

    Args:
        kospi_close: KOSPI 종가
        kospi_ma120: KOSPI MA120
        vix: VIX 지수
        breadth_ratio: fallback용 브레스 비율
        date_str: 날짜 (YYYYMMDD)

    Returns:
        dict: mode, signal, streak, switched, prev_mode
    """
    state = _load_state()
    prev_mode = state['mode']

    # 당일 신호
    signal = check_regime_signal(kospi_close=kospi_close, kospi_ma120=kospi_ma120,
                                  vix=vix, breadth_ratio=breadth_ratio,
                                  kospi_ma60=kospi_ma60, kosdaq_close=kosdaq_close,
                                  kosdaq_ma60=kosdaq_ma60)

    # 연속 카운트
    if signal == state['streak_mode']:
        state['streak'] += 1
    else:
        state['streak'] = 1
        state['streak_mode'] = signal

    # 1일 확인 (v75: 즉시 전환)
    CONFIRM_DAYS = 3  # v75 확정: KP120_3d (3일 확인)
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
            'V_W': 0.25, 'Q_W': 0.00, 'G_W': 0.50, 'M_W': 0.25,
            'G_REV': 0.3,
            'MOM_PERIOD': '12m-1m',
            'ENTRY_RANK': 3, 'EXIT_RANK': 4, 'MAX_SLOTS': 7,
            'STOP_LOSS': None,
            'TRAILING_STOP': -0.20,
            'CORR_THRESHOLD': None,
            'USE_REV_ACCEL': False,
            'label': '공격 모드 (Growth+매출 중심)',
            'icon': '⚔️',
        }
    else:  # v75 방어 (defense)
        return {
            'V_W': 0.20, 'Q_W': 0.10, 'G_W': 0.20, 'M_W': 0.50,
            'G_REV': 0.6,
            'MOM_PERIOD': '6m-1m',
            'ENTRY_RANK': 5, 'EXIT_RANK': 8, 'MAX_SLOTS': 7,
            'STOP_LOSS': -0.10,
            'TRAILING_STOP': -0.15,
            'CORR_THRESHOLD': 0.6,
            'USE_REV_ACCEL': False,
            'label': '방어 모드 (Momentum+분산)',
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
