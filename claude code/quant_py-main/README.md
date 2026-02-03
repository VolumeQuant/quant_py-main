# 한국 주식 퀀트 투자 시스템

KOSPI/KOSDAQ 대상 멀티팩터 퀀트 전략 백테스팅 및 포트폴리오 생성 시스템

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| **전략 A** | 마법공식 (Magic Formula) - 이익수익률 + ROIC |
| **전략 B** | 멀티팩터 - Value(40%) + Quality(40%) + Momentum(20%) |
| **유니버스** | 시가총액 1000억+, 거래대금 30억+, 금융/지주사 제외 |
| **리밸런싱** | 분기별 (3/6/9/12월) |
| **포트폴리오** | 전략별 30종목, 동일비중 |

### 백테스트 성과 (2015-2025)

| 지표 | KOSPI | 전략 A | 전략 B |
|------|-------|--------|--------|
| **CAGR** | 7.58% | **11.98%** | **13.15%** |
| **MDD** | -43.90% | -24.42% | -33.90% |
| **Sharpe** | 0.27 | 0.53 | 0.53 |
| **초과수익** | - | +4.4%p | +5.6%p |

---

## 2. 빠른 시작

```bash
# 1. 패키지 설치
pip install pykrx pandas numpy matplotlib requests beautifulsoup4 lxml pyarrow tqdm aiohttp

# 2. 텔레그램 설정 (선택)
cp config_template.py config.py
# config.py에서 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 설정

# 3. 현재 포트폴리오 생성
python create_current_portfolio.py
# - 캐시 모드: ~15초
# - 전체 수집: ~5-10분 (DART API)

# 4. 일별 모니터링 + 텔레그램 알림
python daily_monitor.py

# 5. 전체 백테스팅 (~15분 소요)
python full_backtest.py
```

---

## 3. 프로젝트 구조

```
quant_py-main/
│
├── [핵심 모듈] ─────────────────────────────────────────────
│   ├── dart_api.py             # OpenDART API 클라이언트 (신규)
│   ├── error_handler.py        # Skip & Log 에러 처리 (신규)
│   ├── fnguide_crawler.py      # FnGuide 컨센서스 크롤링
│   ├── data_collector.py       # pykrx API + 병렬 처리
│   ├── strategy_a_magic.py     # 전략 A: 마법공식
│   ├── strategy_b_multifactor.py # 전략 B: 멀티팩터
│   └── utils.py                # 유틸리티 함수
│
├── [실행 스크립트] ─────────────────────────────────────────
│   ├── create_current_portfolio.py  # 현재 포트폴리오 생성 (메인)
│   ├── daily_monitor.py             # 일별 모니터링 + 텔레그램
│   ├── send_telegram_detailed.py    # 상세 포트폴리오 텔레그램 전송
│   ├── full_backtest.py             # 전체 백테스팅
│   └── generate_report_pdf.py       # PDF 리포트 생성
│
├── [설정] ──────────────────────────────────────────────────
│   ├── config.py                # API키/텔레그램 설정 (gitignore)
│   └── config_template.py       # 설정 템플릿
│
├── [출력 디렉토리] ─────────────────────────────────────────
│   ├── output/                  # 포트폴리오 CSV/리포트
│   ├── backtest_results/        # 백테스트 결과
│   └── daily_reports/           # 일별 분석 JSON/CSV
│
├── [캐시] ──────────────────────────────────────────────────
│   └── data_cache/              # 재무제표/OHLCV parquet 캐시
│
└── [문서] ──────────────────────────────────────────────────
    ├── README.md                # 프로젝트 개요 (이 파일)
    ├── PROJECT_REPORT.md        # 상세 결과 리포트
    └── SESSION_HANDOFF.md       # 개발 히스토리/기술 문서
```

---

## 4. 핵심 모듈 상세

### 4.1 dart_api.py (신규)

OpenDART API를 통한 재무제표 수집 (비동기)

```python
# ═══════════════════════════════════════════════════════════════
# 주요 클래스
# ═══════════════════════════════════════════════════════════════

class DartConfig:
    """DART API 설정"""
    api_key: str              # OpenDART API 키
    cache_dir: Path           # 캐시 디렉토리
    max_concurrent: int = 10  # 동시 요청 수
    timeout: int = 30         # 타임아웃 (초)

class DartApiClient:
    """비동기 OpenDART API 클라이언트"""

    async def get_financial_statement(ticker, year, report_type):
        """단일 재무제표 조회"""

    async def get_financial_statements_batch(tickers, years):
        """배치 재무제표 조회 (병렬)"""

def calculate_ttm(df):
    """TTM (Trailing Twelve Months) 계산"""
    # Flow 항목: 최근 4분기 합산
    # Stock 항목: 최근 분기 값
```

**DART 계정 매핑**:
```
DART API              →  시스템 내부
─────────────────────────────────────
당기순이익(손실)       →  당기순이익
매출액                →  매출액
영업이익(손실)        →  영업이익
자산총계              →  자산
부채총계              →  부채
자본총계              →  자본
```

### 4.2 error_handler.py (신규)

Skip & Log 패턴 에러 처리

```python
# ═══════════════════════════════════════════════════════════════
# 에러 카테고리
# ═══════════════════════════════════════════════════════════════

class ErrorCategory(Enum):
    NETWORK = "network"           # 네트워크 오류
    API_RATE_LIMIT = "rate_limit" # API 호출 제한
    DATA_NOT_FOUND = "not_found"  # 데이터 없음
    PARSE_ERROR = "parse"         # 파싱 실패
    TIMEOUT = "timeout"           # 타임아웃

# ═══════════════════════════════════════════════════════════════
# ErrorTracker 사용법
# ═══════════════════════════════════════════════════════════════

tracker = ErrorTracker(log_dir=Path("logs"))

try:
    data = fetch_data(ticker)
except Exception as e:
    tracker.log_error(ticker, ErrorCategory.NETWORK, "수집 실패", e)
    continue  # Skip & Log - 실패해도 계속 진행

# 작업 완료 후 요약
tracker.print_summary()
tracker.save_error_log()
```

### 4.3 fnguide_crawler.py

FnGuide 컨센서스 크롤링 (재무제표는 DART API로 이전)

```python
# ═══════════════════════════════════════════════════════════════
# 주요 함수 (유지)
# ═══════════════════════════════════════════════════════════════

def get_consensus_data(ticker):
    """
    Forward EPS/PER 컨센서스 수집

    URL: comp.fnguide.com/SVO2/ASP/SVD_Main.asp
    Returns: {forward_eps, forward_per, target_price, analyst_count}
    """

async def get_consensus_batch_async(tickers, delay=0.3, max_concurrent=5):
    """비동기 배치 컨센서스 수집"""

# ═══════════════════════════════════════════════════════════════
# Deprecated 함수 (하위 호환용)
# ═══════════════════════════════════════════════════════════════

def get_all_financial_statements(tickers, use_cache=True):
    """
    [DEPRECATED] DART API 사용 권장
    캐시가 있으면 로드, 없으면 경고
    """
```

### 4.4 data_collector.py

pykrx API 래퍼 + 병렬 처리

```python
# ═══════════════════════════════════════════════════════════════
# 병렬 처리 메서드 (신규)
# ═══════════════════════════════════════════════════════════════

def get_ohlcv_parallel(tickers, start_date, end_date):
    """
    ThreadPoolExecutor로 OHLCV 병렬 수집

    Args:
        tickers: 종목코드 리스트
        start_date, end_date: 기간

    Returns:
        DataFrame: 종목별 종가 피벗 테이블

    캐시: data_cache/all_ohlcv_{start}_{end}.parquet
    """

def get_ticker_names_parallel(tickers):
    """종목명 병렬 수집"""

def get_market_cap_batch(date, markets=['KOSPI', 'KOSDAQ']):
    """
    KOSPI/KOSDAQ 통합 시가총액 조회

    Returns:
        DataFrame: 시가총액, 거래대금, 섹터 정보
    """

def filter_universe(market_cap_df, min_market_cap=1000, min_trading_value=50):
    """
    유니버스 필터링

    조건:
    - 시가총액 >= 1000억원
    - 거래대금 >= 50억원
    - 금융업/지주사 제외
    """
```

### 4.5 strategy_a_magic.py

마법공식 (Magic Formula) 전략

```python
# ═══════════════════════════════════════════════════════════════
# 핵심 지표 계산
# ═══════════════════════════════════════════════════════════════

이익수익률 = EBIT / EV
# EBIT = 영업이익
# EV = 시가총액 + 총부채 - 현금

투하자본수익률 = EBIT / Invested Capital
# IC = 자본 + 유동부채 - 현금 - 유동자산

마법공식_순위 = rank(이익수익률) + rank(ROIC)
# 상위 30종목 선정
```

### 4.6 strategy_b_multifactor.py

멀티팩터 전략

```python
# ═══════════════════════════════════════════════════════════════
# 팩터 구성
# ═══════════════════════════════════════════════════════════════

FACTOR_WEIGHTS = {
    'value': 0.40,      # PER, PBR, PCR, PSR 역수
    'quality': 0.40,    # ROE, GPA, CFO/Assets
    'momentum': 0.20    # 12개월 수익률 (최근 1개월 제외)
}

멀티팩터_점수 = Value*0.4 + Quality*0.4 + Momentum*0.2
# 상위 30종목 선정
```

### 4.7 daily_monitor.py

일별 모니터링 시스템 v6.4

```python
# ═══════════════════════════════════════════════════════════════
# Quality(맛) + Price(값) 2축 점수 시스템
# ═══════════════════════════════════════════════════════════════

Quality Score (펀더멘털 매력도):
- 전략등급 25% | PER 25% | ROE 20% | 회복여력 15% | MA정배열 15%

Price Score (진입 타이밍):
- RSI 30% | 볼린저 20% | 거래량 20% | 이격도 15% | 52주위치 15%

# ═══════════════════════════════════════════════════════════════
# 4분류 시스템
# ═══════════════════════════════════════════════════════════════

🚀 STRONG_MOMENTUM: 신고가 + 거래량 + RSI 70-80 → 추세매수
🛡️ DIP_BUYING: 급락 + 지지선 + RSI < 50 → 저점매수
🟡 WAIT_OBSERVE: 양호 / 타이밍 대기 → 관망
🚫 NO_ENTRY: 버블 / 과열 / 저품질 → 금지
```

---

## 5. 데이터 흐름도

```
┌─────────────────────────────────────────────────────────────────┐
│                        데이터 수집                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  pykrx API                 OpenDART API           FnGuide       │
│  ┌─────────────┐          ┌─────────────┐     ┌──────────────┐  │
│  │ 시가총액    │          │ 재무제표    │     │ 컨센서스     │  │
│  │ OHLCV      │          │ (연간/분기) │     │ Forward EPS  │  │
│  │ 기본지표    │          │ TTM 계산    │     │ Forward PER  │  │
│  └──────┬──────┘          └──────┬──────┘     └──────┬───────┘  │
│         │                        │                   │          │
│         └────────────────┬───────┴───────────────────┘          │
│                          │                                      │
│                          ▼                                      │
│                   ┌─────────────┐                               │
│                   │  유니버스   │                               │
│                   │  (~608개)   │                               │
│                   │ 시총1000억+ │                               │
│                   │ 거래50억+   │                               │
│                   └──────┬──────┘                               │
│                          │                                      │
└──────────────────────────┼──────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                          │     전략 실행                         │
├──────────────────────────┼──────────────────────────────────────┤
│                          │                                      │
│           ┌──────────────┴──────────────┐                       │
│           │                             │                       │
│           ▼                             ▼                       │
│    ┌─────────────┐               ┌─────────────┐                │
│    │  전략 A     │               │  전략 B     │                │
│    │ (마법공식)  │               │ (멀티팩터)  │                │
│    │             │               │             │                │
│    │ 이익수익률  │               │ Value 40%   │                │
│    │ + ROIC     │               │ Quality 40% │                │
│    │             │               │ Momentum 20%│                │
│    └──────┬──────┘               └──────┬──────┘                │
│           │                             │                       │
│           ▼                             ▼                       │
│    ┌─────────────┐               ┌─────────────┐                │
│    │  30종목     │               │  30종목     │                │
│    └──────┬──────┘               └──────┬──────┘                │
│           │                             │                       │
│           └──────────────┬──────────────┘                       │
│                          │                                      │
│                          ▼                                      │
│                   ┌─────────────┐                               │
│                   │ 공통 종목   │                               │
│                   │  (~8개)     │                               │
│                   └─────────────┘                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. 설정 파일

### config.py (gitignore)

```python
# 텔레그램 설정
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"

# Git 자동 푸시
GIT_AUTO_PUSH = True

# OpenDART API 설정
DART_API_KEY = "your_dart_api_key"

# 동시 요청 수 설정
MAX_CONCURRENT_REQUESTS = 10  # DART API
PYKRX_WORKERS = 10            # pykrx 병렬 처리

# 유니버스 필터
MIN_MARKET_CAP = 1000   # 최소 시가총액 (억원)
MIN_TRADING_VALUE = 50  # 최소 거래대금 (억원)

# 진입 점수 임계값
SCORE_BUY = 0.6    # 매수 적기 기준
SCORE_WATCH = 0.3  # 관망 기준
```

---

## 7. 성능 개선

### 리팩토링 전후 비교

| 단계 | 리팩토링 전 | 리팩토링 후 |
|------|------------|------------|
| 시가총액 수집 | ~30초 | ~30초 |
| 종목명 수집 | ~2분 (순차) | ~30초 (병렬) |
| 재무제표 수집 | ~50분 (FnGuide 크롤링) | ~2분 (DART API) |
| OHLCV 수집 | ~4분 (순차) | ~1분 (병렬) |
| **총 소요시간** | **~50분** | **~5분** |
| **캐시 모드** | - | **~15초** |

### 개선 사항

1. **OpenDART API 도입**: FnGuide 크롤링 → 공식 API (빠르고 안정적)
2. **비동기 처리**: asyncio + aiohttp로 동시 요청
3. **병렬 처리**: ThreadPoolExecutor로 OHLCV/종목명 수집
4. **Skip & Log 패턴**: 실패해도 중단 없이 진행, 에러 로깅

---

## 8. 기술 스택

| 패키지 | 버전 | 용도 |
|--------|------|------|
| **pykrx** | 1.2.3 | 한국 주식 데이터 API |
| **aiohttp** | 3.9+ | 비동기 HTTP 요청 |
| **pandas** | 2.2+ | 데이터 처리 |
| **numpy** | 2.1+ | 수치 연산 |
| **requests** | 2.32+ | HTTP 요청 |
| **beautifulsoup4** | 4.12+ | HTML 파싱 |
| **pyarrow** | - | parquet 캐시 |

---

## 9. 주의사항

1. **DART API 키**: https://opendart.fss.or.kr/ 에서 발급 (무료, 일 10,000건)
2. **API 호출 제한**: 과도한 요청 시 IP 차단 가능
3. **캐시 활용**: 재수집 불필요 시 캐시 모드 사용 권장
4. **FnGuide 크롤링**: 컨센서스만 사용 (재무제표는 DART API로 이전)
5. **백테스트 한계**:
   - 생존 편향 (상장폐지 종목 미포함)
   - 거래비용 단순화 (0.3% 고정)
   - 슬리피지 미반영

---

## 10. 라이선스

MIT License

---

*버전: 3.0 | 최종 업데이트: 2026-02-03 | Generated by Claude Code*
