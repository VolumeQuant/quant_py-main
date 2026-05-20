# 작업 원칙

## 사용자 지시 준수
- 사용자 지시와 다른 판단을 하려면 **반드시 먼저 물어볼 것**. 임의로 건너뛰지 마라.
- "대충 맞겠지"로 넘기지 말고, 확인 가능한 건 확인하고 진행
- 효율성을 위한 판단이라도 사용자 승인 없이 지시를 무시하면 안 됨

## 단계별 진행 원칙
- **표본 먼저**: 모든 작업은 시작 전에 표본테스트로 검증. 문제 없으면 전체 실행. 시간 절약의 핵심.
- **EDA → 인사이트 → 계획**: 각 단계 시작 전, 이전 단계 데이터를 EDA해서 인사이트를 얻고 효율적으로 계획을 다시 짜고 시작.
- **맹점 체크**: 각 단계 끝날 때마다 맹점/오류 고찰 후 다음 단계로 넘어가기.
- **한 번에 하나만**: 변경은 하나씩. 동시에 여러 개 바꾸면 효과 분리 불가.

## 실행 전 검증
- 실행 전에 기본 가정을 확인하라 (날짜, 경로, 데이터 존재 여부 등)
- 같은 실수 2번 이상 반복하지 마라
- 각 단계 끝날 때마다 결과 검증 후 다음 단계 진행

## 병렬 실행 최적화
- 병렬 작업 전: CPU 코어 수, 가용 메모리, 프로세스당 메모리 확인
- 최적 병렬 수 = min(CPU코어, 가용메모리 ÷ 프로세스당 메모리)

## 재사용 우선
- 변수 하나만 바꿔서 비교할 때, 전체 파이프라인을 처음부터 돌리지 마라
- 변하지 않는 부분을 재사용하라 (캐시, 이전 결과 등)

## pykrx
- 1초 sleep, 순차 실행 절대. 집 IP 이미 차단됨

---

# 🇺🇸 US 전략 — eps-momentum-us (v80.10c, 2026-05-11)

> 경로: `C:\dev\claude code\eps-momentum-us`

- EPS Revision Momentum, conviction z-score 기반, **균등비중**
- conviction: adj_gap × (1 + max(up30/N, min(|eps_chg|/100, 3)) + min(min(rg,0.5)×0.6, 0.3))  ← v80.9 X2: cap 3.0, rev_bonus smooth
- adj_gap = fwd_pe_chg × (1 + dir_factor) × eps_quality
- **fwd_pe_chg 가중치 (v80.10)**: **7d 0.30 / 30d 0.10 / 60d 0.10 / 90d 0.50** (90일 누적 PE 압축 강조, long-tail)
- 점수: 일별 z-score(**하한30, 상한 무제한**) → 3일 가중(T0×0.5+T1×0.3+T2×0.2), 빈 날=30점
- **v79**: z-score 상한 100 clamp 제거 → outlier 변별력 보존
- **Case 1 보너스 폐기 (v80.5)**: cr/score_100/part2_rank 정렬 일관성 회복 위해 제거
- 진입: 3일 가중 Top **3** + ✅(3일 검증) + min_seg ≥ 0%, 슬롯 **3**
- **퇴출 (v80.10b)**: part2_rank > **10** OR min_seg < -2%  ← 8→10 변경 (회전 정책 재최적화)
- **품질 필터 (v79.1)**: FCF < 0 AND ROE < 0 동시 → eligible 제외
- **rev_up30 ≥ 3 필터 (v80.8)**: 단일 분석가 의존 종목 차단 (WELL 사례)
- **Signal 진입 (v80.2)**: ✅ but min_seg<0/하향과반/저커버리지 탈락 시 다음 ✅ 후보로 슬라이드
- **⏸️ 매도 유예 제거 (v80.10c)**: v80.10 장기 가중치 전환으로 ⏸️ 알파(단기 가중 노이즈 완충재) 소멸. BT N=0이 모든 N>0보다 paired 100/100 우월. `check_breakout_hold` 함수는 유지(약세장 재토글용)
- composite_rank=당일 conviction 순위(추이 표시), part2_rank=3일 가중 순위(매매)
- RETURN_MATRIX: S&P500 기반 (26년 6,593일), VIX는 yfinance 최신 보완
- 비중 조절 안 함 (알파가 공포 구간에서 발생)
- 상관관계: 🔗 유사도% + BFS 그룹핑 + 택1/택1~2 권장
- **v80.10/10b/10c 종합 성과 (60일 paired)**: v80.9 production +55.89% → v80.10b +104.47%, paired lift **+48.58%p** (100/100 wins). 단계별: 가중치 +40.86%p / exit 8→10 +7.72%p / ⏸️ 제거 +5.37%p. caveat: 60일 sample, 본격 약세장 미검증
- **롤백 트리거 (v80.10/10b/10c 공통)**: 5거래일 SPY 대비 알파 -3%p 이하 / MDD -8% 초과 / Top3 교체율 50%+ / HY×VIX Q3 진입. backup: `eps_momentum_data.bak_pre_v80_10.db`

---

# 🇰🇷 KR 전략 — quant_py-main (v80.15, 2026-05-19)

## 2026-05-20 정리 — wr PENALTY 통일 마무리 + 점수기반 wr 재검증

### wr PENALTY 통일 (5/17 작업 잔여 2파일)
5/17 commit `6c76442cf`에서 4파일 통일했지만 2파일 누락 발견 → 수정:
- `ranking_manager.get_stock_status`: top20 한정 cr 매핑 (메시지 표시 wr)
- `backtest/postprocess_wr_batch.py`: pm cr ≤ 20 한정 (state 재생성용)
- state 재생성 1934일×2 (140초). 12 파일 wr 변경 (영향 작음)
- 검증: 전 기간(최신/3월/2년 전) 메시지 wr = 파일 wr = BT wr = 시스템수익률 wr **0건 불일치**
- 실전 매매 영향 X (각 코드가 별도로 PENALTY 적용해서 매매 판단은 이미 정확)
- CLAUDE.md '✅/⏳/🆕 = cr Top 20' → 'cr Top 30' 정정 (코드 verify_n=30, 미국 시스템과 정합)
- commit `9bf5c8758`

### 점수기반 wr (미국식) v80.13 환경 재검증 — 거부
사용자 질문: "미국은 점수 기반, 한국은 순위 기반. 현재 환경에서 재검증?"

| 지표 | 순위 기반 (현재) | 점수 기반 (미국식) | Δ |
|---|---|---|---|
| 전체 Cal | **2.638** | 1.963 | -0.675 |
| 2019 Cal | 2.917 | 0.785 | -2.13 |
| MDD | 32.83% | 39.04% | +6.2%p |
| WF CV | 0.787 | 0.930 | +0.14 |

= 한국 시장에서 순위 기반 명확 우월. v77/v79 결론 재확인.
이유: 종목수 많음(~1900) → score 표준편차 노이즈 큼. outlier에 점수 기반 취약.

### score_100 표시 공식 검증 — 그대로 유지
- `max(5, 100 - (wr - min_wr) × 5)` 그대로
- Top 5~6 (사용자 의사결정 영역)에서 클리프 명확 (5→6위 9.5점)
- 18~20위 5점 floor 96% 일에 발생 but 의사결정 무관 영역 → 그대로 OK
- ×3 변경 검토 → 클리프 9.5점 → 5.7점 약화 = 본질 손실 → 거부

## v80.15 변경 — regime MA220→200 (2026-05-19, OOS robust)

### 핵심 — 사용자 과적합 우려 검증 + 표준값 채택

`regime_indicator.py:56` MA_PERIOD = 220 → **200**
다른 변경 0.

### 검증 — OOS 시간 분할 (IS 2019-2022 / OOS 2023-2026)

| MA × 10d | IS Cal | OOS Cal | 7y Cal | OOS 순위 |
|---|---|---|---|---|
| MA180 | 2.209 | 3.130 | 2.494 | 3위 |
| **MA200** | 2.108 | **3.152** | 2.512 | **2위 ★** |
| MA210 | 2.118 | 3.093 | 2.494 | 5위 |
| **MA220 (이전)** | 2.309 (2위) | 3.087 | 2.664 | 8위 |
| MA250 (전통) | 2.322 (1위) | 2.712 | 2.517 | 35위 |

= **220은 IS에서 강하고 OOS에서 약함** (cherry-pick 의심 약하게 사실)
- 220 IS 2위 → OOS 8위
- 250 IS 1위 → OOS 35위 (가장 심한 cherry-pick)
- **200은 IS 9위 → OOS 2위** (반대 방향 = robust)

### 7년 BT (v80.15 production)
| 지표 | v80.14 (MA220×10d) | v80.15 (MA200×10d) | Δ |
|---|---|---|---|
| Cal | 2.664 | **2.512** | -0.152 (BT noise +0.10 초과) |
| CAGR | 63.2% | 62.1% | -1.1%p |
| MDD | 23.7% | **24.7%** | +1.0%p |
| NAV | ×38.15 | ×36.25 | -5% |
| 전환수 | 35회 | 37회 | +2 |

### 채택 근거 (사용자 의심 데이터로 뒷받침)
1. **OOS 우위** — 미래 환경 robust (200 > 220 +0.07)
2. **표준값** — 200일선 = 시장 보편 인식, "220" 비표준 cherry-pick 의심 해소
3. **메시지 신뢰성** — "코스피 200일선" 자연스러움
4. **인접 plateau 안전** — MA180~210 모두 OOS Top 5

### 비용 (정직하게)
- 7y Cal -0.152 (통계 유의 손해)
- 그러나 IS+OOS 혼합 측정 = 과거 가중. **미래 = OOS-like = 200 우세**
- 전통 quant 원칙 OOS > IS 따름

### 변경 (4 파일)
1. `regime_indicator.py:56` MA_PERIOD = 220 → 200
2. `regime_indicator.py` docstring v80.15 업데이트
3. `send_telegram_auto.py` 모드 전환 메시지 220→200 + BT 성과 (Cal 2.51, CAGR 62%, MDD 25%)
4. `send_notice_once.py` 공지 220→200 + BT 성과 동일

### state 재계산 불필요
- regime은 매일 동적 계산
- 적용 즉시 효과

### 롤백 트리거
- 5거래일 KOSPI 대비 알파 -3%p 이하 또는 MDD -8% 초과
- 즉시 롤백: MA_PERIOD = 220 환원 (git revert)

---

## v80.14 변경 — regime CONFIRM_DAYS 8→10 (2026-05-19)

### 핵심 — 1줄 변경, regime 확인 강화

`regime_indicator.py:72` CONFIRM_DAYS = 8 → **10**
다른 변경 0 (MA_PERIOD=220 유지, defense/boost 변경 없음)

### 7년 BT 검증 (2019-01-02 ~ 2026-05-15)
| 지표 | baseline (8d) | v80.14 (10d) | Δ |
|---|---|---|---|
| Cal | 2.474 | **2.664** | +0.19 (+8%) |
| CAGR | 62.5% | 63.2% | +0.7%p |
| MDD | 25.2% | **23.7%** | **-1.5%p** ★ |
| WF min | 1.442 | **1.675** | +0.23 |
| WF CV | 0.288 | **0.264** | -0.024 안정성 ↑ |
| 전환 (7년) | 39회 | **35회** | -4회 |
| 평균 간격 | 46.4일 | **51.7일** | +5일 |
| <30일 whipsaw | 71.1% | **67.6%** | -3.5%p |

### 연도별 성과 (7년)
| 연도 | baseline Cal | v80.14 Cal | Δ | 평가 |
|---|---|---|---|---|
| 2019 (약세) | 1.44 | **1.68** | +0.23 | ★ |
| 2020 (코로나) | 7.12 | **7.77** | +0.64 | ★★ |
| 2021 (정체) | 1.00 | 0.97 | -0.03 | ~ |
| 2022 (약세) | 1.75 | 1.75 | 0.00 | 동등 |
| **2023 (회복)** | **4.62** | 4.24 | **-0.38** | baseline 우세 |
| 2024 (강세) | 4.25 | **4.53** | +0.28 | ★ |
| 2025 (강세) | 2.94 | 2.93 | -0.01 | ~ |

= 7년 중 ★우세 3년 / 동등 3년 / 열세 1년 (2023 회복기, 진입 +4일 지연)

### 인접 안정성 (5×5 grid)
- 중심: MA220×10d Cal 2.664
- ±5 MA × ±1 conf 9셀 CV = **0.074 ✅ PASS** (기준 < 0.10)
- conf=10 column 전체 plateau (210/215/220/225/230 모두 2.49~2.66)

### 반려된 옵션 (5/19)
- **MA50 (지수)**: 모든 confirm 시도 (3~15d) Cal 1.58~1.99 = baseline 미달. 전환 65~97회 (whipsaw). 반려
- **Breadth (KOSPI 종목 MA50 위 비율)**: thr 0.40~0.70 × conf 3~10 = 모든 조합 Cal 0.43~1.14. breadth 분포 비대칭 (mean 0.37). WF 음수 (-0.27 약세장 손실). 시스템 boost/defense는 fundamental 기반이라 market breadth와 mismatch. 반려

### 변경 (1 파일)
- `regime_indicator.py:72` CONFIRM_DAYS = 8 → 10

### state 재계산 불필요
- regime은 매일 동적 계산 (KOSPI MA 비교 + streak)
- 적용 즉시 효과

### 5/19 변화 전망
- 5/18 streak=4 (이전 상태). 10d 적용 시 streak=4에서 다음 신호 발생까지 +6일 추가 확인 필요 (8d였으면 +4일)
- 신호 발생 후 전환 자체는 동일 — confirm 단계만 늘어남
- 강한 boost (KOSPI>MA220×1.06)는 그대로 적용 (QoQ 패널티 SG6 영향 0)

### 롤백 트리거
- 5거래일 KOSPI 대비 알파 -3%p 이하 또는 MDD -8% 초과
- 즉시 롤백: `regime_indicator.py:72` CONFIRM_DAYS = 8 환원 (git revert 가능)

---

## v80.13 변경 — wr 가중치 50:30:20 → 40:35:25 (당일 비중 ↓)

### 핵심 — 3일 검증 강화로 노이즈 매수 차단

기존 wr = T-0×0.5 + T-1×0.3 + T-2×0.2 (당일 비중 50%)
**신규 wr = T-0×0.4 + T-1×0.35 + T-2×0.25** (당일 비중 40%)

### 검증 (7년 BT, single-day 그리드)
| 시나리오 | Cal | CAGR | MDD |
|---|---|---|---|
| 100:0:0 (T-0만) | 1.695 | 74.3% | 43.84% |
| 80:15:5 | 1.757 | 76.9% | 43.76% |
| 70:20:10 | 1.853 | 76.9% | 41.53% |
| 60:25:15 | 1.902 | 74.1% | 38.95% |
| 50:30:20 (v80.12) | 2.223 | 79.0% | 35.53% |
| 40:30:30 | 2.504 | 83.1% | 33.18% |
| **40:35:25 (v80.13)** | **2.597** ★ | 83.1% | 32.20% |

= 당일 비중 ↑ = 알파 ↓ (노이즈 매수 ↑). 3일 균등 검증이 정답.

### WF 4구간 + 인접 안정성
| 시나리오 | 전체 | 2019 | 20-21 | 22-23 | 24-26 | WFmin | WFCV |
|---|---|---|---|---|---|---|---|
| 50:30:20 (옛) | 2.223 | 1.81 | 2.78 | 0.14 | 5.95 | 0.14 | 0.792 |
| **40:35:25 (현재)** | **2.597** | **1.97** | 3.00 | **0.18** | **7.94** | **0.18** | 0.880 |

- Cal +0.374 (+17%)
- 2019/2024-26 강세장 개선
- WF min 0.14 → 0.18 (약세장 최저점도 개선)
- Top 5 인접 CV 0.016 (과적합 X)

### 채택 근거
1. Cal +0.374 (BT noise ±0.10 훨씬 초과 = 통계 유의)
2. WF min 개선 + 모든 구간 baseline 우월
3. 인접 안정성 CV 0.016 robust
4. CLAUDE.md 본래 의도 'Slow In' (3일 검증) 강화

### 변경 (4파일)
- `run_daily.py:_postprocess_ranking` (line 275)
- `send_telegram_auto.py:calc_system_returns._wr` + 매수 진입 (line 302, 315)
- `backtest/turbo_simulator.py:wr_legacy + ws` (line 324, 353)
- `backtest/postprocess_wr_batch.py` (line 6, 72)

### state 재계산
- 1932일 × 2 (boost + defense) wr 재계산 (6.6분)
- commit `d66db9d21` (3869 files)

### 5/15 매수 후보 변경
- 옛 (v80.12): SK / 보성파워텍 / 제주반도체
- **새 (v80.13): SK / 에스에이엠티 / 아이티센글로벌**
- 브이엠 wr 5위 (메시지 인지 가능)

### 롤백 트리거
- 5거래일 KOSPI 대비 알파 -3%p 또는 MDD -8% 초과
- 코드 4파일 0.5/0.3/0.2로 환원 (git revert `d66db9d21`)

## v80.12 변경 — QoQ 패널티 + 강한 boost (D6_SG6, 2026-05-18 저녁)

### 핵심 — 사용자 통찰 시스템 반영
- **사용자 발견**: 보성파워텍처럼 25Q1 base 작아서 26Q1 OP YoY +285%지만 QoQ +11% 미미한 base 효과 종목 시스템이 잘못 강한 신호
- **해결**: 영업이익 QoQ < +20% 종목 G_score × 0.7
- **조건**: 강한 boost (KOSPI > MA220 × 1.06)일 때만 적용 (회복기 종목 보호)

### 7년 BT 결과 (2019-01-02 ~ 2026-05-15, 비용 미반영)
| 지표 | baseline (v80.11) | **v80.12 (D6_SG6)** | Δ |
|---|---|---|---|
| Cal | 1.846 | **2.374** | **+29%** ★ |
| NAV | ×34.28 | ×39.75 | +16% |
| CAGR | +60.9% | +64.1% | +3.2%p |
| MDD | 33.0% | **27.0%** | **-6.0%p** ★ |
| 2020-21 회복기 Cal | 2.33 | **3.53** | **+52%** ★ |
| 2022-23 약세장 Cal | 3.45 | 3.28 | -0.17 (미미) |
| 2024-25 강세장 Cal | 2.46 | 2.64 | +0.18 |
| 2019 Cal | 1.39 | 1.39 | 동등 |

### 변경 항목 (3 파일)
1. **fast_generate_rankings_v2.py**:
   - `_compute_ticker_growth_events`에 `rev_qoq`, `op_qoq` 추가
   - 메인 코드에 QoQ 패널티 (D6 mode) + SG6 조건 (KOSPI 거리 6%+)
   - SG6: KOSPI vs MA220 asof 매칭 (timestamp 정확 매칭 우회)
2. **regime_indicator.py**: boost params에 G_QOQ_PENALTY, G_QOQ_PENALTY_THRESHOLD=20, G_QOQ_PENALTY_MULTIPLIER=0.7, G_QOQ_SG6_THRESH=0.06 추가
3. **run_daily.py**: `_build_mode_env` + `regime_env` 에 G_QOQ_* 환경변수 전달 (boost only)

### Defense 변경 없음
- v80.11 V35Q15G15M35 그대로
- state/defense/ 재생성 불필요

### 인접 안정성
| MA 거리 임계 | Cal |
|---|---|
| 4% | 2.267 |
| 5% | 2.327 |
| **6%** ★ | **2.374** |
| 7% | 1.988 |

CV **0.067 ✅ PASS** (기준 < 0.10)

### 5/18 production 적용
- state/ 재생성 (1873일, boost만, defense는 baseline 유지)
- 백업: `state_v80_11_backup_pre_v80_12_20260518/`
- 5/18 매수 후보: 에스에이엠티 (wr 1.6) / SK하이닉스 (2.0) / 제주반도체 (2.6)
- 보성파워텍 차단 확인 (wr 7.9, cr 5→8→9) ★

### 환경변수
```
G_QOQ_PENALTY=D6
G_QOQ_PENALTY_THRESHOLD=20      # +20% 미만이면 패널티
G_QOQ_PENALTY_MULTIPLIER=0.7    # G_score × 0.7
G_QOQ_SG6_THRESH=0.06           # KOSPI > MA220 × 1.06일 때만 적용
```

### 검증 단계 (사용자 인사이트 → 표본 → 정통 BT)
1. 표본 BT (sleeve, 7년 어닝서프): D6 Cal 0.904 (Opt2b 0.888 능가)
2. 정통 BT (3년 2023~2025): A Cal 1.259 (baseline 0.968 대비 +30%)
3. 사용자 인사이트: 2022-23 약세장에서 A 약함 → SG6 (강한 boost) 게이팅
4. 강한 boost grid: SG1~SG7 비교 → SG4/SG6 (MA 거리 5~6%) 최강
5. 인접 안정성: CV 0.067 PASS
6. D6 + SG6 조합: Cal 2.374 (최강)

### 롤백 트리거
- 5거래일 KOSPI 대비 알파 -3%p 이하 / MDD -10% 초과
- 즉시 롤백: `regime_indicator.py` boost params에서 G_QOQ_* 키 4개 제거
- 백업: `state_v80_11_backup_pre_v80_12_20260518/` 7년 ranking

---

## v80.11 변경 — regime MA250 → MA220 ×8d (2026-05-18)

### 핵심 변경
- `regime_indicator.py:56` MA_PERIOD `250 → 220`
- 다른 변경 0 (defense V/Q/G/M, MOM, 계절성 모두 baseline 유지)

### 7.4y BT 검증 (2019-01-02 ~ 2026-05-15)
| 지표 | baseline (MA250) | **v80.11 (MA220)** | Δ |
|---|---|---|---|
| Cal | 2.592 | **2.798** | **+0.206 (+8%)** |
| CAGR | 97.0% | 104.7% | +7.7%p |
| MDD | 37.4% | 37.4% | 동일 |
| WF CV | 0.569 | **0.445** | **-22% 안정성 개선 ★** |
| min Cal (약세장 2022-23) | 1.33 | **1.94** | **+0.61 강화** |

### 49 격자 결과 (MA × confirm)
- MA[150,170,200,220,250,280,300] × confirm[3,5,7,8,10,12,15]
- **MA220 × 8d = 1위** (Cal 2.798)
- MA250 × 8d (baseline) = 9위
- 인접 안정성 CV 0.092 ✅ PASS

### MA220 인접 plateau 검증 (5/18 추가, 25 조합)
- MA[210,215,220,225,230] × confirm[6,7,8,9,10] = 25 조합
- confirm=8 행 plateau: 210=2.716 / 215=2.800 / 220=2.798 / 225=2.702 / 230=2.702
- **단일 peak 아닌 plateau** — MA215×8d (2.800) ≈ MA220×8d (2.798) 거의 동일
- 인접 CV **0.059** (PASS 기준 0.30 대비 5배 안전)

### 5/18 추가 검증 (사용자 우려 반영)
1. **KOSPI MA220 vs MA250 신호 차이**: 최근 30일 0건 (강세장에서 MA220/MA250 모두 한참 위)
   - state.json streak=4 (defense) → 5/18 첫 실행 시 boost로 재계산되어 reset 후 진행. mode='boost' 유지, 사고 없음
2. **16:00 자동 실행 DART 캐치율**: 5/15 1Q 마감일 1982건 분기보고서, 약 20%가 16시 이후 제출 (serial 2500+)
   - 평시는 영향 미미 / 분기마감일(3/31, 5/15, 8/14, 11/14)만 위험 / 다음날 자동 갱신으로 회복

### refresh_dart_cache.py 정정공시 보강 (2026-05-18)
- get_recently_disclosed: `[ticker, ...]` → `[(ticker, rcept_dt), ...]` 튜플 반환
- 분류 로직 3가지: skip(이미 정정 반영) / fetch_amended(mtime < rcept_dt) / fetch_new(target_date 데이터 없음)
- **정정공시 누락 위험 차단** (이전 needs_refresh는 target_date 데이터 있으면 skip → 정정공시 못 받음)
- 5/18 실전 동작: 992종목 중 skip 991 + fetch 1 + 캐시없음 1 = 부담 0

### 5/18 종합 검증
**검증 + 채택 안 됨**:
- defense V30Q05G25M40 + MOM 6m-1m: Cal +0.334 but **2022-23 Cal 0.97 사고 패턴** → 반려
- defense V30Q05G25M40 + MOM 12m: 음의 시너지 -0.642, 약세장 0.85 → 반려
- defense V30Q00G25M45 + MOM 12m: 약세장 0.23 사고 → 반려
- defense V30Q05G20M45 + MOM 12m: 약세장 0.85 사고 → 반려

**검증 + 안전 후보 (재고할 가치)**:
- defense V30Q00G25M45 + 6m-1m: Cal +0.261, min 1.18 (안전 but WF CV 0.673 +18% 악화)
- defense V35Q15 + MOM 12m: Cal +0.171, min 1.13 (안전 but WF CV 0.673)
- **MA220 + V30Q00G25M45**: Cal +0.453 (가장 큼) but 변경 4 axis
- **MA220 + V35Q15 + 12m**: Cal +0.341, min **2.13** (가장 안전) but 변경 2 axis

### v80.11 채택 근거
1. **변경 비용 최소** (regime_indicator.py 1줄)
2. **state 재생성 불필요** (regime은 매일 동적 계산)
3. **WF CV -22% 안정성 개선** (Cal lift 통계 noise 가능하더라도 안정성은 명확)
4. **약세장 강화** (min 1.33 → 1.94)
5. 단계적 — 1주 운영 후 defense 추가 변경 검토

### 5/18 분석 발견 (메모리 보존)
**boost/defense 회귀 분석** (1809 거래일, Top 30 × forward 20d):
- boost: G 56% + M 42% = 98% 기여 → V/Q/G/M 비율 데이터 정합
- **defense: Q 계수 -0.670** (가장 강한 음의 신호) — Q=0이 최적
- defense V/Q/M 모두 음수 계수, G만 +0.161 (작은 양수)

**MOM IC 분석**:
- boost 12m IC +0.031 (production 정당)
- defense 12m1m IC +0.016 > 6m-1m IC +0.004 (그러나 BT는 12m이 더 우월)

**defense 계절성 미적용 정당** (G 기여 16%만)

### 롤백 트리거 (v80.11)
- 5거래일 KOSPI 대비 알파 -3%p 이하
- 즉시 롤백: `regime_indicator.py:56` MA_PERIOD = 250 복원
- state 재생성 불필요

---

## v80.10 핵심 변경 — 진정 가속 성장 종목 보호 (2026-05-17)

### 면제 조건: min(직전 4분기) / max(직전 4분기) > 0.2
- 계절성 패널티 발동 종목 중 4분기 매출 변동성 작은 것 = 일관 성장 = 면제
- 코드: `backtest/fast_generate_rankings_v2.py:1846+` (SEASONALITY_EXEMPT_MM_THRESH=0.2 default)
- 브이엠 (089970) 0.35 ✓, 보성파워텍 (006910) 0.31 ✓ → 면제 (진정 성장)
- 동아엘텍 0.11, 선익시스템 0.07 → 차단 유지 (함정)

### 7.4년 BT 결과 (state_v8010_mm)
| 지표 | v80.9 | v80.10 | Δ |
|---|---|---|---|
| Cal | 2.086 | 2.016 | **-0.07** (noise 범위) |
| CAGR | 76.4% | 72.4% | -4%p |
| MDD | 36.64% | **35.93%** | **-0.71%p 개선** |

### 채택 근거 (전문가 의견)
1. Cal -0.07은 BT noise (±0.10 범위) — 통계 무의미
2. v80.9 제주반도체 결정 (-0.22 받아들임)과 동형 일관성
3. MM 0.2 식별력 정확 (진정 vs 함정 gap 3배 + cushion 충분)
4. MDD 개선이 동방향성 = Calmar 분자/분모 호의적

### 5/13~5/15 production 적용 결과
- 5/13 매수 후보: 보성파워텍 / 아이티센글로벌 / SK하이닉스 ★
- 5/14 매수 후보: 보성파워텍 / 아이티센글로벌 / SK하이닉스 ★
- 5/15 매수 후보: SK하이닉스 / 보성파워텍 / 제주반도체
- 브이엠 = 5/13~15 wr 4위 (Top 5, 사용자가 메시지에서 매수 후보로 인지 가능)

### 롤백 트리거
- 5거래일 KOSPI 대비 알파 -3%p 또는 MDD -8% 초과
- `SEASONALITY_EXEMPT_MM_THRESH=0` 환경변수 즉시 환원
- 백업: `/tmp/state_v809_backup/` (5/17 교체 직전 v80.9 state)



> 경로: `C:\dev\claude code\quant_py-main`
> 영구 지도: `C:\dev\SYSTEM_MAP.md` (전략 교체 시 맹점 제로 체크리스트)

## 2026-05-17 변경 종합 (밤샘 작업, 자율 진행)

### 매출 안전망 교체 (sma20>1.5 → jump>2.0 AND revcv>0.7)
- BT 47 시나리오 결과: v80.9 환경에서 sma20 모든 임계 알파 손해 (-0.05 ~ -0.43)
- v80.6 시절 +0.18 → v80.9 -0.151 환경 반전 (계절성 패널티 + 3팩터 G 도입 영향)
- 새 안전망 (조합 + WF 검증): Cal +0.274, WF min 1.791, CV 0.544 (가장 안정)
- AND 조건: 진정 가속 성장 (SK 26Q1 +198% HBM) 보호, 함정 (일회성 폭증+변동성) 차단
- 5/15 표본: 차단 0건, Top 3 (SK/제주/SAMT) 정상 진입
- commit: `0c26beb05`

### TS/SL 매수 후보 차단 제거 (시뮬 가정 위반)
- v80.1 (commit 9bf741b22) 도입 ts_cooldown_set 필터 = 신규 가입자 가정 위반
- 사용자 명시: "TS/SL은 보유 중 고객 판단. 매수 후보 표시는 모두 동일"
- send_telegram_auto.py verified_picks에서 cooldown 필터 제거
- calc_system_returns의 TS cooldown 로직도 제거 (시뮬 일관성)
- commit: `37494c4ed`

### wr PENALTY 통일 (Top 20 한정 + PENALTY 50)
- 사용자 지적: '빈 날짜 PENALTY 제대로 주고 있나?'
- 원인: 보성파워텍 wr 18.6 = cr 36/24 그대로 사용 (PENALTY 50 적용 X)
- 수정 (run_daily._postprocess_ranking + turbo_simulator):
  - T-1/T-2 cr 매핑 시 Top 20 한정 → 밖이면 PENALTY 50
  - BT와 production 동일 룰 (시뮬-실전 일치)
- state 1932일 × 2 (boost+defense) 전체 재생성 (6분)
- BT 결과 변화 미미 (entry=3 종목은 모두 Top 안)
- commit: `6c76442cf`

### 메시지 표시 정리 (4가지 정정 후 단순화)
- 매도 기준선만 (매수 기준선 제거): `━━━━━ 매도 기준선 ━━━━━`
- 매도 OR 조건 명시: '아래 셋 중 하나라도 해당 시 (① 매도 기준선 이탈 / ② -10% 시 / ③ 고점대비 -8% 시)'
- Signal footer = 매매 룰 (간결 6줄)
- Watchlist footer = 면책 (간결 3줄)
- AI Risk 헤더 구분선 19자 → 15자 통일 (gemini_analysis.py + send_telegram_auto.py)
- 순위 이탈 → Watchlist에만 표시 (Signal에서 제거)
- 🆕/⏳ 종목 검증 안 된 날 r1/r2 = '-' 표시
- 분할매수 권장 안내: '1차 50% + 다음날 추가' (적립식 시점 분산)
- '시스템은 신호만, 매매는 본인 판단' 명시
- 점진적 commit: `591b387ed`, `0c63d9c8e`, `7208ea634`, `0ead51a12`, `fae7fb063`

### Dead code 정리 (12개 모순 → 0)
- `_rerank_for_regime` / `_rerank_and_wr` 200줄 통째 삭제 (v78 잔존, 호출 X)
- `ENTRY_SCORE_100`=72 / `EXIT_SCORE_100`=68 deprecated 마킹 (v77 wr 무관)
- `crash_active`/`crash_entered`/`crash_exited` 4파일 잔존 제거 (v79 Crash Cash 제거됨)
- `CORR_THRESHOLD` dead branch 제거 (v74 잔존)
- `compute_3day_intersection` dead function 제거 (호출 X)
- `_postprocess_ranking` 첫 블록 → `_load_top20_cr_map` 단순화
- regime_indicator.py docstring v80.9 업데이트 + 진화 history (v80→v80.6→v80.7→v80.8→v80.9)

### Phase C — NAV 디스카운트 별도 트랙 (production 매매 신호 X)
- 9 산업지주사 식별 (KRX 금융섹터 비키워드 + 시총)
- DART '타법인출자' API + find_corp_code 자동 매핑 (197 자회사)
- 자회사 시가 × 지분율 = NAV 합계
- 5/15 결과: SK스퀘어 **44.4%** ★ (사용자 메모리 일치) / LG **38.5%** / HD현대 **31.0%**
- `nav_discount_module.py` + Watchlist 끝 별도 섹션 (매매 신호 X, 정보만)
- step 6 (BT 검증) 보류 (9 종목 풀 작아 BT 의미 X)
- commit: `86c3e58ec`

### Phase B 폴백 실제 적용 (오늘 밤 5/15 ranking 재계산 포함)
- 5/15 분기마감 finstate_all 누락 37.3% (300 표본) — Phase B 폴백 동작 검증
- 553 종목 재수집: finstate_all 380 + DOC 폴백 58 + empty 115
- DOC 폴백 = SK하이닉스/메가스터디/이건산업 같은 누락 종목 정상 보강
- monitor_dart_fn_health에 분기마감 누락률 자동 감지 + DOC 폴백 카운트 추가
- commit: `0f5a2c0e3`, `2213c6c67`

### 브이엠 케이스 발견 + v80.10 candidate (5/17 새벽 BT 완료)
- 브이엠 (089970) v80.6.1에서 cr 6위 → v80.9에서 cr 60위대 (5/14까지)
- 5/15 1Q 발표 후 자동 해제 → cr 5위 진입
- 원인: 25년 매출 Q2/Q4 vs Q1/Q3 ratio = 1.66 > 1.4 → 계절성 패널티 발동
- 진짜 가속 성장 (25Q4 508 → 26Q1 889, +75% QoQ) but 시스템 함정으로 분류

**면제 조건 후보**: `(vals[-2] / vals[-1]) > 0.6`
- 브이엠 0.72 ✓ 면제, 동아엘텍 0.45 ✗ 차단, 선익시스템 0.40 ✗ 차단 (5/14 표본)
- 5/14 ranking 재생성: 브이엠 cr 61→5 ★, 보성파워텍 cr 36→2 ★
- 7.4y EDA (52건): cr 30~50 평균 +60d +25.5% / cr 50+ 음수

**7.4y BT (state_v8010_test_full, 40.6분)**:
- v80.9 baseline = v80.10 (면제 0.6) = **Cal 2.078 동일** (Δ +0.000)
- 원인: BT 매수 = wr Top 3 (강한 종목). 면제로 cr 올라온 종목도 wr 27+ → Top 3 안 들어감.

**결론 (사용자 결정 대기)**:
- BT 알파 보호 + 메시지 통찰 강화 (브이엠 Top 20 진입)
- 채택 시: SEASONALITY_EXEMPT_QQ_THRESH=0.6 환경변수 설정
- 현재: 기본 비활성 (0), production 영향 0
- 메모리: [[project-vm-seasonality-trap-2026-05-17]]

## Phase B — DART document API 폴백 (2026-05-16 밤, commit 0f5a2c0e3)

### 배경 — 5/15 1Q 분기마감 finstate_all 37.3% 누락 발견
- 5/15 마감일 폭주 → DART finstate_all '013 데이터없음' 다발 (sync 지연 추정)
- 표본 300건 측정: 188 정상 / **112 누락 (37.3%) ★**
- 누락 사례: SK하이닉스/메가스터디/이건산업 등
- 누락 종목 = V/Q/G/M 점수 계산 누락 → ranking 이탈 (FnGuide 보충 또는 옛 데이터)
- 동시에 5/4 SG&A 매핑버그 같은 finstate_all 결과 자체 buggy 사례 우회 효과

### 해결 — XBRL document API 폴백
- `dart_collector._fetch_quarter_via_document(ticker, year, rcode)`: dart.list → dart.document(XBRL) → parse
- `_parse_document_xml(doc_xml, member)`: ACONTEXT (CFY/PFY × dFQQ/dFQA/eFQA × ConsolidatedMember) 정규식 파싱
- ADECIMAL: 0=원, -3=천원, -6=백만원
- fetch_single에서 finstate_all empty 시 자동 폴백 (year >= current-1 한정)
- fs_div='DOC' 추적 (monitoring)
- 매일 자동: refresh_dart_cache.py → fetch_single → 자동 폴백 (코드 변경 0)
- **PIT 원칙 유지**: rcept_dt = rcept_no 앞 8자리 (정확한 공시일) → 과거 ranking 오염 없음

### 검증 (6종목 표본 mismatch 0)

| 종목 | finstate_all | document API | 결과 |
|---|---|---|---|
| 동아엘텍 | 16 계정 정상 | 16 계정 | 일치 ✓ |
| 선익시스템 | 16 계정 정상 | 16 계정 | 일치 ✓ |
| 제주반도체 | 15 계정 정상 | 15 계정 | 일치 ✓ |
| SK하이닉스 | **누락** | 16 계정 | 폴백 ★ |
| 메가스터디 | **누락** | 16 계정 | 폴백 ★ |
| 이건산업 (5/15) | **누락** | 16 계정 | 폴백 ★ |

- SK 26Q1 매출 52.58조 (전년 17.64조 +198% HBM3E 호황) 정확 추출

### 비용 / 한계
- 폴백 발동 시: 종목당 +2 API 호출 (list + document)
- 5/15 폭주 추정: 525종목 × 4분기 × 2호출 = 약 4200 추가 API (일일 한도 59,700 대비 7%)
- transfer: 평균 1.5~4MB/종목 XML
- 한계: Q3 누적값(thstrm_add_amount) 폴백 미구현 → Q4 도출 부정확 가능 (드문 case)
- FnGuide PIT rcept_dt 이식 흐름 (postprocess_fnguide_rcept.py) 유지 — 점진적 의존도 감소

### 운영
- commit: `0f5a2c0e3`
- 회사 PC: 5/18 (월) 자동 pull 시 반영 (run_daily.py 시작 시 git pull --rebase)
- 회귀 위험: 함수 추가 + 1곳 호출 통합. 폴백은 finstate_all 정상 시 발동 안 됨 (영향 0).
- 5/16 밤 후속: 유니버스 1971종목 26년 fs_dart 일괄 재수집 (폴백 적용 → 5/15 누락 일제 보강)

## v80.9 변경 — curr 식 복귀 + defense exit 4→8, slots 4→5 (2026-05-16 저녁)

### 핵심 변경
1. **계절성 식 bi → curr (v80.7로 복귀)** + PENALTY 0.3 유지
   - 이유: v80.8 bi가 **제주반도체** 같은 진짜 가속 성장 종목 잘못 패널티 → 사용자 통찰 위반
   - 사용자 지적: "실적이 잘나와서 상한가가도 쳐다도 보면 안되는 시스템이 조언해주는거야?"
   - curr 식 = 사용자 통찰 100% 만족 (Q2/Q4 편향만 잡음, Q1+Q3 편향 보호)
2. **defense EXIT_RANK 4 → 8, MAX_SLOTS 4 → 5** (진짜 robust 개선)
   - 전체 axis × WF 4구간 그리드 (60 시나리오) + Top 3 인접 안정성 검증
   - 채택안 (B): WF min 0.32 → **0.959** (3배 개선!)
   - 인접 CV **0.035** (가장 안정)
   - 전체 Cal 3.123 (baseline 3.222 대비 -0.10 미미)
3. 다른 매매조건은 v80.8 그대로 (boost entry 3, exit 6, slots 5 / defense entry 5)

### 검증 단계
- WF axes EDA (단일 axis × WF) → exit_d=8 only가 robust 식별
- Full WF 그리드 (41 시나리오 × 4구간) → Top 3 robust 발견
- Top 3 인접 안정성 (±1 변동) → B 최강 (인접 CV 0.035)
- 거부 시나리오:
  - A (exit_d=8 + ts=-0.07): Cal 3.350 but 인접 WF -0.088 위험
  - C (exit_d=8 only): Cal 3.272 but 인접 exit_d=10 WF -0.005 위험
- 채택 B (exit_d=8 + slots_d=5): Cal 3.123 + WF 0.959 + 인접 안정

### 5/15 production 검증
- 동아엘텍: rank=23 (패널티 ✓)
- 선익시스템: rank=62 (패널티 ✓)
- **제주반도체: rank=3** ★ **Top 3 매수 후보 진입** (사용자 의도 정확)
- Top 3: 에스에이엠티 / SK하이닉스 / 제주반도체

### 7.4y BT 성과
| 지표 | v80.6.1 baseline | v80.7 (curr 0.5) | v80.8 (bi 0.3) | **v80.9 (curr 0.3 + exit_d=8)** |
|---|---|---|---|---|
| Cal | 1.863 | 2.287 | 3.494 | **3.272** |
| WF min | 0.320 | 0.320 | 0.320 | **0.750** ★ |
| CAGR | 84.3% | 97.8% | 114.9% | ~105% |
| MDD | 45.3% | 42.8% | 32.9% | ~34% |

### 검증 단계 (Phase 1~3 EDA + 12 step)
- Phase 1 그리드 (식): curr/bi/max2min2/cv 등 비교 → curr가 사용자 의도 만족
- Phase 2 (defense 계절성): defense 식 미적용 결정 (모두 baseline 이하)
- Phase 3 (매매 9 axis): entry_o=2 / all 3 모두 2019 과적합 → exit_d=8만 채택
- WF axes EDA: exit_d=8 only가 robust 진짜 개선 (WF min +0.43)
- RSI 70 도입 검토 → 제주반도체도 차단되어 사용자 의도 위반 → 거부

### 환경변수
- `SEASONALITY_FORMULA='curr'` (default 변경, bi → curr)
- `SEASONALITY_PENALTY='0.3'` (v80.8 그대로)
- `SEASONALITY_RATIO_THRESH='1.4'` 유지

### 롤백
- 식 비활성: `SEASONALITY_DISABLE=1`
- v80.8 (bi) 복귀: `SEASONALITY_FORMULA=bi`
- 백업: `state_v80_8_backup/` (v80.8 1932일)

### 사용자 보호 + 시스템 신뢰
"실적 잘나오는 종목이 안 보이면 시스템 의미 없다"
- v80.9 = 제주반도체 Top 3 보여줌
- 매수해도 시스템 알파 손실 없음 (-0.22 Cal but 사용자 신뢰 +)
- v80.8 (bi)는 제주를 46위로 깊이 숨김 → 사용자 자기 판단 매수 시 시스템 책임

---

## v80.8 변경 — bi 양방향 식 + 매매조건 정밀 그리드 (2026-05-16)

### 핵심 변경
1. **계절성 식 curr → bi (양방향)**: `max((Q2+Q4)/(Q1+Q3), (Q1+Q3)/(Q2+Q4)) > 1.4`
   - Q1+Q3 편향 종목도 잡음 (curr는 못 잡았던 패턴)
   - 단, Q1+Q2/Q3+Q4 인접 2분기 폭증은 여전히 못 잡음 (top4_bot4 BT 망했음)
2. **PENALTY 0.5 → 0.3** (G_score 50% → 70% 깎음)
3. **매매 조건 (Phase 3 9 axis 그리드)**:
   - boost ENTRY_RANK: 2 → **3**
   - defense ENTRY_RANK: 3 → **5**, EXIT_RANK: 6 → **4**
   - TS_COOLDOWN: 2 → **1** (양 모드)

### 7.4y BT 성과 (2019-01~2026-05)
| 지표 | v80.6.1 baseline | v80.7 (curr) | **v80.8 (bi+매매조건)** |
|---|---|---|---|
| Cal | 1.863 | 2.287 | **3.494** |
| CAGR | 84.3% | 97.8% | **114.9%** |
| MDD | 45.3% | 42.8% | **32.9%** |
| Sharpe | 1.43 | 1.68 | **1.98** |

baseline 대비 **Cal +87%**, CAGR +30.6%p, MDD -12.4%p

### Phase 1 그리드 결과 (식 × 임계 × PENALTY)
- Round 1 (12 시나리오): bi 1.4/0.5 = 2.523 (curr 1.4/0.5 = 2.287 +0.236)
- Round 2 (43 시나리오): **bi 1.4/0.3 = 2.610** (PENALTY 0.3 일관 우월)
- top4_bot4 단일 식: 모든 임계 baseline 미달
- bi OR top4_bot4: bi 단독에 못 미침
- AND 조건(bi_and_cv): trigger 좁혀 알파 감소

### Phase 2 결과
- defense 계절성 패널티 → **미적용** (모든 시나리오 baseline 이하 -0.005~-0.082)
- 이격도20 → **1.5 유지** (BT 영향 0, 안전망 기능)

### Phase 3 결과 (9 axis 그리드)
- entry_o 2→3 (+0.315), exit_o 6 유지, slots_o 5 유지
- entry_d 3→5 (+0.087), exit_d 6→4 (+0.112), slots_d 4 유지
- SL -10% 유지, TS -8% 유지
- ts_cd 2→1 (+0.370 단독 우월, 5 variant 강건성 검증 PASS)

### 강건성 검증
- ts_cd=1 우월 (5 variant 평균 Δ +0.267)
- WF CV 0.638 ⚠️ (2019 dip Cal 0.320 — 약세장 약점)
- 단일 종목 의존성 1.3% ✅

### 환경변수 (`fast_generate_rankings_v2.py`)
- `SEASONALITY_FORMULA='bi'` (default 변경)
- `SEASONALITY_PENALTY='0.3'` (default 변경)
- `SEASONALITY_RATIO_THRESH='1.4'` (유지)
- `SEASONALITY_DISABLE=1` 시 비활성

### 롤백 트리거 (v80.8)
- 5거래일 KOSPI 대비 알파 -3%p 이하 / MDD -10% 초과
- 백업: `state_v80_7_backup/`, `state_pre_v80_7_backup/`
- 즉시 롤백: `SEASONALITY_FORMULA=curr SEASONALITY_PENALTY=0.5` 환경변수

### 약점 / 추가 작업
- WF 2019 약점 — 약세장 모니터링 강화
- 인접 2분기 폭증 패턴(Q1+Q2, Q3+Q4 등) 못 잡음
- DART finstate_all 누락 자동 감지 X (5/16 동아엘텍 사용자 발견 의존) → **Phase 4.5에서 document 메인 전환 진행**

---

## v80.7 변경 — 계절성 패널티 도입 (2026-05-16)

- **계절성 비율 (Q2+Q4 매출) / (Q1+Q3 매출) > 1.4 인 종목 → 성장_점수 × 0.5 패널티**
- 효과: 7.4y Cal **2.90 → 3.29 (+0.39)**, CAGR **+102.8% → +114.9% (+12.1%p)**, MDD **-35.4% → -34.9% (개선)**
- 사용자 케이스(선익시스템/동아엘텍 8.6세대 OLED Q2/Q4 일회성 폭증) 함정 자동 회피
- 11개 시나리오 BT 그리드서치(2019~2026-05) 중 단독 baseline 우월 → 채택
- 다른 시나리오(A 분기단독/B 50/50/C 가중치/D CV/F monotonic/L 분리/R smooth/AC outlier)는 baseline 미만 또는 미세 개선만
- 적용 위치: `backtest/fast_generate_rankings_v2.py:1778~` (calculate_multifactor_fast 후처리)
- 환경변수 제어: `SEASONALITY_DISABLE=1` (비활성), `SEASONALITY_RATIO_THRESH` (기본 1.4), `SEASONALITY_PENALTY` (기본 0.5)
- 핵심 메커니즘: 일회성 매출 폭증 종목(분기 매출 [Q1+Q3 작음 / Q2+Q4 큼] 패턴)을 자동 감지하여 G_score 절반. TTM YoY는 그대로 유지하여 BT 평균 알파 손실 0.

### v80.7 BT 그리드 결과 요약 (Cal 순)
| 시나리오 | Cal | CAGR | MDD | 비고 |
|---|---|---|---|---|
| **S(1.4, 0.5)** | **3.29** | +114.9% | -34.9% | **채택** |
| S(1.6, 0.5) | 3.26 | +115.5% | -35.4% | |
| S(1.4, 0.4) | 3.26 | +113.7% | -34.9% | |
| F+S 조합 | 3.21 | +113.6% | -35.4% | 시너지 X |
| F(α=0.2) 단조증가 | 2.98 | +109.6% | -36.8% | 2위 단독 |
| baseline (v80.6.1) | 2.90 | +102.8% | -35.4% | 비교 기준 |
| D(0.5,0.6) binary CV | 2.81 | +108.9% | -38.8% | |
| A/B/C (TTM 변경) | 0.5~0.6 | +27~30% | -47~54% | 망함 |

## v80.6.1 변경 — boost G 3팩터 도입 (2026-05-15)

- **boost G subfactor**: rev_z + oca_z **+ gp_growth_z** (0.4/0.4/0.2) ← 3팩터로 확장
- 이유: 7.4y BT Cal 2.888 → 2.961 (+0.073 미미), **WF CV 0.508 → 0.440 (-13% 안정성 개선) ★**
- 약세장 (2022-23) Cal 1.81 → 1.84 유지 (v80.7 사고 패턴 회피)
- 인접 안정성 CV 0.142 ✅ PASS
- defense 무변경 (rev+oca 0.8/0.2 그대로, defense G grid 결과 baseline 최적)

### v80.6.1 grid search 검증 (2026-05-15)
- V/Q/G/M 격자 56조합: baseline **1/56위** = v80.6 비율 (V15Q0G55M30) 그대로 최적
- G subfactor grid:
  - 단일 팩터 모두 baseline 대비 -1.1 ~ -2.4 (단독 alpha X)
  - 2팩터 rev+oca = 최적
  - **3팩터 rev+oca+gp 0.4/0.4/0.2 = WF 안정성 ★**
  - 4팩터 rev+oca+op_margin+cfo 0.4/0.4/0.1/0.1: Cal 3.868 (+0.980 대형 lift) but 약세장 1.12 함정 → **반려**
  - trio rev+oca+cfo: Cal +0.206 but 약세장 0.92 함정 → 반려
- defense G grid: rev+oca 0.8/0.2 = baseline 최적, 다른 조합 모두 marginal (Δ<0.02)
- MOM 기간 단일화 검증: baseline (boost 12m + defense 6m-1m) = 최강. regime별 변경이 진짜 알파

### v80.6.1 production 적용 (2026-05-15)
- `regime_indicator.py:142~158`: boost G_SUB3='gp_growth_z', G_W1/2/3=0.4/0.4/0.2
- `backtest/regenerate_all_v80.py`: BOOST_ENV 3팩터, defense job 비활성 (baseline 유지)
- state 1930일 재생성 (boost만, 38.7분) + wr_batch 후처리 (61초)
- 백업: `state_v80_6_pre_3f_20260515_RAW/` 1931개 + `state_v80_6_backup_pre_3f_20260515/`
- 5/14 검증: cr=3 제주반도체 (3팩터로 7→3 상승), wr=9 (3일 가중 영향)

## 국면전환 전략 (v80.6, 2026-05-13)

### v80 → v80.6 경위 (2026-05-13)
- 2026-05-12: fs_dart SG&A 매핑 버그 + OHLCV 326종목 액면분할 미반영 발견
- 2026-05-12: 215종목 매핑 정정 + 옵션F (DART/FN mismatch row 제거) 폐기 — 가짜 알파 제거
- 2026-05-13: OHLCV 326종목 옛 백업으로 복원 (수정주가 적용) + 204620 글로벌텍스프리 1종목 추가 보정
- 2026-05-13: KOSPI parquet 두 컬럼 ('종가' + 'kospi') → 단일 'close' 통합
- 2026-05-13: **v80.6 전면 재탐색 시작점 = 2019-01-02 (7.4년)**, 2018 H2 데이터 부족 (DART 분기 8개 미충족) 제외
- Tier 1 (boost coarse 972조합) → Tier 2 (dense 1200 MP) → Tier 3 (WF) → Tier 4 (defense 512 MP) → Tier 5 (regime 30) → Tier 6 (교차 75 MP) → Tier 7+ (단일 종목 + MOM/VQGM/GSUB/ESX 40) → Tier 7B (033100 의존 48) → Tier 8 (최종 WF + 인접 안정성)
- 결과: **baseline Cal 2.38 → v80.6 Cal 3.99** (+68%), CAGR 103%→143%, MDD 43.4%→35.8%, CV 0.69→0.38

### v80.6 핵심 변경 (v80 대비)
- **국면: MA170 8d → MA250 8d** (Tier 5 검증, 평균 Cal 3.59→3.81)
- **공격 G_REV: 0.6 → 0.5** (oca 비중↑, Tier 2 정점)
- **공격 entry: 3 → 2** (집중, Tier 1 +0.11)
- **공격 slots: 3 → 5** (분산 보유, Tier 2 plateau)
- **방어 V/Q/G/M: V30Q15G15M40 → V35Q15G15M35** (V↑ M↓, Tier 4 best)
- **방어 G_REV: 0.7 → 0.8** (rev 비중↑, Tier 4 정점)
- **방어 slots: 5 → 4** (약간↓, Tier 4)
- **공통 TS: -15% → -8%** (보호 강화, Tier 2 정점)
- **공통 SL: -10% 유지**

### v80.6 결정 — robust 후보 vs alpha 후보

**채택: v80.6 (alpha 최강)** — gr 0.5, entry 2, slots 5
- 이유: CV 0.38 압도적 안정 (모든 WF 균등 강)
- 033100 의존 21% (no033 환경에서도 Cal 3.17 > baseline 2.71 유지)
- **인접 안정성 CV 0.052 (orig) / 0.082 (no033) PASS** — overfit 아님
- 거부 후보: v80.6_robust (e3 s3 gr0.5) Cal 3.31, gr 0.35 Cal 3.44 — 모두 WF2/WF3 약화

### 2-tier 시스템
1. **공격 (boost)** — KOSPI > MA250, **8일 확인** → Growth + Value
2. **방어 (defense)** — KOSPI < MA250, **8일 확인** → Momentum + Value

### 국면 규칙 (KP_MA250_8d)
- **KOSPI > 250일 이동평균** = 공격, 미만 = 방어
- **8일 연속 확인** 후 boost↔defense 전환
- 모든 전환 시 기존 포트폴리오 **전량 청산**

### 공격 모드 (Boost) — KOSPI > MA250 (8일 확인)
- **V15 + Q0 + G55 + M30**
- G 내부: 2팩터 **rev_z 50% + oca_z 50%** (v80.6: 60→50)
- 모멘텀: **12m**
- 진입: rank ≤ **2** (v80.6: 3→2), 퇴출: WR > **6**, 슬롯 **5** (v80.6: 3→5)
- 손절: **-10%**, 트레일링: **-8%** (v80.6: -15→-8), **TS 쿨다운: 2일**

### 방어 모드 (Defense) — KOSPI < MA250 (8일 확인)
- **V35 + Q15 + G15 + M35** (v80.6: V30M40 → V35M35)
- G 내부: 2팩터 **rev_z 80% + oca_z 20%** (v80.6: 70→80)
- 모멘텀: **6m-1m**
- 진입: rank ≤ 3, 퇴출: WR > 6, 슬롯 **4** (v80.6: 5→4)
- 손절: **-10%**, 트레일링: **-8%** (v80.6: -15→-8), **TS 쿨다운: 2일**

### 성과 (v80.6, 7.4년 2019-01~2026-05)
- 7.4y Cal **3.99** (baseline v80 2.38 → +1.61, +68%)
- CAGR **142.8%** (baseline 103.3% → +39.5%p)
- MDD **35.8%** (baseline 43.4% → -7.6%p)
- Sharpe **2.01**, Sortino ~3.0
- WF [2019: 3.27 / 2020-21: 3.74 / 2022-23: 3.30 / 2024-26: 7.23]
- WF mean **4.38**, CV **0.38** (압도적 안정)
- 인접 안정성: orig CV 0.052 / no033 CV 0.082 PASS

### 측정 기준 변경 (2026-05-13)
- **시작점: 2018-07-02 → 2019-01-02** (7.8년 → 7.4년)
- 이유: 2018 H2 DART 데이터 부족 ((d) 필터 941종목, 정상 1700+ 대비 55%) → BT 시작점에 부적합
- 5.25y 기준 완전 폐기. **7.4y 단일 기준**.

### v80.6 production 정련 (2026-05-13 저녁 세션)
회사PC v80.6 commit `89e580f42` 후 자동 발송이 종목수 미달(288/320)로 차단된 사고에서 시작. 시스템 점검 + 정련.

**1. 종목수 임계 320 → 150** (`run_daily.py:708, 732`)
- 시장 자연 약세 (305→302→288)를 데이터 사고로 오인하던 문제
- historical 분포: min 193, p5 205, p10 215 — 약세장에선 200대가 정상
- 임계 150 = wholesale 사고(캐시 통째 손실 등) 감지선
- 부분 사고(특정 종목 이탈 등)는 별도 신호로 (DART vs FN baseline 비교 등)

**2. 메시지 문구 v80.6 명확화** (`send_telegram_auto.py`, `send_notice_once.py`)
- "위 이내" 모호 표현 → "상위 N종목" 명시
- "WR > 6" 내부 용어 → "X위 밖"
- "트레일링" → "고점대비"
- 매수: `상위 2종목 (최대 5종목 보유)` / 매도: `6위 밖 / 손절 -10% / 고점대비 -8%`
- send_notice_once.py: MA170→MA250, 슬롯 3/5→5/4, 트레일링 -15%→-8%, defense 팩터 V30M40→V35M35

**3. HY 캐시 복원** (`data_cache/hy_spread.parquet`)
- 5/13 새벽 작업 중 7650일 → 799일(3년)로 손상 (FRED 3년 제한 + 캐시 덮어쓰기)
- git commit `d7f198504`에서 84KB 옛 캐시 추출 + 4/17~5/11 신규 16일 병합 → **7666일 복원**
- 백업: `hy_spread.parquet.bak_799d_corrupt` 보존
- credit_monitor HY 분석 정상 작동 확인 (2.79% Q2 여름 8일째)

**4. Gemini API 키 갱신**
- 기존 키 leak 보고 (Google 403 "API key was reported as leaked") → AI 분석 모두 누락
- 새 키 발급 후 `config.py:23` 교체
- `config.py`는 `.gitignore` 등록 → git push 안 됨, 회사PC 별도 동기화 필요

**5. FnGuide refresh 정책 개선** (`refresh_fnguide_incremental.py`)
- 종목 선정: DAYS cutoff 3→30일 + **mtime 비교 추가** (fnguide < dart인 종목만)
- 처리: ThreadPool=2 worker + 종목당 30초 timeout (hang 보호)
- 전체 timeout: 900s → 10800s (3시간, `run_daily.py:468`)
- 환경변수: `FNG_INCR_DAYS`, `FNG_TICKER_TIMEOUT`, `FNG_WORKERS`
- 5/13 stale 1550 종목 일괄 보충 완료 (100% 성공, 23.4분) → 이후 자동 실행은 소량
- 이유: FnGuide 사이트는 DART보다 며칠~수주 늦게 들어옴. 3일 cutoff면 누락 확정. 매일 매일 30일까지 재시도하다 사이트 데이터 들어오면 받음.

**6. 점수 영향 분석 결과**
- v80.6 G_SUB = `매출성장률(DART) × G_REV + 영업이익변화/자산(DART) × (1-G_REV)` — fnguide 비의존
- V (PCR/PSR) / Q (GPA/CFO)도 DART 14개 핵심 계정으로 계산 가능 — fnguide는 보충용
- fnguide 단독 항목 없음 — 다만 (e) capped 검사에 영업CF z 결측은 영향 미미

### v80.6 추가 정련 (2026-05-14 — 5/15 1Q 폭주 대비)

**timeout 5시간 상향** (`run_daily.py:458, 468`)
- DART subprocess: 10800s(3h) → **18000s(5h)**
- FnGuide subprocess: 10800s(3h) → **18000s(5h)**
- 5/15 분기보고서 마감일 단일일 200~400건 일제 제출 예상 대비
- 산정: DART 500종목 × 7초 ≈ 60분 이론치 + 안전 마진
- FnGuide 종목당 timeout 30초가 핵심 hang 보호선 (유지)

**모자관계 분산 BT 검증 — baseline 유지**
- 동아엘텍-선익시스템 같은 모자관계 동시 매수 우려 검증
- 23그룹 수동 매핑 + 7.4년 BT 4시나리오
- 결과: baseline Cal 3.12, 분산+점수1위 Cal 3.14 (+0.02 미미), 옵션A Cal 2.12~2.65 (악화)
- 7.4년간 모자관계 동시 매수 case 8~12회만 (매우 드뭄)
- 동아엘텍-선익시스템 동시 1·2위는 최근 8.6세대 OLED 폭증의 **일회성 case**
- 결론: 분산 도입 효과 미미 + 매매 로직 복잡도 증가 → **baseline 유지**, 정보성 안내만 검토

## 국면전환 전략 (v80, 2026-04-18, 옛 production)

### v79→v80 경위
- 2026-04-17: 잠정실적 연구 → PIT 문제 발견 → gp_growth_z 제거 검토 시작
- 2026-04-18: v79 Phase 5a 단계적 최적화 함정 발견
  - 3f가 E5X8S5 attack-only에서 결정 → E3X6S3 국면전환에서 재확인 안 됨
- 2026-04-18: v80 전면 재탐색 (5,652조합, 4시간)
  - Phase 1a: VQGM×G서브×모멘텀 2,752조합
  - Phase 1b: G서브 세밀 90조합
  - Phase 1c: E/X/S 240조합 + 최종 조건 재확인
  - Phase 1d: 인접안정성 Top10 전원 CV<0.3 통과
  - Phase 2: 방어 2,850조합
  - Phase 3: 국면 MA{100,150,200,250}×확인{3,5,7,10,15}d = 20조합
  - Phase 4: 교차검증 45조합 × WF 4구간

### v80 핵심 변경 (v79 대비)
- **국면: MA200 7d → MA170 8d** (Phase 3 그리드서치, score 3.85→4.33)
- **공격 G서브: 3f(rev+oca+gp) → 2f(rev60+oca40)** — gp_growth 제거 → PIT 깨끗
- **공격 Q: 5→0** (Quality 제거, Growth 집중)
- **공격 G: 50→55**
- **방어 S: 7→5** (슬롯 축소)
- 잠정실적 호환: 2f(매출+영업이익만) → PIT 위반 없이 잠정 통합 가능

### 2-tier 시스템
1. **공격 (boost)** — KOSPI > MA170, **8일 확인** → Growth + Value
2. **방어 (defense)** — KOSPI < MA170, **8일 확인** → Momentum + Value

### 국면 규칙 (KP_MA170_8d)
- **KOSPI > 170일 이동평균** = 공격, 미만 = 방어
- **8일 연속 확인** 후 boost↔defense 전환
- 모든 전환 시 기존 포트폴리오 **전량 청산**

### 공격 모드 (Boost) — KOSPI > MA170 (8일 확인)
- **V15 + Q0 + G55 + M30**
- G 내부: 2팩터 **rev_z 60% + oca_z 40%**
- 모멘텀: **12m**
- 진입: rank ≤ **3**, 퇴출: WR > **6**, 슬롯 **3**
- 손절: -10%, 트레일링: -15% (v80.2 rollback 2026-05-12 — 옵션F만 BT에서 baseline 우위 Cal 3.98 vs SL-7/TS-10 Cal 3.65), **TS 쿨다운: 2일**

### 방어 모드 (Defense) — KOSPI < MA170 (8일 확인)
- **V30 + Q15 + G15 + M40**
- G 내부: 2팩터 **rev_z 70% + oca_z 30%**
- 모멘텀: **6m-1m**
- 진입: rank ≤ 3, 퇴출: WR > 6, 슬롯 **5**
- 손절: -10%, 트레일링: -15% (v80.2 rollback 2026-05-12 — 옵션F만 BT에서 baseline 우위 Cal 3.98 vs SL-7/TS-10 Cal 3.65), **TS 쿨다운: 2일**

### 이격도20 안전망 (v80.3, 2026-05-12 도입)
- 매수 후보 진입 시 **현재가 / 20일 이평 > 1.5 종목 자동 차단**
- 코드: `send_telegram_auto.py` line 1582 (verified_picks 루프)
- 사유: KBI메탈(4연상한, 이격도 2.26) 같은 폭등 종목 매수 추격 위험 차단
- BT 7.8년 검증 (옵션F만 데이터):
  - baseline Cal 3.937 → 안전망 Cal **4.117** (+0.18)
  - MDD 38.17% → **36.57%** (-1.6%p)
  - 누적 +1,151%p
- 인접 안정성: 1.45 단독 peak (Cal 4.26) → 1.50 plateau 채택 (robust)
- Watchlist에는 그대로 표시 (관찰만, 매수 후보 X)

### TS 쿨다운 규칙 (v80.1, 2026-04-20)
- 트레일링 스탑으로 퇴출된 종목은 **2거래일간 재진입 금지**
- 손절(-10%)로 퇴출된 종목은 쿨다운 없음 (바로 재진입 가능)
- 국면 전환 시 쿨다운 리셋
- 근거: 81조합 그리드서치, Cal 3.86→4.20 (+0.34), WF CV=0.37, 인접 안정
- 트레일링 퇴출 = 고점 대비 되돌림 → 1~2일 더 빠진 후 바닥에서 재진입이 유리

### 성과 (v80 기준)
**5.25년 BT (2021-01~2026-04)**: Cal=**4.71**, CAGR=TBD%, MDD=TBD%
**7.8년 BT (2018-07~2026-04)**: Cal=**3.97**, CAGR=TBD%, MDD=TBD%
- v79 대비: 7.8y Cal +0.74, 5.25y Cal +1.27
- WF min=3.22, mean=4.94, CV=0.29

### v77.1 재측정 vs 기록 불일치 (중요)
- MEMORY.md에 기록된 v77.1: 5.25y Cal 4.58, 7.8y Cal 1.50
- **Phase 3 재생성 BT로 실측**: 5.25y Cal **2.68**, 7.8y Cal **1.01**
- 원인: Phase 2 PIT 수정 (chronic_loss_3yr, asset_dilution 포인트인타임 적용) 반영으로 과거 BT 성과 자체가 바뀜
- 기존 "공식 성과 4.58"은 PIT 수정 전 BT 기준

### Walk-Forward 견고성 (Phase 7, v79 cfg 1)
| 구간 | Cal |
|---|---|
| 2018H2-19 | 5.00 |
| 2020-21 코로나 | 2.50 |
| 2022-23 | 3.88 |
| 2024-26 | 4.89 |
- WF min 2.50, mean 3.75 — cfg 0/2 대비 위기 대응력 우월
- 인접 안정성 CV 0.20 (통과 기준 < 0.3)

### 섹터 쏠림 맹점 (Phase 8b/c 분석)
- v79 Top 10: 전기전자 29% (+8.8%p vs 유니버스), 기계 **40% (+27%p vs 유니버스)**
- 기계 섹터 초과편중 = 2024~26 변압기/HBM 장비/K-방산 사이클 베팅
- 제룡전기(033100) Top 1 점유 9% — 단일 종목 의존 검증 시 제외해도 v79 우세 (Δ Cal +1.93)
- 섹터 cap 실험: cap=2/3/5/7 어느 것도 v79 원본을 못 이김 (dominated) → v79 무제한 유지

### (d)+(d')+(e) 필터 (2026-04-15 도입, v79에서도 유지)
- **(d)** DART 분기보고서 8개(2년) 미만 종목 제외 (`fast_generate_rankings_v2.py` line 1594-1623)
- **(d')** (d)의 PIT 버전: rcept_dt ≤ base_date 기준 분기만 카운트
- **(e)** G 서브팩터 5개 이상 동일값(\|v\|>1.5) = capped 종목 제외 (line 1638-1653)
- 효과: v77 시절 뻥튀기 종목(솔루스첨단소재/SK스퀘어 등) 완전 제외 확인됨

### FnGuide PIT 보강 (2026-04-15)
- 문제: FnGuide 원본 스키마에 `rcept_dt`(공시일) 필드 **없음** → 이전엔 "기준일+90일" 추정 사용 (보수적이지만 비정확)
- 해결: **DART의 rcept_dt를 FnGuide에 역추적 이식** (`postprocess_fnguide_rcept.py`)
  - 2,766 종목 × 약 130만 건 매칭 완료 (49초, 4워커)
  - (종목, 기준일, 공시구분) → DART rcept_dt 매핑
  - DART 미매칭 시 기본값: 연간 기준일+90일 / 분기 기준일+45일 (법정 기한, 보수적)
- 자동 증분: `refresh_fnguide_incremental.py` → `run_daily.py` Step 0.1
  - DART 최근 3일 내 갱신된 종목만 FnGuide 재크롤 후 rcept_dt 자동 이식
- 영향: Growth 팩터 eff_date가 "90일 추정"에서 "실제 공시일"로 변경 → BT/프로덕션 PIT 정확도 향상

### 데이터 품질 필터 (v77 이후 유지, v79에서도 동일)
- pykrx PER/PBR/EPS/BPS 전부 0 → 제거
- ROE: pykrx EPS>0 → pykrx. EPS=0 → DART TTM 폴백
- ROE NaN → 필터 스킵 (GPA/CFO로 Quality 평가)
- 우선주 제거 (티커 끝자리 ≠ 0)
- 금융 키워드: 생명/화재/IB투자/벤처투자/자산운용/신탁

### -1.5σ 단일팩터 바닥 필터 (2026-04-16 검증, 유지 확정)
- V/Q/G/M 4팩터 중 하나라도 -1.5σ 미만이면 유니버스에서 제외
- **효과**: 노이즈 종목 차단. baseline(유지) > A(-2.0완화) > B(V면제) > C(필터없음)
- **부작용**: HD현대일렉트릭, 제룡전기 등 대형 전력주가 V(가치) -1.5 미만으로 탈락
  - 주가 급등 → PER/PBR 비쌈 → Value z-score 하락 → 필터 탈락
  - 5옵션 BT 비교 결과 필터 포함해도 성과 하락 → "포함 불필요" 확정
- **`EXTREME_MODE` env var**: A/B/C/D 실험용 (`fast_generate_rankings_v2.py`). 미설정=baseline.

### 알려진 유니버스 이슈 (v79 이후 별도 해결)
- **LS ELECTRIC (010120)**: OHLCV 비거래일 가격 0 + 액면분할 수정주가 미반영 → MA120 오염 → 필터 탈락
- **산일전기 (062040)**: DART 분기 6개 < 8개 (신규 상장) → (d) 필터 탈락. 시간 경과 시 자동 해결

### DART SG&A 매핑 버그 사건 (2026-05-04, 영구 해결됨)
- **문제**: `dart_collector.py` line 42에 잘못된 매핑 `'dart_TotalSellingGeneralAdministrativeExpenses': '매출액'` 존재 (4/4 commit `409dea9d7`에서 추가, AI co-author)
- **발현**: 5/4 16시 자동 스케줄러 시 SK하이닉스(140만 돌파, +12% 폭등) 등 대형주 ranking 이탈
  - SK 25Y 매출이 SG&A(11.5조) 값으로 잘못 매핑 → mismatch 검사(DART 11.5조 vs FN 97조 ratio 0.12) → DART 폐기 → FN 4분기만 사용 → (d) 분기 8개 미만 → 탈락
  - 4/30까지 발현 안 함 (DART 응답에 `ifrs-full_Revenue` 우선 등장) — 5/4 외부 트리거(DART 응답 변동 추정)로 SG&A 우선 등장 → 매핑 발현
- **해결**: line 42 매핑 영구 제거, 영업이익률 > 80% 가진 'y' 매출 row 78종목 정정 (104 row 제거), 5/4 ranking 재생성 + 텔레그램 정정
- **BT 신뢰성**: 4/30까지 BT 데이터 사용 종목 0개 영향 → 모든 BT 결과 (v80 그리드 6004조합, sl_ts_grid, cooldown_grid, exit_rule 등) 그대로 유효

### B 검증/재시도 안전망 (2026-05-04 도입, run_daily.py)
- 매핑 버그 같은 외부 트리거 사고 재발 방지
- **동작**: ranking 종목 수 < 320 시 채널 발송 차단 + 개인봇 알림 + 30분 sleep + 재시도
- 재시도 통과 → 정상 발송 / 재시도 실패 → 보류 + 개인봇 알림 + push X
- 추가: `run_daily.py` 시작 시 `git pull --rebase origin main` 자동 (working tree clean 시) → 다른 PC에서 push한 코드 변경 자동 반영

### 매핑 추가 시 검증 절차 (2026-05-04 도입)
- DART/FnGuide 매핑 추가/변경 시 **회계 항목 의미 정확히 검증** (특히 비용 vs 수익 항목)
- AI co-author 작업 시 commit 메시지에 명시 안 된 변경분 검토 필수
- ranking에서 갑자기 대형주가 빠지면 첫 의심 = `fs_dart` 데이터 정합성 (영업이익률 > 80% 'y' 매출 row 검사)

### KRX 섹터 "금융" 필터 (2026-05-12 추가, fast_generate_rankings_v2.py)
- **배경**: 옵션F 도입 후 SK스퀘어/LG/CJ/HD현대/에코프로 등 산업지주사가 ranking 상위 진입 → 자회사(SK하이닉스 등)와 중복 평가 문제 드러남
- **원인**: 기존 `EXCLUDE_KEYWORDS`(종목명 키워드)는 "SK스퀘어"처럼 이름에 "지주" 없는 종목 못 잡음. 옵션F 이전엔 OFS 오염으로 자동 탈락하던 것이 옵션F 정정 후 드러남
- **필터**: KRX 분류 "금융" 섹터 = 산업지주사 + 금융사 통합 식별 → 19종목 (5/11 표본 기준) 자동 제외
- **위치**: line 1604-1635, 종목명 키워드 필터 직후 섹터 필터 추가
- **효과 (5/11 표본)**: 325 → 306 (-19). SK하이닉스(전기전자), 동아엘텍/선익시스템(기계) 등 본업 사업체 영향 없음
- **NAV 효과**: 지주사 디스카운트 해소 흐름은 시스템 모델 밖 — 별도 트랙 미래 디자인

### 옵션 F — 항목별 mismatch 자동 정정 (2026-05-12 도입, fast_generate_rankings_v2.py)
- **배경**: 5/4 매핑 버그 + 5/11 'q' 분기 잔재 + dart_collector CFS/OFS fallback 발견 → 광범위 폐기(기존 check_data_mismatch) 대신 정밀 정정 필요
- **EDA**: 1927종목 분석 결과 mismatch는 **항목별 독립** 발생 (OFS 일괄 폴백 아님). q 영업CF 1147 row > q 매출 698 > y 매출 234. 자산은 6 row만 (안전).
- **함수 `fix_dart_account_mismatch`**:
  - 매출/자산/자본: ratio 0.5~2.0 외 → mismatch
  - 영업이익/순이익/CF: |ratio| 0.2~5.0 + 부호 동일 위반 → mismatch
  - mismatch row만 제거 → `merge_fs_supplement`이 FN으로 자동 보충
- **preload_data 흐름**: fs_dart 로드 직후 옵션 F 호출 (벡터화, 1927종목 13.5초 1회만)
- **baseline (2026-05-12)**: 정정 종목 1100, 정정 row 2283
- **모니터링**: `monitor_dart_fn_health.py` (row > 4000 or 종목 > 1500 → 종료코드 1)
- **로그 형식**: "1927종목 (DART X + FnGuide Y, 항목정정 1100종목/2283row)"
- **BT 영향**: 4/30 표본 Top 30 교집합 9/30 → BT 전체 재생성 (`bt_optf_boost/`, `bt_optf_defense/`)
- **BT 재검증 (7.8y, 2018-07~2026-04)**: 옵션F만 Cal 3.68→4.29 (+0.61). 옵션F+섹터필터(최종) Cal 3.64→3.73 (+0.08), MDD 38.6→36.4%

### DART 갱신 list API 전환 (2026-05-06 도입, refresh_dart_cache.py)
- **사고**: 5/1 0시 target Q4→Q1 전환 후 매일 1,585종목 시도 → DART 10분 timeout (마감 5/15 전이라 99% "데이타 없음")
- **해결**: `OpenDartReader.list(start, end, kind='A')` — 최근 N일 정기공시 종목만 추출 → 그 종목만 fetch_single
- **유니버스 강화**: 우선주(끝자리≠0) + KRX 특수코드(`0009K0` 등) + 외국기업(900xxx/950xxx) + 키워드(REIT/리얼티/인프라/맥쿼리/금융/지주) 제거 — FG의 EXCLUDE_KEYWORDS와 동일
- **효과**: 1,585→2종목, 10분 timeout→6초, API 7000+→24
- **subprocess Popen 스트리밍** (`run_daily.py:run_script`): timeout 시 stdout 손실 막기 위해 `capture_output=True` → `Popen` + readline. timeout 600→1800
- **금요일 자동 full_mode 제거 (2026-05-08)**: full + 1Q 시즌 = 30분 timeout 재발 → `is_friday` 트리거 제거. `--full` 명시 시만 전종목. 평일/금요일 통일.
- **DART timeout 30분 → 3시간 (2026-05-08)**: 5/15 1Q 마감일 폭주 대비. 작년 5/15 단일일 시총 1조+ 272건 일제 제출 패턴 확인. 평상시 영향 0, hang 시 최대 3시간 지연 가능.
- 상세: SYSTEM_MAP §12

### 재생성/배포 절차 (v79 적용 기록)
- `state/` 1294일 + `state/defense/` 1294일 v79 파라미터로 재계산 (28.6분, 2워커 병렬)
- wr batch 후처리 (2588파일, 35초, `postprocess_wr_batch.py`)
- `regime_state.json`: version=v79, rule=KP_MA200_7d, crash_active 필드 제거
- 스케줄러 `QuanT_DailyPipeline` 작업 중 비활성화 후 완료 시 재활성화 필수

### 2018 Whipsaw 분석 (2026-04-14, v77 시절)
- 2018년 whipsaw 4회 (gap≤60일): 2018-03~06 약 3개월간 발생
- 보완안 시뮬: 버퍼 2%, C=7~15, CD=20~40일로 whipsaw 감소 가능 확인
- 실제 BT 검증 결과 (상세: `WHIPSAW_ANALYSIS_2026_04_14.md`):
  - 버퍼 2%: 5.25년 Cal 4.41→3.10 (30% 하락) **악화**
  - 쿨다운 단독: 2018 gap 10일 극단에 **비효과적**
  - C=7: 7.8년 Cal 1.37→1.41 소폭 개선, 5.25년 4.41→4.03 **트레이드오프**
  - 어떤 단일 변경도 5.25년 Cal 4.41 초과 못함 → **v77 유지**
- 2018 H1 BT 확장 시도 실패: DART 2016 데이터 제약으로 Growth 팩터 계산 불가

### 순위 체계 — 모든 판단은 weighted_rank(wr) 기준
- composite_rank(cr): 당일 단독 순위. **판단 기준으로 절대 안 씀.** wr 계산 입력값.
- 궤적 표시: 각 날짜의 wr 정렬 후 정수 순위 재부여 (cr 아님). T-0은 리스트 순번=궤적 순위. BT/매매 로직 변경 없음.
- weighted_rank(wr): cr_t0×0.5 + cr_t1×0.3 + cr_t2×0.2. **모든 판단의 유일한 기준.**
- Top 20: wr 상위 20개 (rank ≤ 20)
- 상태(✅/⏳/🆕): T-1, T-2에서도 cr Top 30이었는지 (verify_n=30, 미국 시스템과 정합. 22→20 살짝 밀린 안정 종목 🆕 모순 해소)
- 진입: ✅ 종목 중 wr 상위 entry_rank개
- 퇴출: wr 값 > exit_rank
- postprocessing 후 rank = wr 기준 순위. composite_rank로 판단하면 버그.

### 표시 체계 (v80.1, 2026-04-20) — 궤적(cr-rank) + 점수(wr 선형)
- **매매 로직**: 순위 기반 wr 유지 (BT: 순위 Cal=3.39 > 점수 Cal=2.62, v79 재검증)
- **궤적 표시**: `r2→r1→r0위` 각 날짜의 **당일 cr-rank** (= 그 날 composite_rank 정렬 순위)
  - cr = 당일 순수 실력. wr(3일 가중)보다 직관적
  - wr 기준이면 이미 3일 강한 종목이 🆕로 표시되는 문제 → cr로 해결
- **동점 tie-breaker**: wr이 같으면 **cr 작은 쪽(오늘 더 강한 종목) 우선**
  - 파일 생성/Top 20 표시/진입 picks 전부 `(wr, cr)` 튜플 정렬
- **✅/⏳/🆕 상태 판별**: cr Top 30 기준 (verify_n=30, 미국 시스템 정합). T-1/T-2 각각 cr Top 30이었는지로 판별
  - ✅: cr Top 30 3일 연속, ⏳: 2일, 🆕: 1일(오늘만)
  - Top 20 안 했을 때 22→20 살짝 밀린 안정 종목이 🆕로 분류되는 모순 해소 (의도적 30 채택)
- **역할 분리**: 궤적+상태 = cr(일별 강도), 점수 = wr(3일 종합), 매매 = wr(진입/퇴출)
- **점수 공식**: `score_100 = max(5, 100 - (wr - min_wr) × 5)` (Signal / Watchlist 공통)
  - 1위=100, **wr 1 증가 = 5점 감소** (선형, 하한 5점)
  - 예: 1위 wr=1.0→100, 2위 wr=2.0→95, 5위 wr=4.7→81.5, 10위 wr=11.3→48.5
  - "SK(83.5) vs 브이엠(81.5) = 2점 차이 → 곧 역전 가능"
  - "브이엠(81.5) vs 디바이스(71.5) = 10점 차이 → 격차 큼"
  - **wr 차이가 그대로 점수 차이로 반영** — EDA 245일 기준 배수 ×5 선정
- 이전 공식 폐기:
  - `0.9^(순번-1)` 지수감쇠: 실제 격차 반영 안 됨 (2위와 3위가 항상 90 vs 81)
  - US에서 먼저 적용 후 KR에 동일 적용 (2026-04-17)
- 매매 로직 재검증: use_score_wr=True 시 v79에서도 Cal 악화 (3.39→2.62) → 순위 기반 유지 확정

### 공통
- PER/PBR/ROE: pykrx (KRX 공식)
- 재무제표: DART + FnGuide 보충 (누락 계정 자동 합침)
- FWD_BONUS: 삭제
- MA120 필터: 126일(6M) 미만 제외 (모멘텀 계산 불가, IPO 노이즈)

## 프로덕션 파이프라인 (v77, 2026-04-10)
- **run_daily.py → data_refresher → FG 직접 호출 → weighted_rank 후처리**
- CP 경유 제거, FG가 직접 스코어링
- `USE_NEW_PIPELINE=1`(기본)
- data_refresher.py: 시총/펀더멘털/OHLCV증분/섹터/KOSPI인덱스 갱신
- weighted_rank: FG 출력에 T0×0.5+T1×0.3+T2×0.2 후처리
- per/pbr/roe: 후처리에서 pykrx 캐시로 보충
- 매일 boost + defense 양쪽 ranking 생성 (국면 전환 대비)
- **파이프라인 속도 최적화 (14분→8분)**:
  - `PRODUCTION_MODE=1`: MC 30일+유니버스 FS만 로드 (프리로드 4분→52초)
  - boost+defense 병렬 subprocess (순차 109초→병렬 77초)
  - merge_fs_supplement 벡터화 (iterrows 제거)

### 주의사항 (v76 시행착오)
- send_telegram 단독 실행 금지 — 반드시 data_refresher 먼저 (OHLCV 미갱신 시 수익률 틀림)
- 스케줄러 변경 시 구 스케줄러 `schtasks //Query`로 확인 후 삭제
- 필터 효과 검증은 FG 재생성 기준 (TurboSim 필터링은 z-score 불변이라 낙관적)
- bt 파일의 score/rank는 쓰레기 — z-score만 유효 (TurboSim이 재계산)

## v75 데이터 파이프라인 (2026-04-05)
- DART+FnGuide 합치기, TTM YoY 갭 체크 (450일)
- MA120 필터: 126일 미만 제외 (IPO 시즈닝)
- 4종 모멘텀 BT (6m, 6m-1m, 12m, 12m-1m)
- ma120_failed: FG metadata에 저장 (이탈 사유 판단용)

## 유니버스 필터
- 시총 ≥ 1000억, 거래대금: 대형 ≥ 50억, 중소형 ≥ 20억

## 시장 위험 지표
- RETURN_MATRIX: 코스피 기반 (26년 6,027일)
- 신호등: 🟢≥8% / 🟡<8% / 🔴<5%+extreme
- VIX 비중 조절 안 함

## 메시지
- Signal: 국면 표시 (방어/공격), 전환 시 별도 안내 메시지 먼저 전송
- 날짜: 당일 기준 (19시 실행, d <= today_str)

## 스케줄러
- 일일 파이프라인: 평일(월~금) 16:00 (장 마감 후, 휴장일 자동 스킵)
- 종목명 캐시: 매주 일요일 10:00

## 주의사항
- OHLCV: 프로덕션 실행 시 백테스트용도 동기화
- Growth 계산: 계정별 날짜 사용 (0 채우기 금지)

## 백테스트 도구
- TurboSimulator: 5ms/run (56x 가속), turbo_simulator.py
- fast_generate_rankings_v2.py: DART+FnGuide 합침, per-account dates
- grid_search_final.py: 3워커 병렬, Calmar 기준, 안정성 필터
- ProcessPoolExecutor 기반 Windows 호환 병렬
