# 한국 주식 퀀트 스크리닝 시스템

KOSPI/KOSDAQ 전종목 대상 **국면전환 멀티팩터** 퀀트 전략

매일 자동으로 ~300개 종목을 4팩터로 채점하고, 3일 연속 검증된 고점수 종목만 텔레그램으로 전송합니다.

> 채널: [@kr_dailyquant](https://t.me/kr_dailyquant) | 전략 버전: v80 | 최종 업데이트: 2026-04-18

---

## 시스템 한눈에 보기

```
전체 상장 (~2,770종목)
  ↓
시총 1000억+ / 거래대금 필터 / 우선주 제거
  ↓ (~800종목)
MA120 추세 필터 (126일 미만 제외)
  ↓ (~650종목)
데이터 품질 필터: DART 분기 8개+, 금융 제외, -1.5σ 극단값
  ↓ (~300종목)
4팩터 스코어링 (국면에 따라 비중 변경)
  ├─ 공격 모드: V15 + Q0 + G55 + M30
  └─ 방어 모드: V30 + Q15 + G15 + M40
  ↓
weighted_rank (3일 가중: T0×0.5 + T1×0.3 + T2×0.2)
  ↓
3일 교집합 (✅ 검증) → 진입: rank ≤ 3 / 퇴출: WR > 6
  ↓
텔레그램 3메시지 [Signal] [AI Risk] [Watchlist]
```

---

## 전략 상세 (v80)

### 국면전환 전략 — KP_MA170_8d

KOSPI가 170일 이동평균선 위에서 8거래일 연속 유지하면 **공격 모드**, 하회하면 **방어 모드**로 전환. 전환 시 기존 포트폴리오 전량 청산.

| 구분 | 공격 모드 (Boost) | 방어 모드 (Defense) |
|------|-------------------|---------------------|
| **조건** | KOSPI > MA170, 8일 확인 | KOSPI < MA170, 8일 확인 |
| **Value** | 15% | 30% |
| **Quality** | 0% | 15% |
| **Growth** | 55% | 15% |
| **Momentum** | 30% | 40% |
| **G 서브팩터** | 2f: rev_z 60% + oca_z 40% | 2f: rev_z 70% + oca_z 30% |
| **모멘텀** | 12m | 6m-1m |
| **진입** | rank ≤ 3 | rank ≤ 3 |
| **퇴출** | WR > 6 | WR > 6 |
| **슬롯** | 3 | 5 |
| **손절** | -10% | -10% |
| **트레일링** | -15% | -15% |

### Growth 서브팩터 (v80 핵심 변경)

v80에서 3팩터(rev+oca+gp_growth) → **2팩터(rev+oca)**로 변경.
- 매출총이익 성장(gp_growth_z) 제거 → 오히려 성과 개선
- 2팩터만 사용 → 잠정실적 공시 데이터와 PIT 호환

### 성과 (BT 재측정)

| 기간 | Calmar | CAGR | MDD |
|------|--------|------|-----|
| **7.8년** (2018-07~2026-04) | **3.86** | 138% | -35.7% |
| **5.25년** (2021-01~2026-04) | **4.37** | 113% | -25.9% |

Walk-Forward: min=2.92, mean=5.26, CV=0.35

### 데이터 소스 (DART 주도)

| 소스 | 역할 | 비중 |
|------|------|------|
| **DART** | 재무제표 (매출/영업이익/자산 등 16계정) | **87.7%** (주 데이터) |
| **FnGuide** | DART 누락 계정 보충 (130계정) | 12.3% (보충) |
| **pykrx** | PER/PBR/ROE, OHLCV, 시총, 섹터 | 시세/밸류 |

Growth 팩터 PIT: DART rcept_dt(실제 공시일) 기반 Point-in-Time 보장.

---

## 순위 체계

- `composite_rank`(cr): 당일 단독 순위. **판단 기준으로 안 씀.** wr 입력값.
- `weighted_rank`(wr): `cr_t0×0.5 + cr_t1×0.3 + cr_t2×0.2`. **모든 판단의 유일한 기준.**
- 점수 표시: `max(5, 100 - (wr - min_wr) × 5)` — 선형, 1등=100점
- 상태: ✅ 3일 검증 / ⏳ 관찰 / 🆕 신규

---

## 프로덕션 파이프라인

```
매일 16시 (평일, Task Scheduler):
  run_daily.py
    → Step 0: DART 증분 갱신
    → Step 0.1: FnGuide 증분 (DART 최근 공시 종목)
    → Step 0.3: OHLCV 신규 종목 증분
    → Step 0.5: 국면 판단 (KP_MA170_8d)
    → Step 1: FG 스코어링 (boost + defense 병렬)
    → Step 2: weighted_rank 후처리
    → Step 3: 텔레그램 전송
    → Step 4: git push state/
```

---

## 프로젝트 구조

```
quant_py-main/
├── [핵심 파이프라인]
│   ├── run_daily.py                 # 파이프라인 진입점
│   ├── regime_indicator.py          # 국면 판단 (KP_MA170_8d) + 파라미터
│   ├── data_refresher.py            # 시총/펀더멘털/OHLCV/섹터 캐시 갱신
│   ├── backtest/fast_generate_rankings_v2.py  # FG 스코어링 엔진
│   ├── ranking_manager.py           # weighted_rank, 진입/퇴출
│   ├── send_telegram_auto.py        # 텔레그램 3메시지
│   └── send_notice_once.py          # 국면 전환 공지
│
├── [데이터 수집]
│   ├── dart_collector.py            # DART API 수집
│   ├── refresh_dart_cache.py        # DART 증분 갱신
│   ├── data_collector.py            # pykrx 수집
│   ├── postprocess_fnguide_rcept.py # FnGuide rcept_dt 역추적
│   └── credit_monitor.py            # 시장 위험 지표
│
├── [AI 분석]
│   └── gemini_analysis.py           # Gemini 리스크 + 종목 내러티브
│
├── [백테스트]
│   ├── backtest/turbo_simulator.py  # TurboSimulator (5ms/run)
│   ├── backtest/v80_master_search.py # v80 VQGM 탐색 (5,652조합)
│   ├── backtest/v80_regime_step*.py # v80 국면 탐색 (352조합)
│   └── backtest/grid_search_final.py # 범용 그리드서치
│
├── [상태/데이터]
│   ├── state/                       # boost ranking JSON (git tracked)
│   ├── state/defense/               # defense ranking JSON
│   ├── backtest/bt_extended/        # 2018-2020 ranking
│   ├── data_cache/                  # DART/FnGuide/OHLCV 캐시
│   └── config.py                    # API 키 (.gitignore)
│
├── [문서]
│   ├── README.md                    # 이 파일
│   ├── CLAUDE.md                    # v80 전략 + 작업 원칙
│   ├── SYSTEM_MAP.md                # 영구 지도 (전략 교체 체크리스트)
│   └── PROVISIONAL_EARNINGS_RESEARCH.md # 잠정실적 연구
│
└── [출력 (.gitignore)]
    ├── logs/                        # 실행 로그
    └── output/                      # 포트폴리오 CSV
```

---

## 설치 및 실행

### 환경

- Python 3.10+ (conda 권장)
- Windows (Task Scheduler)

### 패키지

```bash
pip install pykrx pandas numpy requests beautifulsoup4 lxml pyarrow scipy google-genai yfinance opendartreader
```

### 실행

```bash
# 전체 파이프라인 (개인봇 테스트)
TEST_MODE=1 python run_daily.py

# 텔레그램만 (기존 ranking 사용)
TEST_MODE=1 python send_telegram_auto.py
```

### 스케줄러

- **일일**: 평일 16:00 (`QuanT_DailyPipeline`)
- **종목명 캐시**: 매주 월요일 09:00 (`QuanT_TickerRefresh`)

---

## 버전 이력

| 버전 | 날짜 | 핵심 변경 |
|------|------|-----------|
| **v80** | 04-18 | KP_MA170_8d + 2f(rev60+oca40) + Q=0 — 6,004조합 탐색, Phase5a 오류 수정 |
| v79 | 04-15 | KP_MA200_7d + FnGuide PIT — Cal3.23/3.44 |
| v77 | 04-09 | 3팩터G + 궤적wr변경 — Cal6.62 |
| v76 | 04-06 | KP_MA200_5d + CP제거 FG직접호출 |
| v75 | 04-05 | G서브팩터 최적화 + B126_40_3d |
| v74 | 04-04 | 국면전환 단일트랙 확정 |
| v73 | 04-03 | 투트랙 Core+Boost |
| v72 | 03-30 | DART 기반 전환 |
| v70 | 03-25 | rank기반 확정 |

---

## 라이선스

Private repository. 무단 복제 및 배포를 금합니다.

---

*Generated by Claude Code | VolumeQuant/quant_py-main*
