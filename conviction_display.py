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
        gate = st.get('fwd_per_gate', 20)
        # ★비중을 누가 봐도 명확히: "종목 ▶ NN%" 큼직하게, 부가정보는 뒤에
        rows = []
        for h, w in zip(held, wpct):
            g = h.get('grow'); fp = h.get('fwd_per'); nm = h.get('name', '?')[:10]
            if fp is None:
                fptxt = '선행PER 없음'
            elif fp < gate:
                fptxt = f'🟢선행PER{fp:.0f}'
            elif fp < gate + 5:
                fptxt = f'🟡선행PER{fp:.0f}'
            else:
                fptxt = f'🔴선행PER{fp:.0f}'
            if h.get('confirmed'):
                gtxt = f"자격✅ 기대성장+{(g - 1) * 100:.0f}%" if g else '자격✅'
            else:
                gtxt = '자격미달'
            rows.append(f"  {nm} ▶ {w:.0f}%   ({gtxt}·{fptxt})")
        lines = [
            '━━━━━━━━━━━━━━━',
            '💡 확신가중 비중 제안 (합 100%, 표시 전용)',
        ] + rows + [
            f'※ 선행PER<{gate:.0f}(미래기준 쌈)=자격, 기대성장 강할수록 비중↑(최대 ×{cw:.0f}배)',
            '※ 매매신호·시스템 수익률 불변 · 검증 누적중 · 사이징은 본인 판단',
        ]
        return '\n'.join(lines)
    except Exception:
        return ''
