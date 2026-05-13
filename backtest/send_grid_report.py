"""그리드 결과 → 개인봇만 발송 (채널 절대 X)"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

msg = """🎯 그리드서치 결과 (옵션3 전부)

📅 BT 기간: 2018-07~2026-05 (8년)
🛡️ 안전망: 이격도20 1.5
📊 데이터: state 재생성 + fs_dart 215+3종목 정정 후

━━━━━━━━━━━━━━━
📊 단계별 best (Cal 누적 개선)
━━━━━━━━━━━━━━━

🟢 baseline (현재 v80): Cal 1.854

1️⃣ 국면 (MA × 확인일수):
   현재 MA170 8d → MA170 10d
   Cal 1.854 → 1.920 (+0.07)

2️⃣ Boost V/Q/G/M:
   현재 V15Q0G55M30 → V20Q0G50M30
   Cal 1.920 → 1.940 (+0.02, 거의 동일)

3️⃣ Defense V/Q/G/M:
   현재 V30Q15G15M40 → V30Q15G10M45
   Cal 1.940 → 2.288 (+0.35) ⭐
   → G축소 + 모멘텀확대 효과

4️⃣ G_SUB + MOM:
   현재 g_rev 0.6 → g_rev 0.5
   Cal 2.288 → 2.437 (+0.15)

5️⃣ 진입/이탈/슬롯:
   현재 boost slot 3, defense slot 5
   → boost slot 2 (집중), defense slot 7 (분산)
   Cal 2.437 → 2.727 (+0.29) ⭐

6️⃣ 손절/이익실현 (SL/TS):
   현재 SL-10% TS-15% cd2일
   → SL-20% TS-15% cd1일
   Cal 2.727 → 3.455 (+0.73) ⭐⭐
   → 손절 -10% → -20% 완화 (whipsaw 회피)
   → 쿨다운 2일 → 1일

━━━━━━━━━━━━━━━
🏆 최종 BEST 파라미터
━━━━━━━━━━━━━━━

⚙️ 국면: KP_MA170_10d (8일→10일 확인)

🔥 Boost: V20 Q0 G50 M30
🛡️ Defense: V30 Q15 G10 M45

📊 G_SUB: rev_z + oca_z (g_rev=0.5)
📈 모멘텀: 12m (boost), 6m-1m (defense)

🎯 진입/이탈: rank≤3 / WR>6
🎰 슬롯: boost 2, defense 7
🛑 손절: -20%, 트레일링: -15%
⏰ TS 쿨다운: 1일

━━━━━━━━━━━━━━━
📈 성과 비교
━━━━━━━━━━━━━━━

baseline (현재): Cal 1.854
NEW BEST:      Cal 3.455

→ +1.601 개선 (+86%)

━━━━━━━━━━━━━━━
⚠️ 주의 (검증 안 한 것)
━━━━━━━━━━━━━━━

1. WF (구간별) 안정성 미검증
   → 시기별로 일관 좋은지 확인 필요
2. 인접 안정성 미검증
   → 파라미터 약간 변경 시 결과 안정한지
3. 단계적 best 찾기 = local optimum 가능
   → 전체 조합 동시 탐색 시 다른 best 가능

검증 필요 시 별도 진행."""

# 텔레그램 4096자 제한 (분할 발송)
chunks = []
while len(msg) > 4000:
    cut = msg[:4000].rfind('\n')
    if cut == -1: cut = 4000
    chunks.append(msg[:cut])
    msg = msg[cut:]
chunks.append(msg)

for i, c in enumerate(chunks, 1):
    prefix = f'[{i}/{len(chunks)}]\n' if len(chunks) > 1 else ''
    r = requests.post(
        f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
        data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': prefix + c},
        timeout=30
    )
    print(f'  msg {i}/{len(chunks)}: {r.status_code}')

print('발송 완료 (개인봇만)')
