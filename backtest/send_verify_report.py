"""검증 결과 → 개인봇만"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

msg = """🚨 그리드 BEST 검증 결과 — OVERFITTING 발견

━━━━━━━━━━━━━━━
⚠️ 시기별 안정성 (WF)
━━━━━━━━━━━━━━━

2018H2-19: Cal 0.073 ❌ (CAGR 2.4%만)
2020-21:   Cal 0.919
2022-23:   Cal 0.788
2024-26:   Cal 2.074 ✅

→ CV 0.745 (목표 <0.3) WARN
→ 최근 시기에만 강함 = overfitting

━━━━━━━━━━━━━━━
🔻 5.25y vs 7.8y 모순
━━━━━━━━━━━━━━━

7.8y BT:  Cal 3.275
5.25y BT: Cal 1.601 ⚠️

5.25y가 더 짧은데 더 낮음 = 정상 아님
→ 옛 시기(2018H2) 노이즈에 fit

━━━━━━━━━━━━━━━
📊 baseline vs new BEST
━━━━━━━━━━━━━━━

         baseline  new BEST
8년 Cal:  1.854    3.455 (+86%)
7.8y:     1.787    3.275
5.25y:    3.673    1.601 (-56%) ⚠️

→ baseline이 5.25y에서 2배 이상 좋음
→ new BEST = 8년 통합 점수만 좋음

━━━━━━━━━━━━━━━
✅ 인접 안정성 (통과)
━━━━━━━━━━━━━━━

국면 ±1: CV 0.068 PASS
SL/TS ±5%: CV 0.204 PASS

━━━━━━━━━━━━━━━
🏁 결론
━━━━━━━━━━━━━━━

new BEST (Cal 3.455)는 함정
→ 옛 시기 약세장(2018H2-19, 2022-23) 매우 약함
→ 2024-26 강세에 의존

▶ production은 현재 v80 유지가 안전

진정한 best 찾으려면:
- WF CV<0.3 통과
- 5.25y/7.8y 양쪽 좋음
- 인접 안정 동시 만족
- 추가 grid 필요"""

r = requests.post(
    f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
    data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg},
    timeout=30
)
print(f'발송: {r.status_code}')
