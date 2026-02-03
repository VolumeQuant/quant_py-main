# 한국 주식 퀀트 투자 시스템

KOSPI/KOSDAQ 대상 멀티팩터 퀀트 전략 백테스팅 및 포트폴리오 생성 시스템

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| **전략 A** | 마법공식 (Magic Formula) - 이익수익률 + ROIC |
| **전략 B** | 멀티팩터 - Value(40%) + Quality(40%) + Momentum(20%) |
| **유니버스** | 시가총액 1000억+, 거래대금 50억+, 금융/지주사 제외 |
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
pip install pykrx==1.2.3 pandas numpy matplotlib requests beautifulsoup4 lxml pyarrow tqdm

# 2. 텔레그램 설정 (선택)
cp config_template.py config.py
# config.py에서 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 설정

# 3. 현재 포트폴리오 생성 (~50분 소요)
python create_current_portfolio.py

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
│   ├── fnguide_crawler.py       # FnGuide 재무제표 크롤링
│   ├── data_collector.py        # pykrx API 데이터 수집
│   ├── strategy_a_magic.py      # 전략 A: 마법공식
│   ├── strategy_b_multifactor.py # 전략 B: 멀티팩터
│   └── utils.py                 # 유틸리티 함수
│
├── [실행 스크립트] ─────────────────────────────────────────
│   ├── create_current_portfolio.py  # 현재 포트폴리오 생성 (메인)
│   ├── daily_monitor.py             # 일별 모니터링 + 텔레그램
│   ├── full_backtest.py             # 전체 백테스팅
│   └── generate_report_pdf.py       # PDF 리포트 생성
│
├── [설정] ──────────────────────────────────────────────────
│   ├── config.py                # 텔레그램/Git 설정 (gitignore)
│   └── config_template.py       # 설정 템플릿
│
├── [출력 디렉토리] ─────────────────────────────────────────
│   ├── output/                  # 포트폴리오 CSV/리포트
│   ├── backtest_results/        # 백테스트 결과
│   └── daily_reports/           # 일별 분석 JSON/CSV
│
├── [캐시] ──────────────────────────────────────────────────
│   └── data_cache/              # 재무제표 parquet 캐시
│
└── [문서] ──────────────────────────────────────────────────
    ├── README.md                # 프로젝트 개요 (이 파일)
    ├── PROJECT_REPORT.md        # 상세 결과 리포트
    └── SESSION_HANDOFF.md       # 개발 히스토리/기술 문서
```

---

## 4. 핵심 모듈 상세

### 4.1 fnguide_crawler.py

FnGuide 웹사이트에서 재무제표 크롤링

```python
# ═══════════════════════════════════════════════════════════════
# 주요 함수
# ═══════════════════════════════════════════════════════════════

def get_financial_statement(ticker, use_cache=True):
    """
    FnGuide에서 연간/분기 재무제표 수집

    URL: comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?gicode=A{ticker}

    Returns:
        DataFrame: 연간/분기 재무제표 통합 (long format)

    캐시: data_cache/fs_fnguide_{ticker}.parquet
    """

def extract_magic_formula_data(fs_dict, base_date=None, use_ttm=True):
    """
    마법공식 계산용 데이터 추출 (TTM 지원)

    TTM 로직:
    - 손익계산서/현금흐름표: 최근 4분기 합산 (Flow)
    - 재무상태표: 최근 분기 값 사용 (Stock)

    공시 시차:
    - 분기: 45일
    - 연간: 90일

    추출 항목:
    - 손익: 매출액, 영업이익, 당기순이익, 법인세비용, 세전계속사업이익
    - 재무: 자산, 부채, 자본, 유동자산, 비유동자산, 현금
    - 현금: 영업현금흐름, 감가상각비
    """

def get_consensus_data(ticker):
    """
    Forward EPS/PER 컨센서스 수집 (추가 정보용)

    URL: comp.fnguide.com/SVO2/ASP/SVD_Main.asp (테이블 7)

    Returns:
        dict: {forward_eps, forward_per, target_price, analyst_count, has_consensus}

    주의: 필터로 사용하지 않음 (소형주 커버리지 부재)
    """
```

**크롤링 데이터 구조**:
```
FnGuide SVD_Finance.asp 테이블 구조:
├── tables[0]: 포괄손익계산서 (연간)
├── tables[1]: 포괄손익계산서 (분기)
├── tables[2]: 재무상태표 (연간)
├── tables[3]: 재무상태표 (분기)
├── tables[4]: 현금흐름표 (연간)
└── tables[5]: 현금흐름표 (분기)
```

### 4.2 data_collector.py

pykrx API 래퍼

```python
# ═══════════════════════════════════════════════════════════════
# 주요 함수
# ═══════════════════════════════════════════════════════════════

def get_market_data(date, market='ALL'):
    """
    시가총액, 거래량, 기본 지표 수집

    pykrx.stock.get_market_cap(date, market)
    pykrx.stock.get_market_fundamental(date, market)

    Returns:
        DataFrame: 종목코드, 시가총액, 거래량, PER, PBR, 배당수익률
    """

def get_ohlcv_data(ticker, start_date, end_date):
    """
    일별 OHLCV 데이터 수집

    pykrx.stock.get_market_ohlcv(start_date, end_date, ticker)

    Returns:
        DataFrame: 시가, 고가, 저가, 종가, 거래량
    """

def get_universe(base_date, min_market_cap=1000, min_trading_value=50):
    """
    투자 유니버스 구성

    조건:
    - 시가총액 >= 1000억원
    - 일평균 거래대금 >= 50억원
    - 금융업 제외 (은행, 증권, 보험)
    - 지주회사 제외 (종목명에 '지주' 포함)
    - 스팩, 리츠 제외

    Returns:
        DataFrame: 유니버스 종목 리스트 (약 668개)
    """
```

### 4.3 strategy_a_magic.py

마법공식 (Magic Formula) 전략

```python
# ═══════════════════════════════════════════════════════════════
# 전략 개요
# ═══════════════════════════════════════════════════════════════
#
# Joel Greenblatt의 "주식시장을 이기는 작은 책" 기반
# 저평가(이익수익률) + 고효율(ROIC) 종목 선정

# ═══════════════════════════════════════════════════════════════
# 핵심 지표 계산
# ═══════════════════════════════════════════════════════════════

def calculate_earnings_yield(row):
    """
    이익수익률 = EBIT / EV

    EBIT = 세전계속사업이익 + 법인세비용
         = 영업이익 (대안)

    EV = 시가총액 + 총부채 - 현금

    의미: 기업 인수 시 연간 수익률
    높을수록 저평가
    """

def calculate_roic(row):
    """
    투하자본수익률 = EBIT / Invested Capital

    Invested Capital = 자본 + 유동부채 - 현금 - 유동자산
                     = 순고정자산 + 순운전자본

    의미: 투자 자본 대비 영업 효율
    높을수록 효율적
    """

def run_strategy_a(universe_df, fs_data):
    """
    마법공식 전략 실행

    1. 이익수익률 순위 산출 (높을수록 좋음)
    2. 투하자본수익률 순위 산출 (높을수록 좋음)
    3. 두 순위 합산
    4. 합산 순위 상위 30종목 선정

    Returns:
        DataFrame: 상위 30종목 (이익수익률, ROIC, 마법공식_순위)
    """
```

### 4.4 strategy_b_multifactor.py

멀티팩터 전략

```python
# ═══════════════════════════════════════════════════════════════
# 팩터 구성
# ═══════════════════════════════════════════════════════════════

FACTOR_WEIGHTS = {
    'value': 0.40,      # 가치 팩터
    'quality': 0.40,    # 품질 팩터
    'momentum': 0.20    # 모멘텀 팩터
}

# ═══════════════════════════════════════════════════════════════
# 가치 팩터 (Value) - 40%
# ═══════════════════════════════════════════════════════════════

def calculate_value_score(data):
    """
    Value = mean(Z-Score of [PER역수, PBR역수, PCR역수, PSR역수])

    PER = 시가총액 / 당기순이익  (낮을수록 저평가)
    PBR = 시가총액 / 자본       (낮을수록 저평가)
    PCR = 시가총액 / 영업현금흐름 (낮을수록 저평가)
    PSR = 시가총액 / 매출액     (낮을수록 저평가)

    Z-Score 변환 후 역수 사용 (낮은 PER = 높은 점수)
    """

# ═══════════════════════════════════════════════════════════════
# 품질 팩터 (Quality) - 40%
# ═══════════════════════════════════════════════════════════════

def calculate_quality_score(data):
    """
    Quality = mean(Z-Score of [ROE, GPA, CFO/Assets])

    ROE = 당기순이익 / 자본     (높을수록 효율적)
    GPA = 매출총이익 / 자산     (높을수록 수익성)
    CFO = 영업현금흐름 / 자산   (높을수록 현금창출력)
    """

# ═══════════════════════════════════════════════════════════════
# 모멘텀 팩터 (Momentum) - 20%
# ═══════════════════════════════════════════════════════════════

def calculate_momentum_score(data, price_df):
    """
    Momentum = 12개월 수익률 (최근 1개월 제외)

    계산: (P[-21] / P[-252-21] - 1) * 100

    최근 1개월 제외 이유: 단기 반전 효과 회피

    모멘텀 데이터 없는 종목: 자동 제외
    (신규 상장, 거래정지 등)
    """

# ═══════════════════════════════════════════════════════════════
# 종합 점수
# ═══════════════════════════════════════════════════════════════

def run_strategy_b(universe_df, fs_data, price_df):
    """
    멀티팩터 전략 실행

    1. Value Z-Score 계산
    2. Quality Z-Score 계산
    3. Momentum Z-Score 계산
    4. 종합점수 = Value*0.4 + Quality*0.4 + Momentum*0.2
    5. 모멘텀 없는 종목 제외
    6. 상위 30종목 선정

    Returns:
        DataFrame: 상위 30종목 (밸류/퀄리티/모멘텀_점수, 멀티팩터_점수)
    """
```

### 4.5 daily_monitor.py

일별 모니터링 시스템

```python
# ═══════════════════════════════════════════════════════════════
# 진입 점수 시스템
# ═══════════════════════════════════════════════════════════════

ENTRY_WEIGHTS = {
    'rsi': 0.25,           # RSI 과매도
    'position_52w': 0.25,  # 52주 위치
    'bollinger': 0.20,     # 볼린저밴드
    'ma_deviation': 0.20,  # 이동평균 이격도
    'volume': 0.10         # 거래량 신호
}

def calculate_entry_score(ticker, ohlcv_df):
    """
    진입 점수 산출 (0 ~ 1)

    RSI (25%):
    - RSI ≤ 30: 1.0점 (과매도)
    - RSI 30~50: 0.5점
    - RSI ≥ 70: 0.0점

    52주 위치 (25%):
    - 52주 저점 근처: 1.0점
    - 52주 고점 근처: 0.0점

    볼린저밴드 (20%):
    - 하단 터치: 1.0점
    - 상단 터치: 0.0점

    이동평균 이격도 (20%):
    - 60일선 대비 -20%: 1.0점
    - 60일선 대비 +20%: 0.0점

    거래량 (10%):
    - 평균 2배 이상: 1.0점
    - 평균 미만: 0.3점
    """

# ═══════════════════════════════════════════════════════════════
# 분류 기준
# ═══════════════════════════════════════════════════════════════

THRESHOLDS = {
    'buy': 0.6,    # 매수 적기
    'watch': 0.3   # 관망
}

def classify_stock(entry_score):
    """
    분류:
    - 매수 적기 (🟢): entry_score >= 0.6
    - 관망 (🟡): 0.3 <= entry_score < 0.6
    - 대기 (🔴): entry_score < 0.3
    """

# ═══════════════════════════════════════════════════════════════
# 텔레그램 알림
# ═══════════════════════════════════════════════════════════════

def send_telegram_message(buy_list, watch_list, wait_list):
    """
    3개 메시지 분할 발송

    메시지 1: 전략 설명 + 매수 추천 종목 상세
    - 종목명, 현재가, PER, RSI, 52주고점대비, 진입점수
    - 매수 근거 자동 생성

    메시지 2: 관망 종목 전체
    - 관망 이유 표시

    메시지 3: 과열/대기 종목 + Forward EPS 정보
    - 과열 이유 표시
    - 컨센서스 보유 종목: Forward PER 표시 (추가 정보)
    """

# ═══════════════════════════════════════════════════════════════
# 근거 생성 함수
# ═══════════════════════════════════════════════════════════════

def get_buy_reason(row):
    """매수 근거 생성: PER저평가, 52주급락, RSI과매도 등"""

def get_watch_reason(row):
    """관망 근거 생성: RSI과열, 고점근접, BB상단 등"""

def get_hot_reason(row):
    """과열 근거 생성: RSI극과열, 신고가, 괴리과다 등"""
```

---

## 5. 실행 스크립트 상세

### 5.1 create_current_portfolio.py

```python
# 메인 포트폴리오 생성 스크립트

# 실행 흐름:
# 1. 최근 거래일 자동 탐지 (미래 날짜 문제 방지)
# 2. 유니버스 구성 (약 668개)
# 3. FnGuide 재무제표 크롤링 (~50분)
# 4. 가격 데이터 수집 (모멘텀용, 450일)
# 5. 전략 A 실행 → 30종목
# 6. 전략 B 실행 → 30종목
# 7. 결과 저장 (CSV, 리포트)

# 출력:
# - output/portfolio_YYYY_MM_strategy_a.csv
# - output/portfolio_YYYY_MM_strategy_b.csv
# - output/portfolio_YYYY_MM_report.txt
```

### 5.2 daily_monitor.py

```python
# 일별 모니터링 스크립트

# 실행 흐름:
# 1. 전략 A/B 포트폴리오 로드 (49개 종목)
# 2. 최근 120일 OHLCV 수집
# 3. 기술적 지표 계산 (RSI, BB, MA)
# 4. 진입 점수 산출
# 5. 종목 분류 (매수/관망/대기)
# 6. Forward EPS 컨센서스 조회 (추가 정보)
# 7. 텔레그램 발송
# 8. Git 자동 커밋/푸시 (선택)

# 출력:
# - daily_reports/daily_analysis_YYYYMMDD.json
# - daily_reports/daily_analysis_YYYYMMDD.csv
# - daily_reports/daily_report_YYYYMMDD.txt
```

### 5.3 full_backtest.py

```python
# 전체 백테스팅 스크립트

# 설정:
START_DATE = '20150101'
END_DATE = '20251231'
REBALANCE_MONTHS = [3, 6, 9, 12]  # 분기별
TOP_N = 30

# 실행 흐름:
# 1. 리밸런싱 날짜 생성 (44회)
# 2. 각 분기별:
#    - 유니버스 구성
#    - 재무제표 수집
#    - 전략 실행 → 30종목 선정
#    - 분기 수익률 계산
# 3. 누적 수익률 계산
# 4. 성과 지표 산출 (CAGR, MDD, Sharpe)
# 5. 벤치마크(KOSPI) 비교

# 출력:
# - backtest_results/backtest_strategy_A_*.csv/json
# - backtest_results/backtest_strategy_B_*.csv/json
# - backtest_results/backtest_comparison.csv
```

---

## 6. 데이터 흐름도

```
┌─────────────────────────────────────────────────────────────────┐
│                        데이터 수집                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  pykrx API                          FnGuide 크롤링               │
│  ┌─────────────┐                    ┌─────────────────┐         │
│  │ 시가총액    │                    │ 재무제표 (TTM)   │         │
│  │ OHLCV      │                    │ - 손익계산서     │         │
│  │ 기본지표    │                    │ - 재무상태표     │         │
│  └──────┬──────┘                    │ - 현금흐름표     │         │
│         │                          └────────┬────────┘         │
│         └────────────────┬─────────────────┘                   │
│                          │                                      │
│                          ▼                                      │
│                   ┌─────────────┐                               │
│                   │  유니버스   │                               │
│                   │  (668개)    │                               │
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
│                   │  (11개)     │                               │
│                   └─────────────┘                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                          │     일별 모니터링                      │
├──────────────────────────┼──────────────────────────────────────┤
│                          │                                      │
│                          ▼                                      │
│                   ┌─────────────┐                               │
│                   │ 49개 종목   │                               │
│                   │ 기술적분석  │                               │
│                   └──────┬──────┘                               │
│                          │                                      │
│         ┌────────────────┼────────────────┐                     │
│         │                │                │                     │
│         ▼                ▼                ▼                     │
│    ┌─────────┐     ┌─────────┐     ┌─────────┐                  │
│    │ 매수적기│     │  관망   │     │  대기   │                  │
│    │  (🟢)  │     │  (🟡)  │     │  (🔴)  │                  │
│    └────┬────┘     └────┬────┘     └────┬────┘                  │
│         │               │               │                       │
│         └───────────────┴───────────────┘                       │
│                          │                                      │
│                          ▼                                      │
│                   ┌─────────────┐                               │
│                   │  텔레그램   │                               │
│                   │   알림      │                               │
│                   └─────────────┘                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. 설정 파일

### config.py (gitignore)

```python
# 텔레그램 설정
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"

# Git 자동 푸시
GIT_AUTO_PUSH = True

# 진입 점수 임계값
SCORE_BUY = 0.6    # 매수 적기 기준
SCORE_WATCH = 0.3  # 관망 기준
```

---

## 8. 출력 파일 설명

### output/
| 파일 | 설명 |
|------|------|
| `portfolio_YYYY_MM_strategy_a.csv` | 전략 A 30종목 (이익수익률, ROIC) |
| `portfolio_YYYY_MM_strategy_b.csv` | 전략 B 30종목 (밸류/퀄리티/모멘텀) |
| `portfolio_YYYY_MM_report.txt` | 분석 요약 리포트 |
| `strategy_ab_with_forward_eps.csv` | Forward EPS 추가 정보 |

### backtest_results/
| 파일 | 설명 |
|------|------|
| `backtest_strategy_A_returns.csv` | 전략 A 일별 수익률 |
| `backtest_strategy_A_metrics.json` | 전략 A 성과 지표 |
| `backtest_strategy_B_*.csv/json` | 전략 B 결과 |
| `backtest_comparison.csv` | A/B/KOSPI 비교 |

### daily_reports/
| 파일 | 설명 |
|------|------|
| `daily_analysis_YYYYMMDD.json` | JSON 상세 분석 |
| `daily_analysis_YYYYMMDD.csv` | CSV 전체 데이터 |
| `daily_report_YYYYMMDD.txt` | 텍스트 요약 |

---

## 9. 기술 스택

| 패키지 | 버전 | 용도 |
|--------|------|------|
| **pykrx** | 1.2.3 | 한국 주식 데이터 API |
| **pandas** | 2.2+ | 데이터 처리 |
| **numpy** | 2.1+ | 수치 연산 |
| **requests** | 2.32+ | HTTP 요청 |
| **beautifulsoup4** | 4.12+ | HTML 파싱 |
| **pyarrow** | - | parquet 캐시 |
| **tqdm** | - | 진행 표시 |

---

## 10. 주의사항

1. **pykrx 버전**: 반드시 1.2.3 사용 (1.0.x는 인코딩 오류)
2. **FnGuide 크롤링**: 딜레이 2초 적용 (과도한 요청 시 차단)
3. **캐시 용량**: data_cache/ 종목당 ~50KB (전체 ~35MB)
4. **백테스트 한계**:
   - 생존 편향 (상장폐지 종목 미포함)
   - 거래비용 단순화 (0.3% 고정)
   - 슬리피지 미반영
5. **Forward EPS**: 필터가 아닌 추가 정보로만 활용 (소형주 커버리지 부재)

---

## 11. 라이선스

MIT License

---

*버전: 2.0 | 최종 업데이트: 2026-02-03 | Generated by Claude Code*
