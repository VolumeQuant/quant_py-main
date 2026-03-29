# 한국 주식 퀀트 스크리닝 시스템

KOSPI/KOSDAQ 전종목 대상 멀티팩터 퀀트 전략 — **Slow In, Score Out**

매일 자동으로 ~900개 종목을 4팩터로 채점하고, 3일 연속 검증된 고점수 종목만 텔레그램으로 전송합니다.

> 채널: [@kr_dailyquant](https://t.me/kr_dailyquant) | 전략 버전: v71 | 최종 업데이트: 2026-03-26

---

## 시스템 한눈에 보기

```
유니버스 (~900종목)                         텔레그램 3메시지
  시총 1000억+, 거래대금 충족                  [Signal]  매수 후보 + AI 근거
  ↓                                          [Risk]    시장 지수 + 신용/변동성
MA120 x 0.95 추세 필터                       [Watch]   Top 20 + 매도 검토선
  ↓
4팩터 스코어링 (V5 + Q20 + G45 + M30)
  Blom rank z-score, 카테고리 재표준화
  ↓
하드필터: ROE<0, PER>200, floor -1.5s
  ↓
일일 순위 JSON 저장 (state/)
  ↓
3일 교집합 (Slow In) + Death List (Fast Out)
  ↓
rank ≤ 5 진입 / WR > 12 퇴출 / -10% 손절
```

---

## 전략 상세

### 4팩터 국면 적응형 (v71)

| 팩터 | 비중 | 서브팩터 | 정규화 |
|------|------|----------|--------|
| **Value** | 5% | PER + PBR + PCR + PSR | 전체 유니버스 rank z-score (낮을수록 좋음) |
| **Quality** | 20% | ROE + GPA + CFO | 전체 유니버스 rank z-score |
| **Growth** | 45% | 매출성장률×0.7 + 영업이익변화율×0.3 | 전체 유니버스 rank z-score (커버리지 96%) |
| **Momentum** | 30% | 6M수익률/변동성 + K_ratio | **섹터 내** rank z-score (추세 제거) |

**정규화 과정**: 서브팩터별 Rank -> 균등분포 -> 정규 ppf (Blom 변환) -> 카테고리 평균 -> std=1 재표준화

### 하드필터

| 필터 | 기준 | 목적 |
|------|------|------|
| ROE 게이트 | ROE < 0% (TTM) -> 제외 | 적자 기업 밸류 트랩 방지 |
| PER 상한 | PER > 200 -> 제외 | 잔존가치 없는 기업 제거 |
| 단일팩터 floor | 4팩터 중 1개 < -1.5s -> 제외 | 극단 약점 종목 과락 |
| MA120 추세 | 현재가 < MA120 x 0.95 -> 제외 | 중장기 하락 추세 차단 (5% 버퍼) |

### FWD_PER 보너스

컨센서스 Forward PER이 존재하고 EPS가 개선 추세이면, 최종 점수에 +10% std 가산. 팩터 모델 밖에서 적용하여 컨센서스 미보유 종목에 불이익 없음.

### 진입/퇴출 (Rank-based, v70)

| 구분 | 기준 | 설명 |
|------|------|------|
| **진입** | weighted_rank ≤ 5 | 3일 검증(✅) 종목 중 가중순위 상위 5 |
| **퇴출** | weighted_rank > 12.0 | 매도 검토선 |
| **손절** | -10% | 진입가 대비 (쿨다운 없음) |
| **슬롯** | 최대 7종목 | 동시 보유 상한 |

- `weighted_rank = T0 x 0.5 + T1 x 0.3 + T2 x 0.2` (3일 가중순위)
- 비중은 미지정 (투자자 판단)
- 시스템 누적 수익률: Signal 메시지에 KOSPI 대비 표시

### 3일 교집합 (Slow In)

1. 매일 전종목을 스코어링하여 `state/ranking_YYYYMMDD.json` 저장
2. 3거래일(T-0, T-1, T-2) 연속 Top 20에 포함된 종목만 후보 자격 부여
3. 후보 중 weighted_rank ≤ 5인 종목이 매수 후보 (최대 7종목)
4. 상태 표시: ✅ 3일 검증 / ⏳ 2일 관찰 / 🆕 신규 진입

### Death List (Fast Out)

어제 Top 20이었으나 오늘 이탈한 종목에 사유 라벨 부여:
- `120일선하락`: 현재가 < MA120
- `거래부족`: 시총/거래대금 미달
- `팩터하락` (가치/품질/성장/모멘텀): 가장 크게 하락한 팩터
- `순위밀림`: 기본값

---

## 시장 위험 지표

### 3-Layer 모델 (credit_monitor.py)

| Layer | 지표 | 데이터 소스 | 역할 |
|-------|------|-------------|------|
| 1 | US HY Spread | FRED API | 방향타 (구조적 위기 감지) |
| 2 | 한국 BBB- 스프레드 | ECOS API | 한국 신용시장 상태 |
| 3 | CBOE VIX | FRED API | 속도계 (순간 변동성) |

**HY 사계절 모델**: HY 수준(넓/좁) x 방향(상승/하락) -> 4분면(봄/여름/가을/겨울)
- 봄(Q1): 적극 매수 | 여름(Q2): 정상 매수 | 가을(Q3): 신중 | 겨울(Q4): 관망~분할매수
- VIX Concordance Check로 행동 톤 조절 (이중 확인 강화 / 일시적 쇼크 완화)
- KR BBB- 에스컬레이션 (경계: 경고 추가, 위기: picks 하향)

### 텔레그램 표시 (AI Risk 메시지)

```
📊 시장 지수
🟡 코스피 5,781(+0.31%)
🟢 코스닥 1,162(+1.58%) · 5일선 돌파

🏦 신용·변동성
🟡 과거 수익률이 낮았던 구간이에요
  회사채 금리차(HY) 3.27% · 상위 75%
  변동성지수(VIX) 24.1 · 상위 13%
  → 이 구간 과거 S&P 연평균 +0.4%
```

---

## 텔레그램 메시지 구조

매일 3개 메시지를 순서대로 전송 (parse_mode='HTML'):

### [1/3] Signal — 매수 후보

- 시스템 누적 수익률 (KOSPI 대비)
- 매수 후보 종목 (rank ≤ 5 + ✅ 3일 검증, 최대 7종목)
- 상관관계 경고 (🔗 그룹 자동 묶기, corr > 0.65)
- 선정 과정 (고객 친화적 — 전문 용어 없음)
- 종목별 순위 궤적 + 점수 + AI 내러티브 (Gemini + Google Search)
- 순위 이탈 알림 (사유별 묶기)

### [2/3] AI Risk — 시장 환경

- 시장 지수 (코스피/코스닥 + 이평선 이벤트 인라인)
- 신용·변동성 (1줄 결론 + 3줄 근거)
- 시장 동향 (Gemini + Google Search Grounding)
- 매수 주의 종목 (RSI >= 80 등 리스크 플래그)

### [3/3] Watchlist — Top 20 현황

- 상위 20종목 점수 정렬 + 순위 궤적
- 섹터 분포 1줄 요약
- `── 매도 검토선 ──` 구분선 (weighted_rank > 8.0 기준)
- 매매 조건 표시 (매수: 상위5 · 최대7 / 매도: WR>8 or -10% 손절)
- 매매 조건 표시 (매수: 상위5 · 최대7 / 매도: 15위밖 or -10% 손절)
- 순위 이탈 (사유별 묶기)

> 프레이밍: "추천"이 아닌 "스크리닝 결과" — 행동 지시 없음, 비중 미지정

---

## 프로젝트 구조

```
quant_py-main/
├── .github/workflows/           # GitHub Actions (비활성화, 수동 실행만)
│   ├── telegram_daily.yml
│   ├── telegram_test.yml
│   └── fnguide_weekly.yml
│
├── [핵심 파이프라인]
│   ├── create_current_portfolio.py  # 메인: 유니버스→필터→스코어→순위JSON
│   ├── ranking_manager.py           # 순위 영속화, 3일 교집합, Death List
│   ├── strategy_b_multifactor.py    # 4팩터 스코어링 (V/Q/G/M, Blom z-score)
│   ├── strategy_a_magic.py          # 마법공식 사전필터 (현재 SKIP)
│   └── send_telegram_auto.py        # 텔레그램 3메시지 전송
│
├── [데이터 수집]
│   ├── data_collector.py            # pykrx OHLCV + 시총 + PER/PBR
│   ├── fnguide_crawler.py           # FnGuide 재무제표 + 컨센서스 크롤링
│   ├── krx_auth.py                  # KRX 세션 인증 (timeout=30s)
│   ├── refresh_fnguide_cache.py     # FnGuide 주간 캐시 갱신
│   └── credit_monitor.py            # 시장 위험 지표 (HY/BBB-/VIX)
│
├── [AI 분석]
│   └── gemini_analysis.py           # Gemini 리스크 필터 + 종목 내러티브
│
├── [실행/스케줄러]
│   ├── run_daily.py                 # 일일 파이프라인 (Task Scheduler 진입점)
│   ├── run_weekly_refresh.py        # 주간 FnGuide 갱신 래퍼
│   ├── QuantWeeklyRefresh.xml       # 주간 Task Scheduler XML
│   ├── register_task.ps1            # 일일 Task 등록 스크립트
│   └── register_weekly_refresh.bat  # 주간 Task 등록 스크립트
│
├── [백테스트/분석 (참고용)]
│   ├── backtest_comprehensive.py    # 진입/퇴출 기준 최적화
│   ├── grid_search_v69.py           # Entry×Exit×Slots 그리드서치
│   ├── batch_recalculate_v69.py     # v69 일괄 재계산
│   └── ...
│
├── [상태/데이터]
│   ├── state/                       # 일일 순위 JSON (git tracked)
│   ├── data_cache/                  # FnGuide parquet 캐시 (git tracked)
│   ├── config.py                    # API 키/설정 (.gitignore)
│   └── error_handler.py             # 에러 추적 유틸리티
│
├── [문서]
│   ├── README.md                    # 이 파일
│   ├── SESSION_HANDOFF.md           # 개발 히스토리/기술 심화 문서
│   └── backtest_results.md          # 백테스트 결과 보고서
│
└── [출력 (.gitignore)]
    ├── output/                      # 포트폴리오 CSV
    ├── logs/                        # 실행 로그
    └── backtest_cache/              # 백테스트 캐시
```

---

## 설치 및 실행

### 환경 요구사항

- Python 3.10+ (conda 권장)
- Windows (Task Scheduler 사용)

### 패키지 설치

```bash
pip install pykrx pandas numpy requests beautifulsoup4 lxml pyarrow tqdm scipy html5lib google-genai
```

### 설정 (config.py)

```python
# 텔레그램
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_channel_id"       # 채널
TELEGRAM_PRIVATE_ID = "your_private_id"    # 개인봇 (테스트용)

# API 키
GEMINI_API_KEY = "your_gemini_key"         # AI 분석 (필수)
FRED_API_KEY = "your_fred_key"             # HY/VIX (선택, 없으면 CSV fallback)
ECOS_API_KEY = "your_ecos_key"             # 한국 BBB- (선택)

# KRX 인증 (국내 IP 전용)
KRX_USER_ID = "your_krx_id"
KRX_PASSWORD = "your_krx_pw"

# 유니버스 설정
MIN_MARKET_CAP = 1000       # 억원
PREFILTER_N = 200           # 마법공식 사전필터 수
N_STOCKS = 30               # 최종 순위 산출 수
```

### 수동 실행

```bash
# 포트폴리오 생성 (~3분)
python create_current_portfolio.py

# 텔레그램 전송 (개인봇 테스트)
TEST_MODE=1 python send_telegram_auto.py

# 전체 파이프라인 (개인봇 테스트)
TEST_MODE=1 python run_daily.py
```

### 자동 실행 (Windows Task Scheduler)

**일일 스케줄** (월~금 06:00 KST):
```
run_daily.py → create_current_portfolio.py → send_telegram_auto.py → git push state/
```
- `QuantDaily` Task — `register_task.ps1`로 등록
- StartWhenAvailable: 절전 복귀 시 즉시 실행
- 중복 방지: `logs/daily_YYYYMMDD.lock`

**주간 스케줄** (일요일 21:00 KST):
```
run_weekly_refresh.py → refresh_fnguide_cache.py (시총 1000억+ 전종목)
```
- `QuantWeeklyRefresh` Task — `register_weekly_refresh.bat`로 등록

### GitHub Actions (비활성화)

KRX 해외 IP 차단(2026-02-27~)으로 GitHub Actions에서 pykrx 호출 불가. 현재 로컬 Task Scheduler로 운영 중. `workflow_dispatch`를 통한 수동 실행만 가능.

---

## 데이터 소스

| 소스 | 수집 항목 | 주기 | 비고 |
|------|-----------|------|------|
| **pykrx** (KRX) | 종목 목록, OHLCV, 시총, PER/PBR | 매일 | 국내 IP 전용 |
| **FnGuide** | 재무제표, ROE/GPA/CFO, 매출성장률, Forward PER | 주간 캐시 | `data_cache/fs_fnguide_*.parquet` |
| **FRED** | US HY Spread, VIX | 매일 (API) | FRED_API_KEY 권장 |
| **ECOS** | 한국 BBB- 스프레드, 국고채 금리 | 매일 (API) | ECOS_API_KEY |
| **Gemini** | 시장 동향, 종목 내러티브 | 매일 (API) | Google Search Grounding |

### 가중 TTM (Weighted Trailing Twelve Months)

손익계산서/현금흐름표 항목의 TTM 계산 시 최근 분기에 가중치 부여:
- 최신 분기 40% / 2분기 30% / 3분기 20% / 4분기 10%
- 최근 실적 변화를 더 빠르게 반영

---

## 콜드 스타트

시스템 최초 가동 또는 데이터 단절 후:
1. 3거래일 동안 순위 JSON 축적 (채널 전송 스킵, 개인봇에만 전송)
2. 3일차부터 3일 교집합 계산 가능 -> 정상 운영 시작
3. 자동 감지, 별도 설정 불필요

---

## 주요 설정값

| 항목 | 값 | 파일 |
|------|-----|------|
| 진입 기준 | score_100 >= 72 | `ranking_manager.py` |
| 퇴출 기준 | score_100 < 68 | `ranking_manager.py` |
| 팩터 비중 | V25 + Q25 + G25 + M25 | `strategy_b_multifactor.py` |
| MA 필터 | MA120 x 0.95 | `create_current_portfolio.py` |
| 최소 시총 | 1000억 | `config.py` |
| 거래대금 (대형) | 50억 (시총 1조+) | `create_current_portfolio.py` |
| 거래대금 (중소형) | 20억 (시총 3000억~1조) | `create_current_portfolio.py` |
| Watchlist 크기 | Top 20 | `send_telegram_auto.py` |
| 섹터 최소 크기 (M) | 10종목 | `strategy_b_multifactor.py` |

---

## 알려진 제약사항

1. **KRX 해외 IP 차단**: 2026-02-27~ 해외에서 pykrx 사용 불가. 국내 PC에서만 실행.
2. **백테스트 한계**: 생존 편향(상장폐지 미포함), 거래비용 단순화(0.3%), 슬리피지 미반영
3. **FnGuide 의존성**: 재무제표/컨센서스 데이터가 FnGuide 크롤링에 의존. 사이트 구조 변경 시 파서 수정 필요.
4. **단일 국가**: KOSPI/KOSDAQ 전용. 해외 주식 미지원.

---

## 버전 이력

| 버전 | 날짜 | 핵심 변경 |
|------|------|-----------|
| **v69** | 2026-03-20 | 4팩터 재설계 — Blom rank z-score, V25+Q25+G25+M25, K_ratio, FWD_PER 보너스, 진입72/퇴출68 |
| v68 | 2026-03-20 | 3팩터 체제 실험 (같은 날 v69로 대체) |
| v66 | 2026-03-19 | 거래대금 래그 수정 + 24일 증분 재계산 |
| v65 | 2026-03-18 | score-based 복원 + Death List Top20 통일 |
| v64 | 2026-03-14 | 신용·변동성 리디자인 (FRED/ECOS API) |
| v61 | 2026-03-12 | score-based entry/exit 도입 (EDA 62조합) |
| v56 | 2026-03-11 | V10/Q25/G35/M30 + ROE<0 하드게이트 |
| v46 | 2026-03-03 | 스크리닝 프레이밍 전환 |
| v45 | 2026-03-01 | 로컬 스케줄러 전환 (GitHub Actions -> Task Scheduler) |

상세 개발 히스토리: [SESSION_HANDOFF.md](SESSION_HANDOFF.md)

---

## 라이선스

Private repository. 무단 복제 및 배포를 금합니다.

---

*Generated by Claude Code | VolumeQuant/quant_py-main*
