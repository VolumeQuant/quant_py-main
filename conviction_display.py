# -*- coding: utf-8 -*-
"""확신가중 제안 표시 — Signal 메시지 footer용 (2026-06-25).
융합 추적기(conviction_fusion_tracker.py)가 쓴 kr_eps_momentum/fusion_state.json을 읽어 비중제안 렌더.
★네트워크 호출 없음(상태파일만). 킬스위치 FUSION_CONVICTION_DISABLE=1. 실패/없음 시 빈문자열(안전).
★표시 전용 — 매매신호(3종목)·시스템 수익률 불변. 사이징 제안일 뿐, 본인 판단."""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'kr_eps_momentum', 'fusion_state.json')


def get_conviction_weights():
    """매수 후보 종목 옆에 표시할 ticker별 비중 dict. {ticker: {'w':71,'conf':True,'fp':8.0}}.
    킬스위치/실패 시 빈 dict(안전). 매수 후보 라인에 '💡권고비중 NN%' 붙이는 용도."""
    if os.environ.get('FUSION_CONVICTION_DISABLE') == '1':
        return {}
    try:
        if not os.path.exists(STATE):
            return {}
        st = json.load(open(STATE, encoding='utf-8'))
        held = st.get('held') or []
        wpct = st.get('weights_pct') or []
        if not held or len(held) != len(wpct):
            return {}
        out = {}
        for h, w in zip(held, wpct):
            out[h.get('ticker')] = {'w': w, 'conf': bool(h.get('confirmed')), 'fp': h.get('fwd_per')}
        return out
    except Exception:
        return {}
