"""고객 공지 1회 전송 — 개인봇 + 채널"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'C:\\dev')
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PRIVATE_ID
from send_telegram_auto import send_telegram_long

notice = """📡 <b>AI 종목 브리핑 KR — 운영 안내</b>

시장 국면에 따라 전략을 자동 전환합니다.
KOSPI 200일선 기준으로 공격/방어 모드 결정.

━━━━━━━━━━━━━━━
📊 <b>7년 백테스트 (2019~2026)</b>
━━━━━━━━━━━━━━━
CAGR        +62%
MDD         -25%
Calmar      2.51
코스피      연 +13% 수준

━━━━━━━━━━━━━━━
📈 <b>공격 모드</b> — KOSPI > MA200
━━━━━━━━━━━━━━━
팩터: Growth 55 / Momentum 30 / Value 15

매수: 3일 연속 ✅ 상위 3종목 (최대 5종목)
매도 (셋 중 하나):
• 3일 가중순위 6위 밖
• 매수가 대비 -10%
• 최고가 대비 -8%

━━━━━━━━━━━━━━━
📉 <b>방어 모드</b> — KOSPI &lt; MA200
━━━━━━━━━━━━━━━
팩터: Momentum 35 / Value 35 / Quality 15 / Growth 15

매수: 3일 연속 ✅ 상위 5종목 (최대 5종목)
매도 (셋 중 하나):
• 3일 가중순위 8위 밖
• 매수가 대비 -10%
• 최고가 대비 -8%

━━━━━━━━━━━━━━━
📌 <b>전환 기준</b>
━━━━━━━━━━━━━━━
KOSPI 200일선 위/아래 10거래일 연속 확인 후 전환.
7년 평균 연 5회 전환.
전환 시 보유 전량 정리 → 새 모드 기준으로 재진입.

━━━━━━━━━━━━━━━
현재: <b>공격 모드</b>
매일 장 마감 후 발송.

분할매수 권장 (1차 50% + 다음날 추가)
자동매매 X — 매수/매도/손절은 본인 실행
종목 선별 기준이며, 비중은 본인 판단
투자 손실 책임은 본인에게 있습니다."""

for target, name in [(TELEGRAM_CHAT_ID, '채널'), (TELEGRAM_PRIVATE_ID, '개인봇')]:
    results = send_telegram_long(notice, TELEGRAM_BOT_TOKEN, target)
    codes = [str(r.status_code) for r in results]
    print(f'{name}: {", ".join(codes)}')
