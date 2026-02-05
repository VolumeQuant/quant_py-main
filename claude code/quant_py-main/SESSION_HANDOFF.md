# 한국 주식 퀀트 포트폴리오 시스템 - 기술 문서

## 문서 개요

**버전**: 6.4
**최종 업데이트**: 2026-02-05
**작성자**: Claude Opus 4.5

---

## 핵심 변경사항 (v3.2 진입점수 개선)

### 2026-02-05 텔레그램 메시지 완전 자동화 + 진입점수 개선

**목표**: "좋은 사과를 싸게 사자" - 할인된 종목 우선

| 변경 항목 | Before | After |
|----------|--------|-------|
| 날짜 | 하드코딩 | **자동 감지 (전일 거래일 기준)** |
| 기술지표 | 수동 입력 | **pykrx 실시간 계산** |
| 선정이유 | 수동 작성 | **데이터 기반 자동 생성** |
| 리스크 | 수동 작성 | **지표 기반 자동 생성** |
| 신고가 돌파 | **보너스 +35점** | **중립 (감점 안 함)** |

**신규 모듈**:
- `send_telegram_auto.py` - 완전 자동화 텔레그램 전송

**날짜 로직**:
```
TODAY = 오늘 날짜 (인사용)
BASE_DATE = 전일 거래일 (분석 기준)
→ 장 시작 전 전일 종가 분석하여 당일 매매 전략 수립
```

**뉴스 자동화** (Google News RSS):
```
크롤링 → 필터링 → 정제 → 표시

필터링 규칙 (시세 뉴스 제외):
- "+X% 상승/하락", "VI 발동"
- "상승폭 확대/축소", "하락폭 확대/축소"
- "주가 X월 X일", "X% 상승 마감"
- "주가.*장중", "장중.*주가"

정제 규칙:
- 종목명 + 조사 제거 (도/는/가/이/을/를/의/에)
- 언론사명, [태그] 제거
- 빈 따옴표(''), 연속 특수문자(··) 정리
- 헤드라인 35자 제한

표시 형식:
📰 주요뉴스: 마스크팩 인기에 1년 새 15배 뛴
📰 주요뉴스: ⚠️삼성전자 HBM4 수율 격차 1.5배… (부정적)

자동화 한계:
- 규칙 기반 필터링 (80~90% 정확도)
- 새로운 패턴의 시세 뉴스는 필터 못 함
- 며칠 사용 후 평가 예정
```

**2단계 전략 시스템**:
```
[1단계] 밸류 - 뭘 살까? (630개 → 8개)
• 유니버스: 거래대금 30억↑ 약 630개
• 전략A 마법공식 30개 ∩ 전략B 멀티팩터 30개

[2단계] 가격 - 언제 살까? (8개 → 순위)
• 진입점수로 정렬 (RSI↓ 52주저점↓ 거래량↑)
```

**진입점수 계산 (100점 만점)** - "싸게 사자" 철학:
```
RSI (40점): 낮을수록 좋음
  - ≤30: 40점 (과매도 - 최고 기회)
  - 31-50: 30점 (양호)
  - 51-70: 20점 (중립)
  - >70 + 신고가돌파: 20점 (감점 안 함)
  - >70 일반: 10점 (과매수 위험)

52주위치 (30점): 할인 클수록 좋음
  - ≤-20%: 30점 (큰 할인)
  - -10~-20%: 25점
  - -5~-10%: 20점
  - 신고가돌파: 15점 (감점 안 함, 보너스도 없음)
  - 기타: 15점

거래량 (20점): 스파이크 확인
  - ≥1.5x: 20점
  - 일반: 10점

기본 (10점): 통과 종목 기본 점수
```

---

## 핵심 변경사항 (v3.0 리팩토링)

### 2026-02-03 대규모 리팩토링

**목표**: 런타임 50분 → 5분 단축

| 변경 항목 | Before | After |
|----------|--------|-------|
| 재무제표 소스 | FnGuide 크롤링 | **OpenDART API** |
| 처리 방식 | 순차 처리 | **비동기 + 병렬** |
| 에러 처리 | print + 무시 | **Skip & Log 패턴** |
| 거래대금 필터 | 10억원 (당일) | **30억원 (20일 평균)** |
| 총 소요시간 | ~50분 | **~35초 (캐시)** |

**신규 모듈**:
- `dart_api.py` - OpenDART API 비동기 클라이언트
- `error_handler.py` - Skip & Log 에러 처리

**수정 모듈**:
- `fnguide_crawler.py` - 재무제표 크롤링 deprecated, 컨센서스만 유지
- `data_collector.py` - 병렬 처리 추가
- `create_current_portfolio.py` - async main() 구조로 전환

---

## 1. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                         데이터 수집 레이어                            │
├─────────────────────────────────────────────────────────────────────┤
│  pykrx API              │  OpenDART API         │  FnGuide          │
│  - 시가총액 (병렬)       │  - 재무제표 (비동기)   │  - 컨센서스       │
│  - OHLCV (병렬)         │  - TTM 계산           │  - Forward EPS    │
│  ThreadPoolExecutor     │  aiohttp + asyncio    │  requests         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         전략 레이어                                   │
├─────────────────────────────────────────────────────────────────────┤
│  Strategy A (마법공식)     │  Strategy B (멀티팩터)                   │
│  - 이익수익률 (EBIT/EV)   │  - Value 40% (PER, PBR, PCR, PSR)       │
│  - 투하자본수익률 (ROC)   │  - Quality 40% (ROE, GPA, CFO)          │
│                          │  - Momentum 20% (12M-1M)                 │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         에러 처리 레이어                              │
├─────────────────────────────────────────────────────────────────────┤
│  ErrorTracker (Skip & Log 패턴)                                      │
│  - ErrorCategory: NETWORK, TIMEOUT, API_RATE_LIMIT, PARSE_ERROR     │
│  - log_error() → 기록 후 continue                                    │
│  - print_summary() → 에러 통계                                       │
│  - save_error_log() → JSON 저장                                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         출력 레이어                                   │
├─────────────────────────────────────────────────────────────────────┤
│  텔레그램 알림 (3개 메시지)  │  CSV/JSON 저장   │  Git 자동 푸시      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 핵심 모듈 상세

### 2.1 dart_api.py (신규, 450줄)

OpenDART API 비동기 클라이언트

#### 주요 클래스

**DartConfig** (35-50줄)
```python
@dataclass
class DartConfig:
    api_key: str                          # OpenDART API 키
    cache_dir: Path = Path("data_cache")  # 캐시 디렉토리
    max_concurrent: int = 10              # 동시 요청 수
    timeout: int = 30                     # 타임아웃 (초)
    retry_count: int = 3                  # 재시도 횟수
    cache_max_age_days: int = 7           # 캐시 유효 기간
```

**DartApiClient** (195-420줄)
```python
class DartApiClient:
    """비동기 OpenDART API 클라이언트"""

    async def __aenter__(self):
        """Context manager - 세션 초기화, 기업코드 로드"""

    async def get_financial_statement(ticker, year, report_type):
        """단일 재무제표 조회"""

    async def get_financial_statements_multi_year(ticker, years):
        """다년도 재무제표 조회 (연간 + 분기)"""

    async def get_financial_statements_batch(tickers, years):
        """배치 재무제표 조회"""
```

**calculate_ttm()** (438-490줄)
```python
def calculate_ttm(df: pd.DataFrame) -> pd.DataFrame:
    """
    TTM (Trailing Twelve Months) 계산

    Flow 항목 (손익/현금): 최근 4분기 합산
    - 매출액, 영업이익, 당기순이익

    Stock 항목 (재무상태): 최근 분기 값
    - 자산, 부채, 자본
    """
```

#### DART 계정 매핑

```python
DART_ACCOUNT_MAPPING = {
    '당기순이익(손실)': '당기순이익',
    '매출액': '매출액',
    '영업이익(손실)': '영업이익',
    '자산총계': '자산',
    '부채총계': '부채',
    '자본총계': '자본',
}
```

---

### 2.2 error_handler.py (신규, 400줄)

Skip & Log 패턴 에러 처리

#### 에러 카테고리

```python
class ErrorCategory(Enum):
    NETWORK = "network"           # 네트워크/연결 오류
    API_RATE_LIMIT = "rate_limit" # API 호출 제한
    DATA_NOT_FOUND = "not_found"  # 데이터 없음
    PARSE_ERROR = "parse"         # 파싱 실패
    VALIDATION = "validation"     # 데이터 검증 실패
    TIMEOUT = "timeout"           # 타임아웃
    UNKNOWN = "unknown"           # 기타
```

#### ErrorTracker 클래스

```python
class ErrorTracker:
    def log_error(ticker, category, message, exception=None):
        """에러 기록 + 실패 종목 추적"""

    def log_warning(ticker, message):
        """경고 기록 (복구 가능)"""

    def mark_success(ticker):
        """성공 시 실패 목록에서 제거"""

    def get_failed_tickers() -> List[str]:
        """실패 종목 목록"""

    def get_summary() -> Dict:
        """에러 통계 요약"""

    def save_error_log(path=None) -> Path:
        """JSON 로그 저장"""
```

#### 사용 예시

```python
tracker = ErrorTracker(log_dir=Path("logs"), name="portfolio")

for ticker in tickers:
    try:
        data = await client.get_financial_statement(ticker)
        tracker.mark_success(ticker)
    except Exception as e:
        tracker.log_error(ticker, ErrorCategory.NETWORK, "수집 실패", e)
        continue  # Skip & Log

tracker.print_summary()
tracker.save_error_log()
```

---

### 2.3 fnguide_crawler.py (수정, 529줄)

**변경사항**: 재무제표 크롤링 deprecated, 컨센서스만 유지

#### 유지 함수

**get_consensus_data()** (372-445줄)
```python
def get_consensus_data(ticker: str) -> Dict:
    """
    Forward EPS/PER 컨센서스 수집

    URL: comp.fnguide.com/SVO2/ASP/SVD_Main.asp
    테이블: tables[7]

    Returns:
        {forward_eps, forward_per, target_price, analyst_count}
    """
```

**get_consensus_batch_async()** (480-529줄)
```python
async def get_consensus_batch_async(
    tickers: List[str],
    delay: float = 0.5,
    max_concurrent: int = 5,
) -> pd.DataFrame:
    """비동기 배치 컨센서스 수집"""
```

#### Deprecated 함수 (하위 호환용)

```python
def get_financial_statement(ticker, use_cache=True):
    """[DEPRECATED] dart_api.DartApiClient 사용 권장"""
    warnings.warn("get_financial_statement()는 deprecated입니다.")
    # 캐시가 있으면 로드, 없으면 빈 DataFrame 반환

def get_all_financial_statements(tickers, use_cache=True):
    """[DEPRECATED] 캐시 전용"""
    # 기존 캐시 파일만 로드
```

---

### 2.4 data_collector.py (수정, 544줄)

**변경사항**: 병렬 처리 메서드 추가

#### 신규 메서드

**get_ohlcv_parallel()** (67-140줄)
```python
def get_ohlcv_parallel(
    self,
    tickers: List[str],
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """
    ThreadPoolExecutor로 OHLCV 병렬 수집

    캐시: data_cache/all_ohlcv_{start}_{end}.parquet
    Workers: self.max_workers (기본 10)
    """
```

**get_ticker_names_parallel()** (142-184줄)
```python
def get_ticker_names_parallel(
    self,
    tickers: List[str],
) -> Dict[str, str]:
    """종목명 병렬 수집"""
```

**get_market_cap_batch()** (186-230줄)
```python
def get_market_cap_batch(
    self,
    date: str,
    markets: List[str] = ['KOSPI', 'KOSDAQ'],
) -> pd.DataFrame:
    """
    KOSPI/KOSDAQ 통합 시가총액 조회

    캐시: data_cache/market_cap_ALL_{date}.parquet
    """
```

**filter_universe()** (232-280줄)
```python
def filter_universe(
    self,
    market_cap_df: pd.DataFrame,
    min_market_cap: int = 1000,    # 억원
    min_trading_value: int = 50,   # 억원
) -> pd.DataFrame:
    """
    유니버스 필터링

    조건:
    - 시가총액 >= 1000억원
    - 거래대금 >= 30억원
    - 금융업/지주사 제외
    """
```

---

### 2.5 create_current_portfolio.py (수정, 525줄)

**변경사항**: async main() 구조로 전환

#### 핵심 함수

**main_async()** (390-513줄)
```python
async def main_async():
    """비동기 메인 함수"""

    # 1. 시가총액 수집
    market_cap_df = collector.get_market_cap_batch(BASE_DATE)

    # 2. 유니버스 필터링
    universe_df, ticker_names = filter_universe_optimized(...)

    # 3. 재무제표 수집 (DART API)
    magic_df = await collect_financial_data_dart(tickers)

    # DART 실패 시 FnGuide 캐시 fallback
    if magic_df.empty:
        magic_df = extract_magic_formula_data(fs_data, use_ttm=True)

    # 4. OHLCV 수집 (병렬)
    price_df = collect_price_data_parallel(...)

    # 5. 전략 실행
    selected_a = await run_strategy_a(magic_df, universe_df)
    selected_b = await run_strategy_b(magic_df, price_df, universe_df)

    # 6. 결과 저장
    ...
```

**main()** (516-520줄)
```python
def main():
    """동기 래퍼 (호환성)"""
    return asyncio.run(main_async())
```

---

## 3. 데이터 흐름

### 포트폴리오 생성 (create_current_portfolio.py)

```
1. pykrx에서 시가총액 조회 (병렬)
   └─ KOSPI + KOSDAQ = 2,774개

2. 유니버스 필터링
   ├─ 시가총액 >= 1000억원 → 1,100개
   ├─ 거래대금 >= 30억원 → 824개
   └─ 금융/지주 제외 → 608개

3. 재무제표 수집
   ├─ DART API 시도 (비동기)
   └─ 실패 시 FnGuide 캐시 fallback

4. TTM 계산
   ├─ Flow: 최근 4분기 합산
   └─ Stock: 최근 분기 값

5. 전략 A 실행 → 30종목
   └─ 이익수익률 + ROC 순위 합산

6. 전략 B 실행 → 30종목
   └─ Value*0.4 + Quality*0.4 + Momentum*0.2

7. 결과 저장
   └─ output/portfolio_strategy_a/b.csv
```

### 일별 모니터링 (daily_monitor.py)

```
1. 포트폴리오 종목 로드 (A+B 합집합)

2. 기술적 지표 계산
   ├─ RSI (14일)
   ├─ 볼린저밴드
   ├─ 이동평균 이격도
   ├─ 52주 고저점 위치
   └─ MA 정배열

3. Quality(맛) + Price(값) 점수 계산

4. 4분류 시스템 적용
   ├─ 🚀 STRONG_MOMENTUM
   ├─ 🛡️ DIP_BUYING
   ├─ 🟡 WAIT_OBSERVE
   └─ 🚫 NO_ENTRY

5. 텔레그램 발송 (3개 메시지)

6. Git 자동 커밋
```

---

## 4. 파일 구조

```
quant_py-main/
├── 핵심 모듈 (신규/수정)
│   ├── dart_api.py           # [NEW] OpenDART API 클라이언트 (450줄)
│   ├── error_handler.py      # [NEW] Skip & Log 에러 처리 (400줄)
│   ├── fnguide_crawler.py    # [MOD] 컨센서스만 유지 (529줄)
│   ├── data_collector.py     # [MOD] 병렬 처리 추가 (544줄)
│   ├── strategy_a_magic.py   # 마법공식 (225줄)
│   └── strategy_b_multifactor.py # 멀티팩터 (341줄)
│
├── 실행 스크립트
│   ├── create_current_portfolio.py  # [MOD] async main() (525줄)
│   ├── daily_monitor.py             # 일별 모니터링 v6.4 (1289줄)
│   └── full_backtest.py             # 백테스트
│
├── 설정
│   ├── config.py                    # API키/텔레그램 (gitignore)
│   └── config_template.py           # 설정 템플릿
│
├── 출력 디렉토리
│   ├── output/                      # 포트폴리오 CSV
│   ├── backtest_results/            # 백테스트 결과
│   └── daily_reports/               # 일별 분석
│
├── 캐시
│   └── data_cache/                  # Parquet 캐시
│       ├── fs_fnguide_{ticker}.parquet    # 재무제표
│       ├── all_ohlcv_{start}_{end}.parquet # OHLCV
│       └── market_cap_ALL_{date}.parquet   # 시가총액
│
└── 문서
    ├── README.md                    # 프로젝트 개요
    ├── PROJECT_REPORT.md            # 결과 리포트
    └── SESSION_HANDOFF.md           # 기술 문서 (이 파일)
```

---

## 5. 환경 설정

### Python 환경
```
Python: 3.13+ (miniconda3)
```

### 필수 패키지
```bash
pip install pykrx pandas numpy scipy matplotlib requests beautifulsoup4 lxml pyarrow tqdm aiohttp
```

### 설정 파일 (config.py)
```python
# 텔레그램 설정
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"

# OpenDART API
DART_API_KEY = "your_dart_api_key"

# 병렬 처리
MAX_CONCURRENT_REQUESTS = 10  # DART API
PYKRX_WORKERS = 10            # pykrx

# 유니버스 필터
MIN_MARKET_CAP = 1000   # 억원
MIN_TRADING_VALUE = 30  # 억원

# Git 자동 푸시
GIT_AUTO_PUSH = True
```

---

## 6. 알려진 제한사항

### 데이터 관련
1. **DART API 호출 제한**: 일 10,000건 (과도한 요청 시 IP 차단)
2. **FnGuide 컨센서스**: 대형주 위주 커버리지 (~60%)
3. **선호주/우선주**: 일부 재무제표 누락 가능

### 전략 관련
1. **섹터 분류 없음**: 업종 중립화 미적용
2. **거래비용**: 0.3% 고정 (슬리피지 미반영)

### 백테스팅 관련
1. **생존 편향**: 상장폐지 종목 미포함
2. **Look-ahead bias**: 재무제표 공시 시차 반영 (45일/90일)
3. **배당 미반영**: 배당 재투자 미구현

---

## 7. 작업 로그

| 날짜 | 주요 작업 | 파일 |
|------|-----------|------|
| 2026-01-30 | 포트폴리오 생성 시스템 구현 | create_current_portfolio.py |
| 2026-01-31 | 일별 모니터링 시스템 구현 | daily_monitor.py |
| 2026-02-01 | 텔레그램 메시지 3분할 | daily_monitor.py |
| 2026-02-02 | 모멘텀 팩터 구현 | strategy_b_multifactor.py |
| 2026-02-03 | v6.4 리팩토링 (Quality+Price 2축) | daily_monitor.py |
| **2026-02-03** | **OpenDART API 도입** | **dart_api.py (NEW)** |
| **2026-02-03** | **Skip & Log 에러 처리** | **error_handler.py (NEW)** |
| **2026-02-03** | **병렬 처리 추가** | **data_collector.py** |
| **2026-02-03** | **async main() 구조 전환** | **create_current_portfolio.py** |
| **2026-02-03** | **거래대금 필터 30억으로 조정** | **config.py** |
| **2026-02-03** | **문서 전면 업데이트** | **README.md, PROJECT_REPORT.md** |
| **2026-02-04** | **20일 평균 거래대금 필터 적용** | **create_current_portfolio.py** |
| **2026-02-04** | **텔레그램 편입/편출 사유 표시** | **send_telegram_detailed.py** |
| **2026-02-04** | **종목별 인사이트 추가 (섹터/요약/선정이유)** | **send_telegram_detailed.py** |
| **2026-02-04** | **고객 친화적 메시지 형식 개선** | **send_telegram_detailed.py** |
| **2026-02-05** | **Claude 종합 순위 시스템 구현 (전략+기술+거래량+뉴스)** | **send_telegram_detailed.py** |
| **2026-02-05** | **텔레그램 완전 자동화 (send_telegram_auto.py)** | **send_telegram_auto.py (NEW)** |
| **2026-02-05** | **분석 기준일 전일 거래일로 변경** | **send_telegram_auto.py** |
| **2026-02-05** | **진입점수 개선: 신고가 보너스 제거 (싸게 사자 철학)** | **send_telegram_auto.py** |
| **2026-02-05** | **핵심추천 섹션 제거 (순위만 표시)** | **send_telegram_auto.py** |
| **2026-02-05** | **뉴스 자동 크롤링 및 센티먼트 분석 추가** | **send_telegram_auto.py** |
| **2026-02-05** | **뉴스 헤드라인 요약 개선 (시세뉴스 필터링)** | **send_telegram_auto.py** |

---

## 8. 빠른 시작 가이드

```bash
# 1. 패키지 설치
pip install pykrx pandas numpy scipy matplotlib requests beautifulsoup4 lxml pyarrow tqdm aiohttp

# 2. 설정 파일 생성
cp config_template.py config.py
# DART_API_KEY, TELEGRAM 설정 입력

# 3. 포트폴리오 생성 (캐시 모드: ~15초)
python create_current_portfolio.py

# 4. 일별 모니터링 (~3분)
python daily_monitor.py

# 5. 백테스트 (~15분)
python full_backtest.py
```

---

**문서 버전**: 6.5
**최종 업데이트**: 2026-02-05
