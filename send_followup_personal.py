# -*- coding: utf-8 -*-
import sys, requests
sys.path.insert(0, '.')
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

msg = """✅ <b>자율 후속 확인까지 끝냈어요 (집 가시는 동안)</b>

방금 보고 드린 진단을 <b>여러 방법으로 교차검증</b>했고, 다음부터 헛경보를 안 울리게 할 <b>개선안도 미리 만들어 뒀어요.</b> (적용은 안 했어요 — 안전 관련이라 오시면 같이 결정하려고요.)

<b>1) 교차검증 결과 (다 일치)</b>
• 필터 하나씩 꺼보는 실험으로 확인: 종목이 준 진짜 범인은 <b>MA120(상승추세) 필터</b> = 시장 급락 탓. 데이터 필터(capped 등)는 무관.
• 가격바 존재 종목수: 정상일 2,877~2,882개인데 오늘도 <b>2,877개(정상)</b>. 데이터 멀쩡 재확인.
• 흥미로운 발견: 지난 5/28 수집사고 때도 KR 가격바는 멀쩡했어요 → 그래서 개선안엔 "가격 + 재무 <b>둘 다</b>" 보게 넣었어요.

<b>2) 만들어 둔 것</b>
• 사건 기록(메모리) 저장 ✅
• 개선안 문서 <code>PROPOSAL_safetynet_breadth_vs_data.md</code>: 안전망을 "데이터 건강도"와 "최종 종목수" <b>2단계로 분리</b> → 진짜 수집사고만 막고, 시장 급락엔 헛경보 안 울림.
• 검증용 분석 스크립트들 정리 ✅, 임시 폴더 청소 ✅

<b>3) 지금 상태</b>
• 오늘 채널 발송: <b>보류 그대로</b> (제가 임의로 안 보냈어요)
• 오늘 순위 데이터: <b>정상·유효</b>
• 국면: 아직 <b>공격(boost)</b> — 오늘 급락에도 방어 전환 전. 지켜볼 점.

더 건드리면 시스템 안전·전략에 영향 가는 부분이라 여기서 멈췄어요. 오시면 ① 오늘 채널 보낼지 ② 개선안 적용할지 같이 정해요. 푹 쉬세요! 🙌"""

r = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    data={"chat_id": TELEGRAM_PRIVATE_ID, "text": msg, "parse_mode": "HTML"},
    timeout=30,
)
print(f"개인봇 후속 전송: {r.status_code} ok={r.ok}")
if not r.ok: print(r.text[:400])
