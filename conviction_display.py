# -*- coding: utf-8 -*-
"""확신가중 제안 표시 — Signal 메시지 footer용 (2026-06-25).
융합 추적기(conviction_fusion_tracker.py)가 쓴 kr_eps_momentum/fusion_state.json을 읽어 비중제안 렌더.
★네트워크 호출 없음(상태파일만). 킬스위치 FUSION_CONVICTION_DISABLE=1. 실패/없음 시 빈문자열(안전).
★표시 전용 — 매매신호(3종목)·시스템 수익률 불변. 사이징 제안일 뿐, 본인 판단."""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, 'kr_eps_momentum', 'fusion_state.json')


def build_conviction_line():
    if os.environ.get('FUSION_CONVICTION_DISABLE') == '1':
        return ''
    try:
        if not os.path.exists(STATE):
            return ''
        st = json.load(open(STATE, encoding='utf-8'))
        held = st.get('held') or []
        wpct = st.get('weights_pct') or []
        if not held or len(held) != len(wpct):
            return ''
        cw = st.get('cw', 3.0)
        tags = []
        for h in held:
            g = h.get('grow')
            if h.get('confirmed'):
                gtxt = f"+{(g - 1) * 100:.0f}%" if g else ''
                tags.append(f"{h.get('name', '?')[:8]} ✅{gtxt}")
            else:
                tags.append(f"{h.get('name', '?')[:8]} —")
        wline = ' / '.join(f"{w:.0f}%" for w in wpct)
        lines = [
            '━━━━━━━━━━━━━━━',
            '💡 확신가중 제안 (선행성장 이중확인 → 비중↑)',
            ' · '.join(tags),
            f'권고 비중: {wline}',
            f'※ 시장 기대성장(컨센) 상위 확인종목 ×{cw:.0f} 제안 · 검증 누적중 · 사이징은 본인 판단',
        ]
        return '\n'.join(lines)
    except Exception:
        return ''
