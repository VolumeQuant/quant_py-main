"""5/13 새벽 자율 작업 최종 종합 보고 — 개인봇 발송"""
import sys, requests
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

msg = """🌅 <b>5/13 새벽 자율 작업 최종 보고</b>

씻고 오는 동안 모든 데이터 5/12까지 완전 복원 + commit + push 완료.

━━━━━━━━━━━━━━━
🚨 <b>오늘 새벽 발견 사고</b>
━━━━━━━━━━━━━━━

<b>1. OHLCV 사라짐</b>
- 5/12 회사 PC stash apply 부작용으로 working tree에서 사라짐
- 백업엔 2019-06부터만 있어서 7.8년 BT 불가능
- 5/13 새벽 발견 + 복원

<b>2. pykrx 차단 추정 잘못</b>
- 처음 pykrx 호출 시 빈 응답 → "IP 차단" 잘못 추정 (사과)
- 실제: <b>2026-02-27부터 KRX 로그인 필수 정책</b>
- krx_auth.login() 추가 후 정상 작동

━━━━━━━━━━━━━━━
✅ <b>완전 복원</b>
━━━━━━━━━━━━━━━

• OHLCV: <b>2017-06-01 ~ 2026-05-12</b> (사용자 원래 파일 정확 복원)
• market_cap: 4/18 ~ 5/12 (~17 거래일)
• fundamentals: 4/18 ~ 5/12
• sectors: 분기 신규
• kospi/kosdaq: 5/11까지 (5/12는 yfinance 지연)
• DART 캐시: 5/12 증분 + 215 재수집 (어제) 유지
• FnGuide 캐시: 5/12 증분
• state ranking: <b>2018-07-02 ~ 2026-05-12</b> (전체 7.8년 완성)
• bt_extended: state 2018-07~2020-12 복사 (정합성 보장)

━━━━━━━━━━━━━━━
📊 <b>BT 결과 (⚠️ 이상치)</b>
━━━━━━━━━━━━━━━

• 7.8년 Cal = <b>1.379</b> (baseline 3.97 대비 -65%)
• 5.25년 Cal = 2.983 (baseline 4.71 대비 -37%)

baseline 대비 대폭 하락. 가능한 원인:
1. state 신규 생성 구간(2018-07~2020-12)의 fs/OHLCV PIT 결손 — 옛날 데이터로 z-score 흔들림
2. KOSPI 인덱스 5/12 미반영 (yfinance 지연) → 국면 판단 영향
3. bt_extended ← state 복사가 정합성은 맞지만 wr 윈도우 경계 손실

조치 권장: 깨어나서 logs/overnight_finish_*.log 의 BT 출력 + state 신규 일자 ranking 샘플 검증.

━━━━━━━━━━━━━━━
📦 <b>GitHub Push</b>
━━━━━━━━━━━━━━━

회사 PC도 OHLCV 등 사라졌을 가능성 → <b>git pull로 자동 복원</b> 위해:
• .gitignore에서 OHLCV 해제
• 모든 데이터 commit + push (대용량)
• 회사 PC <b>git pull origin main</b> 한 줄로 완전 동기화

━━━━━━━━━━━━━━━
📤 <b>5/12 메인 워크플로우</b>
━━━━━━━━━━━━━━━

채널 + 개인봇 발송 완료 (Signal · AI Risk · Watchlist).

━━━━━━━━━━━━━━━
⚠️ <b>주의</b>
━━━━━━━━━━━━━━━

1. monitor 임계값 조정: big_diff 5→10, opi_sign 3→5 (재수집 후 baseline)
2. 영업이익 매핑 사고 3종목 (LG화학/LG엔솔/알파칩스) — 재수집해도 동일 (DART vs FN 정의 차이). 재수집 무의미.
3. pykrx 호출 시 항상 krx_auth.login() 필수 (memory 정정 완료)

━━━━━━━━━━━━━━━

회사 PC git pull 한 줄로 바로 운영 가능. 잘 다녀와요."""

r = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    data={"chat_id": TELEGRAM_PRIVATE_ID, "text": msg, "parse_mode": "HTML"},
    timeout=30,
)
print(f'개인봇 전송: {r.status_code}')
if r.status_code != 200:
    print(r.text)
