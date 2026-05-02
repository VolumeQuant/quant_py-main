# config.py 템플릿
# ─────────────────────────────────────────────────────────────
# 사용법:
#   1) 이 파일을 config.py 로 복사
#        cp config.example.py config.py
#   2) 아래 <...> 자리에 본인 실제 값 입력
#   3) config.py 는 .gitignore 에 등록되어 있어 커밋되지 않음
# ─────────────────────────────────────────────────────────────

# 텔레그램 설정
TELEGRAM_BOT_TOKEN = "<BotFather 발급 봇 토큰, 예: 1234567890:AAH...>"
TELEGRAM_CHAT_ID = "<채널 chat_id, -100으로 시작하는 음수, 예: -1001234567890>"
TELEGRAM_PRIVATE_ID = "<본인 텔레그램 user_id (양의 정수)>"

# 동시 요청 수 설정
MAX_CONCURRENT_REQUESTS = 10  # 동시 요청
PYKRX_WORKERS = 10            # pykrx 병렬 처리 워커

# 캐시 설정
CACHE_DIR = "data_cache"

# 유니버스 필터 설정
MIN_MARKET_CAP = 3000         # 최소 시가총액 (억원)
PER_MAX_LIMIT = 60
PBR_MAX_LIMIT = 10

# 포트폴리오 설정
PREFILTER_N = 200             # Strategy A 사전 필터 수
N_STOCKS = 30                 # 최종 선정 종목 수

# Gemini AI 설정 (Google AI Studio)
GEMINI_API_KEY = "<Gemini API 키>"

# FRED API (HY Spread, VIX 안정적 수집)
FRED_API_KEY = "<FRED API 키>"

# 한국은행 ECOS API (BBB- 회사채 스프레드)
ECOS_API_KEY = "<ECOS API 키>"

# OpenDART API (과거 재무제표, 무료 — 일일 쿼터 분산용 트리플 키)
DART_API_KEY = "<OpenDART API 키 1>"
DART_API_KEY_2 = "<OpenDART API 키 2>"
DART_API_KEY_3 = "<OpenDART API 키 3>"
DART_API_KEYS = [DART_API_KEY, DART_API_KEY_2, DART_API_KEY_3]  # 트리플 키 (일일 57,000건)

# KRX 데이터 시스템 로그인 (2026-02-27~ 필수)
KRX_USER_ID = "<KRX 데이터시스템 ID>"
KRX_PASSWORD = "<KRX 데이터시스템 비밀번호>"
