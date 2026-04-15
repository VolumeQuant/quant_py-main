"""방금 채널에 잘못 보낸 최근 메시지 삭제 시도"""
import sys, requests
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# getUpdates로 최근 메시지 ID 알 수 없음 (이건 webhook용)
# deleteMessage는 message_id 필요한데 우리가 방금 보낸 건 응답 저장 안 함

# 대신 현재 채널 최신 메시지들 (봇이 보낸)을 삭제 시도
# 방법: 최근 30개 메시지 ID 범위를 시도 (너무 크면 rate limit)

# 안전한 방법: getChat으로 확인 후 수동 삭제 or 추정
# 대안: 봇 API는 메시지 ID 없이 삭제 못함

# 현재 텔레그램 API 제약상 우리가 방금 보낸 메시지 ID를 모르면 삭제 불가
# 가장 최근 채널 메시지 ID 추정: getMessages 권한 필요 (채널 멤버)

# 차선책: 채널에 사과 메시지 전송하여 공지 철회 알림

def send(text):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    r = requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'text': text, 'parse_mode': 'HTML'})
    return r

# 바로 앞 3개 메시지를 무효화한다는 공지
notice = '\n'.join([
    '⚠️ <b>관리자 공지 — 직전 3개 메시지 무효</b>',
    '',
    '━━━━━━━━━━━━━━━',
    '방금 전송된 다음 3개 메시지는 테스트 중 실수로 전송됐습니다. <b>무시해 주세요.</b>',
    '',
    '• "v77.1 → v79 업데이트" 공지',
    '• "방어 모드 → 공격 모드 전환" 샘플',
    '• "공격 모드 → 방어 모드 전환" 샘플',
    '━━━━━━━━━━━━━━━',
    '',
    '• 현재 실제 국면은 <b>공격 모드 유지 중</b>이며, 모드 전환은 아직 발생하지 않았습니다.',
    '• 전략 v79 전환은 내부 검증 단계이며, 정식 공지는 별도로 안내드릴 예정입니다.',
    '',
    '혼란을 드려 죄송합니다.',
])

r = send(notice)
print(f'무효 공지 전송: {r.status_code}')
print(r.text[:300])
