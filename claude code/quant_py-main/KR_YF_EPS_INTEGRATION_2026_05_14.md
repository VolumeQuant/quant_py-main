# KR 시스템 yfinance EPS 모멘텀 통합 검토 요청

> 작성일: 2026-05-14
> 작성 주체: US 프로젝트(`eps-momentum-us`) 세션
> 요청 대상: KR 프로젝트(`quant_py-main`, v80.6) 세션
> 목적: US의 EPS Revision Momentum 전략을 KR에 통합 가능한지 KR 시스템 관점에서 분석
> **업데이트: 488종목 심층 검증 완료 (시총 6,200억+ KOSPI 302 + KOSDAQ 186)**

---

## 배경

US 프로젝트(`C:\dev\claude code\eps-momentum-us`)의 EPS Revision Momentum 전략을 KR 종목에 적용 가능한지 검증. 30종목 표본 검증 후 488종목으로 확대해 시총 구간별 가용성/커버리지/staleness 패턴 등 심층 분석 완료. KR 시스템(v80.6 v80.6) 관점의 통합 분석이 필요.

---

## US 시스템 구조 (참고)

EPS Revision Momentum 전략 핵심:

- yfinance `eps_trend`의 5 스냅샷(`current`/`7daysAgo`/`30daysAgo`/`60daysAgo`/`90daysAgo`) × 2 FY(`0y`, `+1y`)
- `_earnings_trend.endDate`로 시간 가중 블렌딩 → NTM EPS 계산
- 5 스냅샷 간 변화율 → 4 segment score → conviction
- `eps_revisions.upLast30days`/`downLast30days` → rev_up30/rev_down30
- 진입: 3일 가중 z-score Top 3 + ✅(3일 검증) + min_seg ≥ 0
- 이탈: Top 10 밖 OR min_seg < -2%
- 슬롯: 3, 균등비중
- 가중치 v80.10b: 7d 0.30 / 30d 0.10 / 60d 0.10 / 90d 0.50 (90d long-tail 강조)

핵심 함수:
- `eps_momentum_system.py:calculate_ntm_eps()` — NTM 계산 (line 285)
- `eps_momentum_system.py:calculate_ntm_score()` — segment score (line 364)

---

## 488종목 심층 검증 결과

표본: KR 프로젝트의 `market_cap_ALL_20260319.parquet` 시총 상위 500종목 중 보통주 488개 (우선주 끝자리≠0 제외). 시총 분포: 6,200억~1,187조원.

### 1. 시장 분포

| 시장 | 종목수 | 비율 |
|---|---|---|
| KOSPI (.KS) | 302 | 62% |
| KOSDAQ (.KQ) | 186 | 38% |

### 2. 전체 가용성

| 항목 | 비율 | 비고 |
|---|---|---|
| `eps_trend` 존재 | 488/488 (100%) | 모든 종목 응답 있음 |
| 0y FY 5스냅샷 완전 | 371/488 (76%) | 시스템 입력 충족 |
| +1y FY 90d→current 완전 | 365/488 (75%) | NTM 블렌딩 가능 |
| `endDate 0y` | 452/488 (93%) | |
| `endDate +1y` | 370/488 (76%) | 시간 가중 블렌딩 가능 |
| `eps_revisions` 0y | 371/488 (76%) | rev_up30/down30 매핑 가능 |
| `numAnalysts ≥ 3` | 260/488 (**53%**) | US 진입 임계 |
| `numAnalysts ≥ 5` | 208/488 (43%) | |
| `revenueGrowth` 존재 | 399/488 (82%) | |
| `operatingMargin` 존재 | 431/488 (88%) | |
| `Earnings Date` 캘린더 | 107/488 (22%) | ❌ 어닝일 부정확 |

### 3. 시총 구간별 가용성 cliff (★ 핵심)

US 시스템 진입 기준(FY 완전 + na≥3) 적용 시 실효 종목 비율:

| 시총 구간 | 종목수 | FY 완전 | na≥3 | **FY+na≥3** |
|---|---|---|---|---|
| 10조+ | 73 | 99% | 95% | **95%** |
| 5~10조 | 44 | 89% | 86% | **86%** |
| 1~5조 | 242 | 74% | 50% | **50%** |
| 5천억~1조 | 129 | 64% | 26% | **26%** |

**Cliff 위치 명확**: 1~5조 구간부터 커버리지 급락. 5천억 이하는 단일 분석가 의존 위험으로 사실상 제외 영역.

### 4. 분석가 커버리지 분포

| 통계 | 값 |
|---|---|
| 존재 종목 | 356/488 (73%) |
| min / max | 1 / 38 |
| p25 / median / p75 | 2 / 7 / 15 |
| 평균 | 9.5 |

**히스토그램**:
```
1~2명  : 96 ██████████████████████████████████████████████████████████████
3~5명  : 63 ████████████████████████████████████████
6~10명 : 59 █████████████████████████████████████
11~20명: 96 ██████████████████████████████████████████████████████████████
21~99명: 42 ██████████████████████████
```

**양극화 패턴**: 1~2명(저커버리지) 또는 11~20명(고커버리지) 양쪽으로 집중. 미국 S&P500/NQ100과 유사한 분포.

### 5. NaN 패턴 — 정직한 all-or-nothing

| 5스냅샷 가용 | 종목수 |
|---|---|
| 0/5 (없음) | 117 |
| 1~4/5 (부분) | **0** |
| 5/5 (완전) | 371 |

**부분 결측 없음**. yf는 KR 종목에 대해 데이터 주거나 안 주거나 둘 중 하나. 시스템 적용 시 누락 데이터 처리 로직 단순함.

### 6. revenueGrowth 분포 (KR 특화 이슈)

| 통계 | 값 |
|---|---|
| 존재 | 399/488 (82%) |
| min / max | -100% / 9,920% |
| p10 / median / p90 | -15% / 7% / 61% |
| \|값\| > 500% (비정상) | 3/399 (0.8%) |

→ US 시스템의 `income_stmt 재검증` 로직(v71.2, `_fetch_one()` 내부)을 KR에도 적용 필요. 다만 비정상 비율 1% 미만이라 영향 작음.

### 7. 어닝 점프 detection 가능성

90d→current 큰 변화 = 어닝 비트/미스 detect 가능.

| 변화 | 종목수 |
|---|---|
| detect 가능 (NaN 아님) | 346/488 (71%) |
| **+50% 이상 상향** | **24** |
| -50% 이하 하향 | 15 |

**Top 5 상향 (어닝 비트 candidates)**:
- 086520.KQ ECOPRO +198% (단 na=1, 신뢰성 낮음)
- 096770.KS SK Innovation +179% (na=21)
- 009420.KS HANALL BIOPHARMA +137% (na=4)
- 010950.KS S-Oil +122% (na=18)
- 002380.KS KCC +105% (na=4)

KR 시스템에서 BE/SNDK 같은 어닝 비트 케이스 detect 가능. 단 KOSDAQ 소형(ECOPRO 등)은 na 1명이라 시스템 진입 필터에서 탈락.

### 8. ★★★ yf staleness 패턴 — US와 동일하게 작동

**핵심 발견**: US 시스템 알파의 일부인 "yf staleness가 만드는 어닝 후 lock-in 효과"가 **KR 종목에서도 동일하게 발생**.

| staleness 패턴 | 비율 |
|---|---|
| 7d ≈ 30d (값 동일) | **138/371 (37.2%)** |
| 30d ≈ 60d (값 동일) | 132/371 (35.6%) |
| 7d = 30d = 60d 모두 동일 | **80/371 (21.6%)** |

**의미**:
- yf가 KR 종목 대해서도 `7daysAgo`/`30daysAgo` 컬럼을 stale하게 유지하는 케이스가 **37%** (약 1/3)
- 5분의 1 종목(21.6%)은 7d/30d/60d 세 컬럼이 모두 같은 값 — 즉 yf가 최근 데이터 갱신 후 한 번에 정정하는 패턴
- 선익시스템 사례(0y: 8910/8773/8773/8773/5795)가 **일반적인 패턴**

**US와의 비교**:
- US BE 사례: yf의 `7daysAgo` 컬럼이 어닝 후 14일간 stale → 어닝 후 cr=1 lock-in → yf 정정 시 매도 신호 → 익절 회전
- KR도 같은 메커니즘 작동할 가능성 **매우 높음**
- 즉 US가 검증한 staleness 알파를 KR에서도 일부 활용 가능

**caveat**:
- 7d=30d 동일 비율이 어닝 후 lock-in의 직접 증거는 아님 (yf의 일반적 갱신 패턴)
- 실제로 BE/SNDK급 어닝 비트가 KR 종목에서도 같은 lock-in 효과를 만드는지는 별도 BT 필요
- 단 메커니즘 가능성은 충분히 입증됨

### 9. 시스템 적용 시나리오별 실효 종목 수

| 시나리오 | 조건 | 종목수 | 비율 |
|---|---|---|---|
| **A (US 동일)** | FY완전 + endDate + revisions + na≥3 | **260** | 53% |
| B (완화) | FY완전 + na≥2 | 302 | 62% |
| C (최소) | FY완전 | 371 | 76% |

488 표본 기준. 더 넓은 유니버스(KR ~2,300 종목)로 확장 시 절대 종목 수 늘어나지만 비율은 떨어질 가능성 (소형주 비중↑).

### 10. KOSPI vs KOSDAQ 차이

| 시장 | n | FY완전 | na≥3 | avg na |
|---|---|---|---|---|
| KOSPI | 302 | 259 (86%) | 204 (68%) | **11.1** |
| KOSDAQ | 186 | 112 (60%) | 56 (30%) | **5.3** |

**KOSPI > KOSDAQ in 가용성 + 커버리지**. KOSDAQ는 KOSPI의 절반 수준 분석가 커버리지.

### 11. 실패 종목 패턴 (~40종목)

`HTTP 404 No fundamentals data`로 응답한 종목들:
- 015750.KS, 287840.KS, 042000.KS, 365340.KS 등 ~40종목
- 신규 상장 (산일전기 062040 패턴)
- 또는 yf 데이터베이스 미갱신 (한미반도체 042700 — 큰 종목이지만 404)
- 합병/상장폐지 종목

→ 시스템 적용 시 404 처리 로직 필요 (retry + cache)

---

## yfinance KR 특이점 (US 대비)

- ❌ `calendar.Earnings Date` 22%만 가용 (US는 거의 100%) — 정확한 어닝일 못 가져옴 → DART 공시일로 보완 필요
- ❌ `forwardEps`/`trailingEps` None — 분기 EPS 없음 (FY 단위만)
- ⚠️ `earnings_dates` 옛 데이터 비중 높음
- ⚠️ `revenueGrowth` 일부 종목 비정상 큰 값 (0.8%) — `quarterly_income_stmt` 재검증 권장
- ✅ `eps_trend`/`eps_revisions`/`_earnings_trend.endDate`는 US와 동일 구조
- ✅ staleness 패턴도 US와 동일

---

## KR 적용 시나리오 (3안)

### 옵션 A — 보수적 PoC
- 유니버스: 시총 5천억+ KOSPI + KOSDAQ ≈ 488종목 → 실효 260종목 (53%)
- US 시스템 룰 그대로 적용 (가중치/필터/슬롯 동일)
- BT로 알파 측정 후 KR 특화 조정

### 옵션 B — 광역 적용
- 유니버스: KOSPI + KOSDAQ 시총 1천억+ (~1,500종목)
- `num_analysts ≥ 2`로 임계 완화 (US는 3)
- KOSDAQ 중소형 포함, 단일 분석가 의존 위험
- KR 특화 BT 필수

### 옵션 C — 기존 v80.6에 보조 신호로 통합 (★ 권장)
- 기존 v80.6의 G 팩터(rev_z + oca_z) 옆에 yf EPS 모멘텀 점수 추가
- 가용 종목(488 중 260, 53%)에만 보충 신호로 사용
- 기존 알파 깨지 않음
- staleness 알파를 v80.6에 자연스럽게 통합 가능

---

## KR 시스템 입장에서 분석 필요한 질문

1. **DART/FnGuide rev_z와 yf eps_trend rev 신호의 정합성**
   - 두 데이터 소스가 같은 어닝 비트를 다르게 반영하는지
   - DART 공시일 vs yf 컨센서스 갱신일 시점 차이
   - HANALL/SK Innovation/S-Oil 등 yf top 상향 종목이 DART 기반 v80.6 G 팩터에서도 상위인지 비교

2. **기존 v80.6 알파 vs yf 모멘텀 알파 중복도**
   - 같은 어닝 비트 종목을 두 시스템이 동시 픽하는지
   - 보조 신호로 통합 시 알파 추가분 vs 중복

3. **분석가 커버리지 cliff 대응**
   - 1~5조 구간에서 na≥3 비율 50% → 절반은 자동 탈락
   - 5천억~1조 구간은 26%만 진입 → 사실상 제외
   - v80.6 유니버스의 이 영역 비중이 얼마이며, 어떻게 보완할지 (DART 단독 시그널?)

4. **국면전환과의 호환성**
   - v80.6은 공격(KOSPI > MA250) vs 방어 모드 전환
   - US EPS 모멘텀은 국면 무관 단일 룰
   - 공격 모드에만 yf 모멘텀 추가? 또는 양쪽?

5. **장세 의존성**
   - US 시스템은 강세장 60일 데이터로 검증됨
   - KR 7.4년 BT(2019~2026)에서 약세장(2022) 포함 — 약세장에서 yf 모멘텀 신호의 노이즈/잡음 평가
   - KR이 보유한 historical eps_trend 데이터 가용성 (yf는 보통 90일치만 — DB 누적 필요)

6. **yfinance staleness 메커니즘 (★중요)**
   - US 메모리 `project_yf_staleness_alpha.md` 참고
   - DB-NTM lookback 정정 시도 paired BT -12~-30%p 손실 (0~1/6 wins)
   - 어닝 후 매도 유예 시도도 실패 (7~14d 0%p, 21d -27%p)
   - **KR에서 staleness 비율 37% (US와 유사) → 같은 알파 메커니즘 작동 가능성 높음**
   - 다만 KR BT에서 직접 측정 필요

7. **404 종목 비율**
   - 488 중 ~40종목 (8%) HTTP 404
   - 한미반도체(042700) 같은 큰 종목도 일시 404
   - retry/cache 메커니즘 + DART 폴백 필요

---

## 검증 도구

US 프로젝트 검증 스크립트 (그대로 KR로 옮겨 실행 가능, yfinance 의존만 있음):

| 파일 | 용도 |
|---|---|
| `C:\dev\claude code\eps-momentum-us\research\kr_yf_single_probe.py` | 단일 종목 raw 데이터 확인 |
| `C:\dev\claude code\eps-momentum-us\research\kr_yf_sample_availability.py` | 30종목 빠른 가용성 통계 |
| `C:\dev\claude code\eps-momentum-us\research\kr_yf_deep_probe.py` | 시총 상위 500종목 풀 수집 (CSV) |
| `C:\dev\claude code\eps-momentum-us\research\kr_yf_deep_analyze.py` | 시총/커버리지/NaN/staleness 분석 |

결과 CSV: `C:\dev\claude code\eps-momentum-us\research\kr_yf_deep_results.csv` (488 rows)

---

## 권장 시작점

**옵션 C (보조 신호 통합)으로 PoC 시작 권장**:
1. 488종목 결과 CSV를 KR 프로젝트로 import
2. 같은 종목을 v80.6 G 팩터로 점수 매기고 yf 모멘텀 점수와 cross-correlation 측정
3. 중복도 낮으면(<0.7) 보조 신호 추가 가치 있음 → BT
4. 중복도 높으면 두 신호 중 어느 쪽이 더 강한지 신호 품질 비교

다만 이 판단은 KR 프로젝트 컨텍스트(v80.6 알파 구조, 데이터 인프라)를 가진 클로드가 더 정확히 할 수 있음.

---

## 검토 과정에서 참고할 US 메모리

`C:\Users\user\.claude\projects\C--dev-claude-code-eps-momentum-us\memory\`

- `project_yf_staleness_alpha.md` — yf staleness가 알파 원천이라는 발견. DB-NTM lookback 시도 실패. 어닝 유예 시도도 실패 (별도 BT 수행, 채택 안 함).
- `feedback_db_first.md` — 외부 API 호출 전 DB 구조부터 확인
- `feedback_clear_explanation.md` — 분석 결과 명료 설명

---

## 직전 US 세션 발견 요약

1. BE(Bloom Energy) 5/12→5/13 cr 2→56 폭락 분석에서 yf staleness 발견
2. DB-NTM lookback 정정 시도: paired 0~1/6 wins, -12~-30%p 손실 → 채택 불가
3. 어닝 후 매도 유예 시도: 7~14일 0%p, 21일 -27%p → 채택 불가
4. 결론: **현재 시스템 알파 일부가 yf staleness가 만드는 "어닝 후 lock-in" 효과에 의존**
5. **KR 적용 검토 시 같은 메커니즘 작동/불작동 여부가 핵심 — 488종목 분석에서 staleness 비율 37% 확인, 메커니즘 작동 가능성 높음**

---

## 핵심 결론 (한 문장)

**KR 시총 5천억+ 종목 중 53%(260개)가 US 시스템 룰 그대로 적용 가능하며, yf의 staleness 패턴(37%)도 US와 유사해 staleness 알파 메커니즘도 작동할 가능성이 높음. 단 KOSDAQ 소형(시총 5천억~1조) 영역은 커버리지 부족(na≥3 26%만)으로 시스템 자동 탈락하므로 DART 단독 신호로 보완 필요.**
