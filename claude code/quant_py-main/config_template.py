"""
퀀트 포트폴리오 설정 파일 템플릿
이 파일을 config.py로 복사한 후 설정값을 입력하세요.

사용법:
1. 이 파일을 config.py로 복사
2. 텔레그램 봇 토큰과 채팅 ID 입력
3. python create_current_portfolio.py 실행
4. python send_telegram_auto.py 실행

텔레그램 봇 설정 방법:
1. @BotFather에게 /newbot 명령 → 봇 토큰 받기
2. 봇에게 아무 메시지 보내기
3. https://api.telegram.org/bot{BOT_TOKEN}/getUpdates 접속
4. 응답에서 "chat":{"id":123456789} 부분의 숫자가 채팅 ID
"""

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # 예: "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"       # 예: "123456789" (채널 ID)
TELEGRAM_PRIVATE_ID = "YOUR_PRIVATE_ID_HERE"  # 예: "123456789" (개인 채팅 ID)

# 유니버스 필터 설정
MIN_MARKET_CAP = 3000       # 최소 시가총액 (억원)
# 거래대금 차등 필터 (코드 내 하드코딩): 대형(1조+)≥50억, 중소형(3000억~1조)≥20억
PER_MAX_LIMIT = 60          # PER 상한 (초과 시 유니버스 제외)
PBR_MAX_LIMIT = 10          # PBR 상한 (초과 시 유니버스 제외)

# 전략 설정
PREFILTER_N = 200           # 마법공식 사전필터 종목 수
N_STOCKS = 30               # 최종 선정 종목 수

# 데이터 수집 설정
MAX_CONCURRENT_REQUESTS = 10  # 최대 동시 요청 수
PYKRX_WORKERS = 10            # pykrx 병렬 워커 수
CACHE_DIR = "data_cache"      # 캐시 디렉토리 경로

# Gemini AI 설정 (AI 리스크 분석용)
# Google AI Studio에서 API 키 발급: https://aistudio.google.com/apikey
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"
