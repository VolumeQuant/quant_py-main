# 2026-05-13 저녁~05-14 오전 세션 인계 — v80.6 production 정련 + 5/15 폭주 대비

> 회사 PC가 출근 후 `git pull` + `config.py` Gemini 키 1줄만 동기화하면 바로 작업 가능.

## TL;DR

집 PC에서 v80.6 production 정련 작업 완료. 5/12·5/13 발송 채널+개인봇 모두 OK. 5/15 1Q 마감 폭주 대비 timeout 5시간 상향. 모자관계 분산 BT 검증 (baseline 유지). 코드/데이터/문서 모두 commit·push 됨.

---

## 작업 흐름 (시간순)

### 1단계 — 사건 발단 (5/13 19시)

5/13 16시 자동 실행 (회사 PC) 종료 후 집 PC가 19시 자동 실행 → ranking 종목수 **288/320 미달** → B 안전망(임계 320)이 데이터 사고로 오인하여 채널 발송 차단 → 5/12 새벽 v80 기준 채널 발송 1회만 도착, 5/13 자동 발송 미발생.

### 2단계 — 진단 (5/13 19~20시)

| 가설 | 실제 결과 |
|---|---|
| OHLCV 액면분할 복원 영향? | **무관**. 표본 16종목 검증 — 5/12 종가→5/13 종가 자연 약세로 MA120 아래 진입 |
| FnGuide stale 영향? | **점수 영향 0**. v80.6 G_SUB = `rev_z(DART) × 0.5 + oca_z(DART) × 0.5`. fnguide 비의존 |
| 데이터 사고? | **아님**. 시장 자연 약세 (universe 19개 거래대금 / ma120 16개 / score 11개 = 5/8→5/13 사라진 59개) |
| Gemini AI 누락? | **API 키 leak**으로 자동 비활성화 (403 PERMISSION_DENIED) |
| HY 지수 누락? | **7650일 캐시가 799일로 손상** (5/13 새벽 작업 부산물) |

### 3단계 — v80.6 정련 (5/13 20~22시)

**코드 변경**
- `run_daily.py` 종목수 임계 320 → **150** (line 708, 732) — 시장 자연 약세 흡수
- `send_telegram_auto.py` 매매 조건 문구 정련
  - 기존: "매수: 3일 검증 상위 2종목 중 5종목 / 매도: WR > 6 또는 -10% 손절 또는 트레일링 -8%"
  - 신규: "매수: 상위 2종목 (최대 5종목 보유) / 매도: 6위 밖 / 손절 -10% / 고점대비 -8%"
- `send_telegram_auto.py` cold start 안내 v80.6 갱신
- `send_notice_once.py` 국면 전환 안내 v80.6 갱신 (170일→250일, 슬롯 3/5→5/4, 트레일링 -15%→-8%, defense M40V30→M35V35)
- `refresh_fnguide_incremental.py` 전면 개편
  - DAYS cutoff 3 → 30 (FnGuide 사이트가 DART보다 며칠~수주 늦음)
  - mtime 비교 추가 (fnguide<dart 종목만, 이미 최신 스킵)
  - ThreadPool=2 + 종목당 30초 timeout (hang 보호)
  - 환경변수: `FNG_INCR_DAYS`, `FNG_TICKER_TIMEOUT`, `FNG_WORKERS`

**데이터 복원**
- `data_cache/hy_spread.parquet`: 7650일 → 799일로 손상되었던 캐시 복원
  - git d7f198504 commit에서 84KB 옛 캐시 추출 + 4/17~5/11 신규 16일 병합
  - 최종 **7666일 (1996-12-31 ~ 2026-05-11)** 복원 완료
  - 손상본 `hy_spread.parquet.bak_799d_corrupt` 보존 (검증용)
  - credit_monitor HY 분석 정상 작동 확인 (2.79% Q2 여름 8일째)
- `config.py` Gemini API 키 갱신 (이전 키 leak 보고됨, .gitignore라 git push 안 됨)

**Step A — FnGuide stale 일괄 보충 (5/13 22~22시 30분)**
- 1550 종목 (4/16 mtime이던 stale 누적분)
- 100% 성공, 23.4분 소요
- 이제 대부분 fnguide mtime이 dart 이후 → 다음 자동 실행 처리량 작음

**Step B — 5/12, 5/13 ranking 재생성 (5/13 22:30~22:36)**
- 새 fnguide 데이터 반영
- 5/12: boost 302 / defense 294
- 5/13: boost 288 / defense 281
- 종목수는 이전과 동일 (예상대로 fnguide stale은 점수 영향 0)

**Step C — 5/12 + 5/13 메세지 발송 (5/13 22:38~22:39)**
- 5/12 v80.6 기준: 채널 200 / 개인봇 200 (Signal 964자 / AI Risk 850자 / Watchlist 894자)
- 5/13 v80.6 기준: 채널 200 / 개인봇 200 (Signal 997자 / AI Risk 921자 / Watchlist 907자)
- AI 종목 근거, AI 시황 분석, HY 지수 모두 정상 표시

**Step D — 정리 + 문서 (5/13 22:40~)**
- 임시 디버그/regen/refresh 스크립트, log, 사용 후 파일 모두 제거
- memory 신규 3건
  - `project_20260513_evening_v806_polish.md`
  - `feedback_validation_threshold_static_market.md`
  - `feedback_data_cache_git_backup.md`
- CLAUDE.md에 v80.6 정련 섹션 추가
- HANDOVER_20260513_EVENING.md (이 문서)

**Step E — Commit + Push (5/13 23시)**
- `7acd10442` commit (1572 파일, 4184+ insertions)
- `89e580f42..7acd10442 main -> main` push 성공
- `config.py`는 .gitignore라 Gemini key 회사PC 별도 동기화 필요

**Step F — v80.6 성과 보고서 → 개인봇 (5/13 23시)**
- 7.4년 BT 1회 실측
- 결과: 누적 +23,916% (240배) / CAGR 110.6% / MDD -35.4% / Calmar 3.12
- 연도별 / 국면별 / 전환 횟수 / 공격·방어 전략 특징 / 안정성 모두 포함
- 중학생 이해 가능한 톤, 메시지 2개 발송 (1328자 + 1704자)
- 개인봇 200 OK (채널 X)

### 4단계 — 5/14 오전 추가 작업

**모자관계 분산 BT 검증**
- 동아엘텍-선익시스템 같은 모자관계 동시 매수 우려 검증
- 23그룹 수동 매핑 (LG/삼성/SK/현대/한화/두산/코오롱/CJ/GS/롯데/효성/한진/신세계/카카오 등)
- 4가지 시나리오 BT (7.4년):

  | 시나리오 | CAGR | MDD | Calmar | skip |
  |---|---|---|---|---|
  | baseline (분산X) | +110.6% | -35.4% | **3.12** | 0 |
  | 분산+점수1위 (모회사) | +111.4% | -35.4% | **3.14** | 8 |
  | 분산+G점수1위 (자회사) | +110.9% | -35.4% | 3.13 | 12 |
  | 옵션A strict (entry=3, 자리비움) | +89.2% | -33.6% | 2.65 | 24 |
  | 옵션A expand (entry=3 보장) | +70.4% | -33.2% | 2.12 | 46 |

- 결론: **baseline 유지** — 분산 도입 효과 +0.02 미미. 7.4년 동안 모자관계 동시 매수 case 8~12회만(매우 드뭄). 동아엘텍-선익시스템 동시 1·2위는 최근 8.6세대 OLED 폭증의 일회성. **매매 로직 변경 없음**.

**5/15 1Q 분기보고서 마감 폭주 대비**
- 2026 Q1 마감 = 5/15(금), D-1 시점에 fs_dart 등록 110/1971 (5.6%)만
- DART 직접 조회: 5/13 단일일 144건 폭증 시작 → 5/15에 200~400건 일제 제출 예상
- `run_daily.py:458, 468` subprocess timeout 10800s(3h) → **18000s(5h)** 상향
- 산정: DART 500종목 × 7초 ≈ 60분 이론치 + 안전 마진. 6시간은 너무 길어 19~20시 발송 차질 위험
- FnGuide 종목당 timeout 30초가 핵심 hang 보호선 (유지)

---

## 회사 PC 작업 절차 (출근 후)

```bash
git pull origin main
# config.py만 수동 동기화 — Gemini API 키 교체
# (집 PC에서 사용 중인 키 또는 새로 발급)
```

다음 자동 실행(평일 16시) 시 새 정책 자동 적용:
- 종목수 임계 150 (약세장 정상 흡수)
- DART/FnGuide subprocess timeout 5시간
- FnGuide refresh 30일 cutoff + mtime 비교 + ThreadPool 보호
- 메시지 문구 v80.6 정련

---

## 5/15(금) D-Day 모니터링 권장

- 16시 자동 실행 후 종목수 확인 (정상은 280~330)
- `monitor_dart_fn_health.py` 결과 확인 (DART vs FN baseline mismatch 임계 점검)
- 시총 1조+ 대형주 ranking 정상 진입 확인 (SG&A 매핑 버그 같은 사고 감지)
- 5/15 단일일 200~400건 DART 신규 → 5/16부터 fnguide refresh가 자동으로 따라옴 (30일 cutoff)

---

## 발송 완료 기록

| 날짜 | 시각 | 채널 | 개인봇 | 비고 |
|---|---|---|---|---|
| 5/12 (v80.6 기준) | 5/13 22:38 | 200 | 200 | 새벽 v80 기준 발송과 중복 |
| 5/13 (v80.6 기준) | 5/13 22:39 | 200 | 200 | AI 분석 + 시황 + HY 포함 |
| v80.6 성과 보고서 | 5/13 23:xx | - | 200 | 채널 X, 개인봇만 |

채널에 5/12자 메시지가 두 번 발송된 상태 (어제 새벽 v80 + 오늘 저녁 v80.6). 필요 시 수동 정리.

---

## 위험 신호 (앞으로 주의)

- 종목수 50개 이하로 폭락 시 = 진짜 캐시 손상 의심. 임계 150도 통과 안 됨
- `data_cache/hy_spread.parquet` 크기 갑자기 줄어들면 = 또 손상. git d7f198504에서 복원
- `[Gemini] AI 분석 실패: 403 PERMISSION_DENIED` 로그 = 키 leak. 즉시 재발급
- FnGuide refresh가 timeout 5시간으로 잡혀도 ThreadPool이 progress 찍어서 hang 즉시 보임
- 5/15 단일일 폭주 시 fs_dart 무결성 mismatch 모니터 결과 즉시 확인

---

## 변경 안 한 것 (BT 검증으로 의도적 유지)

- v80.6 알파 파라미터 (V/Q/G/M, G_REV, entry/exit/slots, SL/TS) — commit 89e580f42 그대로
- BT 결과 데이터 (bt_optf_*) — 변경 없음
- regime_indicator.py — 변경 없음
- 옵션 F 미적용 상태 그대로 (가짜 알파 폐기)
- 모자관계 분산 로직 — BT 검증 결과 효과 미미라 baseline 유지

### config.py (git push 안 됨, 수동 동기화 필요)
- `GEMINI_API_KEY` 갱신됨 — 회사 PC도 동일 키로 교체 필요
- 키 값은 집 PC에서 확인 후 동기화
