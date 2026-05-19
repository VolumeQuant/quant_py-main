"""국면 판단 모듈 — KP_MA250_8d (v80.9, 2026-05-16)

v80.9 전략:
  공격: V15Q0G55M30, 3f rev+oca+gp_growth(0.4/0.4/0.2), 12m, E3X6S5, sl-10%, tr-8%
  방어: V35Q15G15M35, 2f rev+oca(0.8/0.2), 6m-1m, E5X8S5, sl-10%, tr-8%
  국면: KOSPI > MA250 8일 확인 → 공격, 미만 → 방어
  계절성 패널티: SEASONALITY_FORMULA=curr, PENALTY=0.3, RATIO=1.4

진화:
  v80 (04-18): MA170 8d, 2f rev+oca, E3X6S3, tr-15%
  v80.6 (05-13): MA250 8d, slots 5, tr-8%, V35M35 (defense)
  v80.6.1 (05-15): boost G 3팩터 (rev+oca+gp_growth_z 0.4/0.4/0.2)
  v80.7 (05-16): 계절성 패널티 (Q2+Q4/Q1+Q3>1.4 시 G×0.5)
  v80.8 (05-16): bi 양방향 + 매매조건 (entry 2→3, ts_cd 2→1)
  v80.9 (05-16 저녁): curr 복귀 + defense E4→8 / S4→5 (사용자 통찰 보호)
  2026-05-17: jump>2.0 AND revcv>0.7 안전망 (Cal +0.274), wr PENALTY 50 통일

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


MA_PERIOD = 220                 # v80.11 (2026-05-18): MA250→220 (Cal +0.206, WF CV -22%, 약세장 min 1.94)

def check_regime_signal(kospi_close=None, kospi_ma=None, kospi_ma200=None, **kwargs):
    """KP_MA250 (v80.6): KOSPI > 250일 이동평균 = boost

    kospi_close: KOSPI 종가
    kospi_ma: KOSPI MA(MA_PERIOD)일 이동평균
    kospi_ma200: 호환용 (v79 이전 코드)
    """
    ma_val = kospi_ma if kospi_ma is not None else kospi_ma200
    if kospi_close is not None and ma_val is not None:
        return 'boost' if kospi_close > ma_val else 'defense'
    return 'defense'


# v80 파라미터
CONFIRM_DAYS = 10               # v80.14 (2026-05-19): 8→10 (7년 BT Cal 2.474→2.664 +0.19, MDD -1.5%p, 전환 39→35회, whipsaw -3.5%p)


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
            'ENTRY_RANK': 3, 'EXIT_RANK': 6, 'MAX_SLOTS': 5,  # v80.8: entry 2→3
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
            'ENTRY_RANK': 5, 'EXIT_RANK': 8, 'MAX_SLOTS': 5,  # v80.9: exit 4→8, slots 4→5 (인접 CV 0.035, WF min 0.96)
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
