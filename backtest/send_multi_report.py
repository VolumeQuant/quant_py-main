"""multi-constraint 결과 → 개인봇만"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

msg = """🏆 multi-constraint 그리드 완료

━━━━━━━━━━━━━━━
📊 baseline vs new BEST
━━━━━━━━━━━━━━━

         baseline   new BEST
7.8y:    1.854      1.142 (-38%)
wf_min:  -0.122     0.71 (양수)
WF CV:   1.98       0.34
2018H2:  0.03       0.71
2020:    -0.05      2.18
2022:    0.46       1.68
2024:    0.51       1.84

━━━━━━━━━━━━━━━
🎯 trade-off
━━━━━━━━━━━━━━━

✅ 시기별 안정성 큰 개선
   - 모든 시기 양수 Cal
   - WF CV 1.98 → 0.34 (83% 개선)
   - 어떤 시기도 망하지 않음

❌ 통합 Cal 양보
   - 7.8y 1.85 → 1.14 (-38%)

━━━━━━━━━━━━━━━
🔧 new BEST 파라미터
━━━━━━━━━━━━━━━

⚙️ 국면: MA250 8d (170→250)

🔥 Boost:
   V10 Q0 G60 M30
   oca_z + gp_growth_z (rev_z 빠짐)
   g_rev 0.7
   mom 6m-1m (12m 아님)

🛡️ Defense:
   V30 Q10 G15 M45
   rev_z + oca_z
   g_rev 0.7, mom 6m-1m

🎰 진입/슬롯:
   Boost: rank≤2, exit>5, slot 2
   Defense: rank≤3, exit>6, slot 3

🛑 손절: -20%, 트레일링 -15%, 쿨다운 5일

━━━━━━━━━━━━━━━
⚠️ production 채택 결정 필요
━━━━━━━━━━━━━━━

(A) 현재 v80 유지
   → 강세장 강함 (Cal 1.85)
   → 약세장 위험 (wf_min 음수)

(B) new BEST 채택
   → 안정성 큼 (모든 시기 양수)
   → 강세장 양보 (Cal 1.14)

이건 trade-off. 사용자 판단 영역."""

# 텔레그램 4096 분할
chunks = []
while len(msg) > 4000:
    cut = msg[:4000].rfind('\n')
    if cut == -1: cut = 4000
    chunks.append(msg[:cut])
    msg = msg[cut:]
chunks.append(msg)

for i, c in enumerate(chunks, 1):
    prefix = f'[{i}/{len(chunks)}]\n' if len(chunks)>1 else ''
    r = requests.post(
        f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': prefix + c},
        timeout=30
    )
    print(f'  {i}/{len(chunks)}: {r.status_code}')
print('완료 (개인봇만)')
