# 한국 주식 퀀트 투자 시스템

KOSPI/KOSDAQ 대상 멀티팩터 퀀트 전략 백테스팅 및 포트폴리오 생성 시스템

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| **전략 A** | 마법공식 (Magic Formula) - 이익수익률 + ROIC → 사전 필터 150개 |
| **전략 B** | 멀티팩터 - Value(40%) + Quality(40%) + Momentum(20%) → 스코어링 |
| **통합순위** | 마법공식 30% + 멀티팩터 70% → 최종 30종목 |
| **유니버스** | 시가총액 1000억+, 20일평균 거래대금 30억+, 금융/지주사 제외 |
| **리밸런싱** | 분기별 (4/5/8/11월 - 실적 공시 후) |
| **텔레그램** | 매일 06:00 KST 자동 전송 (TOP 20 상세분석) |

### 백테스트 성과 (2015-2025)

| 지표 | KOSPI | 전략 A | 전략 B |
|------|-------|--------|--------|
| **CAGR** | 7.58% | **11.98%** | **13.15%** |
| **MDD** | -43.90% | -24.42% | -33.90% |
| **Sharpe** | 0.27 | 0.53 | 0.53 |
| **초과수익** | - | +4.4%p | +5.6%p |

---

## 2. 빠른 시작

### Python 환경

아래 두 경로 중 하나의 Python을 사용:
```
C:\Users\jkw88\miniconda3\envs\volumequant\python.exe
C:\Users\user\miniconda3\envs\volumequant\python.exe
```

### 실행 방법

```bash
# 1. 패키지 설치
pip install pykrx pandas numpy requests beautifulsoup4 lxml pyarrow tqdm scipy html5lib google-genai

# 2. 텔레그램 설정 (선택)
cp config_template.py config.py
# config.py에서 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 설정

# 3. 현재 포트폴리오 생성
python create_current_portfolio.py
# - 캐시 모드: ~30초
# - 전체 수집: ~5-10분

# 4. 텔레그램 전송
python send_telegram_auto.py

# 5. 전체 백테스팅 (~15분 소요)
python full_backtest.py
```

---

## 3. 프로젝트 구조

```
quant_py-main/
│
├── [핵심 모듈] ─────────────────────────────────────────────
│   ├── error_handler.py        # Skip & Log 에러 처리
│   ├── fnguide_crawler.py      # FnGuide 재무제표 캐시 + 가중TTM
│   ├── data_collector.py       # pykrx API + 병렬 처리
│   ├── strategy_a_magic.py     # 전략 A: 마법공식 (사전 필터)
│   ├── strategy_b_multifactor.py # 전략 B: 멀티팩터 (최종 스코어링)
│   └── gemini_analysis.py      # Gemini AI 리스크 분석
│
├── [실행 스크립트] ─────────────────────────────────────────
│   ├── create_current_portfolio.py  # 포트폴리오 생성 (메인)
│   ├── send_telegram_auto.py        # 텔레그램 자동 전송 (GitHub Actions)
│   ├── full_backtest.py             # 전체 백테스팅
│   └── generate_report_pdf.py       # PDF 리포트 생성
│
├── [설정] ──────────────────────────────────────────────────
│   ├── config.py                # API키/텔레그램 설정 (gitignore)
│   └── config_template.py       # 설정 템플릿
│
├── [출력 디렉토리] ─────────────────────────────────────────
│   ├── output/                  # 포트폴리오 CSV/리포트
│   └── backtest_results/        # 백테스트 결과
│
├── [캐시] ──────────────────────────────────────────────────
│   └── data_cache/              # 재무제표/OHLCV parquet 캐시
│
└── [문서] ──────────────────────────────────────────────────
    ├── README.md                # 프로젝트 개요 (이 파일)
    └── SESSION_HANDOFF.md       # 개발 히스토리/기술 문서
```

---

## 4. 핵심 모듈 상세

### 4.1 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│                        데이터 수집                               │
├─────────────────────────────────────────────────────────────────┤
│  pykrx API                          FnGuide                     │
│  ┌─────────────┐               ┌──────────────┐                │
│  │ 시가총액    │               │ 재무제표     │                │
│  │ OHLCV      │               │ (캐시)       │                │
│  │ PER/PBR/DIV│               │              │                │
│  └──────┬──────┘               └──────┬───────┘                │
│         └──────────────┬──────────────┘                        │
│                        ▼                                        │
│                 ┌─────────────┐                                 │
│                 │  유니버스   │                                 │
│                 │ 시총1000억+ │                                 │
│                 │ 거래30억+   │                                 │
│                 └──────┬──────┘                                 │
└────────────────────────┼────────────────────────────────────────┘
                         │
┌────────────────────────┼────────────────────────────────────────┐
│                        │     전략 실행                           │
├────────────────────────┼────────────────────────────────────────┤
│                        ▼                                        │
│              ┌─────────────────┐                                │
│              │   전략 A 사전필터 │                               │
│              │   (마법공식)     │                                │
│              │   상위 150종목   │                                │
│              └────────┬────────┘                                │
│                       ▼                                         │
│              ┌─────────────────┐                                │
│              │  전략 B 스코어링 │                                │
│              │  (멀티팩터)      │                                │
│              │  150종목 전체    │                                │
│              └────────┬────────┘                                │
│                       ▼                                         │
│              ┌─────────────────┐                                │
│              │ A30% + B70%     │                                │
│              │ 통합순위 TOP 30 │                                │
│              └─────────────────┘                                │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 전략 A - 마법공식 (사전 필터)

```
이익수익률 = EBIT / EV      (EV = 시가총액 + 총부채 - 여유자금)
투하자본수익률 = EBIT / IC   (IC = (유동자산 - 유동부채) + 비유동자산)

마법공식_순위 = rank(이익수익률) + rank(ROIC)
→ 상위 150종목 사전 필터
```

### 4.3 전략 B - 멀티팩터 (최종 스코어링)

```
Value   40%: PER(실시간) + PBR(실시간) + PCR + PSR + DIV(실시간)
Quality 40%: ROE + GPA + CFO/Assets
Momentum 20%: 12개월 수익률 (최근 1개월 제외)

멀티팩터_점수 = Value*0.4 + Quality*0.4 + Momentum*0.2
```

### 4.4 가중 TTM (Weighted Trailing Twelve Months)

```
손익계산서/현금흐름표 항목:
  최신 분기: 40% (가중치 1.6)
  2번째 분기: 30% (가중치 1.2)
  3번째 분기: 20% (가중치 0.8)
  4번째 분기: 10% (가중치 0.4)
  합계 = 4.0 (기존 TTM 합산과 동일 스케일)
→ 최근 실적 변화를 더 잘 반영
```

### 4.5 텔레그램 메시지

```
1~2개 메시지 (TOP 20 상세분석):
  - 시장 개황 (코스피/코스닥 지수, RSI)
  - 전략 설명
  - TOP 20 종목별: 순위, 업종, 가격, PER/PBR/ROE, RSI, 52주위치, 뉴스
  - 3800자 초과 시 자동 분할

뉴스 필터링:
  - 채용공고, 다종목 나열, 종목명 미포함 뉴스 자동 제외
  - 시세 뉴스 (상승/하락/VI발동) 제외
```

### 4.6 AI 브리핑 (Gemini)

```
"검색은 코드가, 분석은 AI가" 원칙:
→ 개별 종목 뉴스 검색 안 함 (Grounding은 요청당 5-8개만 검색, 나머지 할루시네이션)
→ 시장 동향만 Google Search (1개 광범위 쿼리는 안정적)
→ 코드가 포트폴리오 데이터(PER/PBR/ROE/RSI/52주위치) 구성 → AI가 해석

Gemini 2.5 Flash + Google Search Grounding (temperature 0.3)
출력 형식:
  📰 이번 주 시장 (AI가 검색, 시장 전반 이벤트 2~3줄)
  ⚠️ 주의 종목 (코드가 감지한 RSI 과매수/과매도, 52주 급락, 급등락)
  📊 포트폴리오 특징 (섹터 편중, 밸류에이션, 모멘텀 패턴)
개인봇에만 전송 (채널 제외)
```

---

## 5. 설정 파일

### config.py (gitignore)

```python
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"
TELEGRAM_PRIVATE_ID = "your_private_id"
MIN_MARKET_CAP = 1000
MIN_TRADING_VALUE = 30
MAX_CONCURRENT_REQUESTS = 10
PYKRX_WORKERS = 10
PREFILTER_N = 150
N_STOCKS = 30
GEMINI_API_KEY = "your_gemini_api_key"
```

---

## 6. GitHub Actions 자동화

### 매일 06:00 KST 자동 실행

```yaml
# .github/workflows/telegram_daily.yml
on:
  schedule:
    - cron: '0 21 * * 0-4'  # UTC 21:00 = KST 06:00 (월~금)
  workflow_dispatch:          # 수동 실행 가능
```

### 실행 흐름

```
1. checkout → 최신 코드 pull
2. Python 3.11 설치
3. pip install (의존성)
4. config.py 생성 (GitHub Secrets에서)
5. create_current_portfolio.py → CSV 생성
6. send_telegram_auto.py → 포트폴리오 전송 + AI 리스크 분석
```

### GitHub Secrets

Repository → Settings → Secrets → Actions:
- `TELEGRAM_BOT_TOKEN`: 봇 토큰
- `TELEGRAM_CHAT_ID`: 채널 ID
- `TELEGRAM_PRIVATE_ID`: 개인 채팅 ID
- `GEMINI_API_KEY`: Gemini API 키 (AI 리스크 분석용)

---

## 7. 주의사항

1. **캐시 활용**: 재수집 불필요 시 캐시 모드 사용 권장
2. **FnGuide 캐시**: Q3 2025 고정 (수동 갱신 필요)
3. **백테스트 한계**:
   - 생존 편향 (상장폐지 종목 미포함)
   - 거래비용 단순화 (0.3% 고정)
   - 슬리피지 미반영

---

*버전: 3.1 | 최종 업데이트: 2026-02-08 | Generated by Claude Code*
