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
            g = h.get('grow'); fp = h.get('fwd_per')
            # fwd_per 신호등: <20 싸서 잘오름 🟢 / 20~25 🟡 / >25 비쌈 🔴
            if fp is None:
                fptxt = ''
            elif fp < 20:
                fptxt = f" 🟢fwPER{fp:.0f}"
            elif fp < 25:
                fptxt = f" 🟡fwPER{fp:.0f}"
            else:
                fptxt = f" 🔴fwPER{fp:.0f}"
            if h.get('confirmed'):
                gtxt = f"+{(g - 1) * 100:.0f}%" if g else ''
                tags.append(f"{h.get('name', '?')[:8]} ✅{gtxt}{fptxt}")
            else:
                tags.append(f"{h.get('name', '?')[:8]} —{fptxt}")
        wline = ' / '.join(f"{w:.0f}%" for w in wpct)
        gate = st.get('fwd_per_gate', 20)
        lines = [
            '━━━━━━━━━━━━━━━',
            f'💡 확신가중 제안 (선행PER<{gate:.0f} 자격 → 기대성장 비례 비중)',
            ' · '.join(tags),
            f'권고 비중: {wline}',
            f'※ 선행PER<{gate:.0f}(미래기준 쌈)이 자격, 기대성장 강할수록↑(최대 ×{cw:.0f}) · 검증중 · 사이징 본인판단',
        ]
        return '\n'.join(lines)
    except Exception:
        return ''
