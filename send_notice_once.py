"""고객 공지 1회 전송 — 개인봇 + 채널"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'C:\\dev')
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PRIVATE_ID
from send_telegram_auto import send_telegram_long

notice = '''<b>AI 종목 브리핑 KR</b> — 전략 업그레이드 안내
━━━━━━━━━━━━━━━

<b>왜 바꿨나?</b>
기존 전략은 시장 상황과 관계없이 동일한 방식으로 종목을 선정했습니다. 상승장과 하락장에서 유효한 전략이 다르다는 분석 결과를 바탕으로, 시장 국면에 따라 자동으로 전략을 전환하는 방식으로 업그레이드했습니다.

━━━━━━━━━━━━━━━
📊 <b>과거 성과</b> (2021~2026, 5년 백테스트)

 · 연평균 수익률(CAGR): +187%
 · 최대 낙폭(MDD): -27%
 · 수익/위험 비율(Calmar): 6.9
 · 위험조정 수익(Sharpe): 2.53
 · 같은 기간 코스피: 연 +13%

※ 과거 성과이며 미래를 보장하지 않습니다.

━━━━━━━━━━━━━━━
📋 <b>두 가지 모드</b>

<b>공격 모드</b> — 시장 상승기
 · 성장(Growth) 60% + 추세(Momentum) 20%
 · 가치(Value) 15% + 수익성(Quality) 5%
 · 최대 3종목 집중 투자

<b>방어 모드</b> — 시장 하락/횡보기
 · 추세(Momentum) 50% + 성장(Growth) 25%
 · 가치(Value) 15% + 수익성(Quality) 10%
 · 최대 5종목 분산 투자

━━━━━━━━━━━━━━━
📌 <b>전환 기준</b>

 · KOSPI가 200일 이동평균을 기준으로 판단
 · 5거래일 연속 상회 → 공격, 하회 → 방어
 · 전환 빈도: 연 약 3회
 · 전환 시 기존 종목 전량 매도 후 재진입

━━━━━━━━━━━━━━━
📌 <b>매매 규칙</b>

 · 매수: 3일 연속 종합 상위 5위 이내 (✅)
 · 매도: 가중순위 8위 밖 이탈
 · 손절: 매수가 대비 -10%
 · 트레일링 스톱: 고점 대비 -15%
 · 보유: 공격 최대 3종목 / 방어 최대 5종목

━━━━━━━━━━━━━━━
📌 <b>현재 상태</b> (4/3 장 기준)

 · 공격 모드 진행 중
 · 오늘부터 장 마감 후 브리핑 발송'''

# 채널 + 개인봇 모두 전송
for target, name in [(TELEGRAM_CHAT_ID, '채널'), (TELEGRAM_PRIVATE_ID, '개인봇')]:
    results = send_telegram_long(notice, TELEGRAM_BOT_TOKEN, target)
    codes = [str(r.status_code) for r in results]
    print(f'{name}: {", ".join(codes)}')
