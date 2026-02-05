"""
일별 모니터링 설정 파일 템플릿
이 파일을 config.py로 복사한 후 설정값을 입력하세요.

사용법:
1. 이 파일을 config.py로 복사
2. 텔레그램 봇 토큰과 채팅 ID 입력
3. daily_monitor.py 실행

텔레그램 봇 설정 방법:
1. @BotFather에게 /newbot 명령 → 봇 토큰 받기
2. 봇에게 아무 메시지 보내기
3. https://api.telegram.org/bot{BOT_TOKEN}/getUpdates 접속
4. 응답에서 "chat":{"id":123456789} 부분의 숫자가 채팅 ID
"""

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # 예: "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"       # 예: "123456789"

# Git 설정
GIT_AUTO_PUSH = True  # 자동 커밋/푸시 활성화
