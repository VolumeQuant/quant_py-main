"""국면 판단 모듈 — KP_MA170_8d (v80, 2026-04-18)

v80 전략:
  공격: V15Q0G55M30, 2f rev+oca(0.6/0.4), 12m, E3X6S3, sl-10%, tr-15%
  방어: V30Q15G15M40, 2f rev+oca(0.7/0.3), 6m-1m, E3X6S5, sl-10%, tr-15%
  국면: KOSPI > MA170 8일 확인 → 공격, 미만 → 방어

변경사항 (v79 → v80, 2026-04-18):
  - 국면: MA200 7d → MA170 8d (352조합 국면 탐색, 5지표 공정비교+촘촘탐색)
  - 공격 G서브: 3f(rev+oca+gp, 0.5/0.3/0.2) → 2f(rev+oca, 0.6/0.4) — gp_growth 제거
  - 공격 Q: 5→0 (Growth에 집중)
  - 공격 G: 50→55
  - 방어 S: 7→5 (슬롯 축소)
  - 잠정실적 PIT 호환: 2f(매출+영업이익만) → PIT 위반 없음

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


MA_PERIOD = 170                 # v80: MA170 (v79: MA200)

def check_regime_signal(kospi_close=None, kospi_ma=None, kospi_ma200=None, **kwargs):
    """KP_MA170: KOSPI > 170일 이동평균 = boost

    kospi_close: KOSPI 종가
    kospi_ma: KOSPI MA(MA_PERIOD)일 이동평균
    kospi_ma200: 호환용 (v79 이전 코드)
    """
    ma_val = kospi_ma if kospi_ma is not None else kospi_ma200
    if kospi_close is not None and ma_val is not None:
        return 'boost' if kospi_close > ma_val else 'defense'
    return 'defense'


# v80 파라미터
CONFIRM_DAYS = 8                # KP_MA170_8d (v79: MA200 7d)


def get_current_regime(kospi_close=None, kospi_ma200=None, kospi_ma=None, date_str=None, **kwargs):
    """현재 국면 판단 (KP_MA150_10d).

    Args:
        kospi_close: KOSPI 종가
        kospi_ma200: KOSPI 200일 이동평균
        date_str: 날짜 (YYYYMMDD)

    Returns:
        dict: mode, signal, streak, switched, prev_mode
        mode는 'boost'/'defense' 중 하나 (v79: cash 모드 제거).
    """
    state = _load_state()
    prev_mode = state['mode']

    # 당일 신호 (boost/defense)
    signal = check_regime_signal(kospi_close=kospi_close, kospi_ma=kospi_ma, kospi_ma200=kospi_ma200)

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
        # v79에서 제거되었지만 기존 호출처 호환 유지 (항상 False)
        'crash_active': False,
        'crash_entered': False,
        'crash_exited': False,
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
            'G_REV': 0.6,                   # 2팩터 rev 비중 60% (v79: 3팩터 → 2팩터)
            'G_SUB1': 'rev_z',
            'G_SUB2': 'oca_z',
            'G_SUB3': None,                 # v80: 2팩터 (gp_growth 제거)
            'G_W1': None, 'G_W2': None, 'G_W3': None,
            'MOM_PERIOD': '12m',
            'ENTRY_RANK': 3, 'EXIT_RANK': 6, 'MAX_SLOTS': 3,
            'STOP_LOSS': -0.10,             # v80.2 rollback (2026-05-12): 옵션F만 데이터 BT에서 baseline 우위
            'TRAILING_STOP': -0.15,         # v80.2 rollback (2026-05-12)
            'TS_COOLDOWN': 2,               # v80.1: 트레일링 퇴출 후 2거래일 재진입 금지
            'CORR_THRESHOLD': None,
            'USE_REV_ACCEL': False,
            'label': '공격 모드 (Growth 55%)',
            'icon': '📈',
        }
    else:  # defense
        return {
            'V_W': 0.30, 'Q_W': 0.15, 'G_W': 0.15, 'M_W': 0.40,
            'G_REV': 0.7,                   # 2팩터 rev 비중 70%
            'G_SUB1': 'rev_z',
            'G_SUB2': 'oca_z',
            'G_SUB3': None,                 # 2팩터
            'G_W1': None, 'G_W2': None, 'G_W3': None,
            'MOM_PERIOD': '6m-1m',
            'ENTRY_RANK': 3, 'EXIT_RANK': 6, 'MAX_SLOTS': 5,  # v80: 7→5
            'STOP_LOSS': -0.10,             # v80.2 rollback (2026-05-12)
            'TRAILING_STOP': -0.15,         # v80.2 rollback (2026-05-12)
            'TS_COOLDOWN': 2,               # v80.1: 트레일링 퇴출 후 2거래일 재진입 금지
            'CORR_THRESHOLD': None,
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
