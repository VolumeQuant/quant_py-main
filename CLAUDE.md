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

# 🇺🇸 US 전략 — eps-momentum-us (v71)

> 경로: `C:\dev\claude code\eps-momentum-us`

- EPS Revision Momentum, conviction z-score 기반, **균등비중**
- conviction: adj_gap × (1 + max(up30/N, min(|eps_chg|/100, 1)))
- 점수: 일별 z-score(30~100) → 3일 가중(T0×0.5+T1×0.3+T2×0.2), 빈 날=30점
- 진입: 3일 가중 Top 3 + ✅(3일 검증) + min_seg ≥ 0%, 슬롯 5
- 퇴출: part2_rank > 15 OR min_seg < -2% OR -10% 손절
- composite_rank=당일 conviction 순위(추이 표시), part2_rank=3일 가중 순위(매매)
- RETURN_MATRIX: S&P500 기반 (26년 6,593일), VIX는 yfinance 최신 보완
- 비중 조절 안 함 (알파가 공포 구간에서 발생)
- 상관관계: 🔗 유사도% + BFS 그룹핑 + 택1/택1~2 권장

---

# 🇰🇷 KR 전략 — quant_py-main (v77.1, 2026-04-14)

> 경로: `C:\dev\claude code\quant_py-main`

## 국면전환 전략 (v77.1 Crash Cash 추가, 2026-04-14)

### v77→v78→v77→v77.1 경위
- 2026-04-13 저녁: v78(7.8년 BT Cal=3.40) 프로덕션 적용 직후 5년 프로덕션 -80% 확인
- 2026-04-13 밤: v77 복원 + ranking 2586개 재계산 (`9e4a2cc98`)
- 2026-04-14 오전: 2018 whipsaw 보완안 탐색 → v77 기본 유지 (`05fb073bf`)
- 2026-04-14 오후: **3-tier 시스템 발견** → v77.1 적용

### v77.1 핵심 추가: Crash Cash
방어 모드 중 **KOSPI 20일 수익률 < -20%** 발동 시 → **전량 청산, 현금 보유**.
조건 해제 시 방어 모드 자동 재진입. 공격 전환 시 자동 해제.

**3-tier 시스템**:
1. **공격 (boost)** — KOSPI > MA200, 5일 확인 → Growth 중심
2. **방어 (defense)** — KOSPI < MA200, 5일 확인 → Momentum + Value
3. **현금 (cash)** — 방어 중 KOSPI 20일 수익률 < -20% → 전량 청산

### 국면 규칙 (KP_MA200_5d + Crash20)
- **KOSPI > 200일 이동평균** = 공격, 미만 = 방어
- **5일 연속 확인** 후 boost↔defense 전환
- **defense 상태에서 20일 수익률 < -20%** → cash 전환 (확인일수 없이 즉시)
- 모든 전환 시 기존 포트폴리오 **전량 청산**
- 전환 빈도: 7.8년 BT 21회 (boost↔defense) + cash 발동 8일

### 공격 모드 (Boost) — KOSPI > MA200 (5일 확인)
- **V5 + Q0 + G65 + M30**
- G 내부: 3팩터 **rev_z 50% + oca_z 30% + gp_growth_z 20%**
- 모멘텀: **12m-1m** (최근 1개월 skip)
- 진입: rank ≤ 7, 퇴출: WR > 8, **슬롯 3**
- 손절: -10%, 트레일링: -15%

### 방어 모드 (Defense) — KOSPI < MA200 (5일 확인)
- **V30 + Q5 + G10 + M55**
- G 내부: 2팩터 **rev_accel_z 50% + op_margin_z 50%**
- 모멘텀: **6m-1m** (최근 1개월 skip)
- 진입: rank ≤ 3, 퇴출: WR > 6, **슬롯 7**
- 손절: -10%, 트레일링: -15%

### 현금 모드 (Cash) — KOSPI 20일 수익률 < -20% (즉시 발동)
- 모든 포트폴리오 **전량 청산**
- 신규 매수 **없음**
- 20일 수익률 ≥ -20% 회복 시 방어 모드 복귀
- 또는 boost 전환 시 자동 해제

### 성과 (v77.1 기준)
- **5.25년 BT (2021-01~2026-04)**: Cal=**4.58**, CAGR=128.5%, MDD=28.1%
  - cash 발동 0일 (COVID 구간 밖) — v77과 동일
- **7.8년 BT (2018-07~2026-04)**: Cal=**1.50**, CAGR=81.8%, MDD=54.5%
  - v77 대비 **Cal 1.35→1.50 (+11%)**, **MDD 58.9%→54.5% (-4.4%p)**
  - cash 발동 8일 (2020-03 COVID 급락 구간)
  - 2020 수익 +60.4% → +77.7% (COVID 저점 현금 도피 + 반등 재진입)
- 2018 whipsaw 4회 구간(2018-02~06)은 여전히 BT 범위 밖 (DART 2016 Growth 로직 이슈)

### 데이터 품질 필터 (v77)
- pykrx PER/PBR/EPS/BPS 전부 0 → 제거
- ROE: pykrx EPS>0 → pykrx. EPS=0 → DART TTM 폴백 (지배주주NI/지배주주자본 → 지배주주NI/자본 → 당기NI/자본 → 스킵)
- ROE NaN → 필터 스킵 (GPA/CFO로 Quality 평가)
- 우선주 제거 (티커 끝자리 ≠ 0)
- 금융 키워드: 생명/화재/IB투자/벤처투자/자산운용/신탁

### 2018 Whipsaw 분석 (2026-04-14)
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
- 상태(✅/⏳/🆕): T-1, T-2에서도 rank ≤ 20이었는지 (wr 기준)
- 진입: ✅ 종목 중 wr 상위 entry_rank개
- 퇴출: wr 값 > exit_rank
- postprocessing 후 rank = wr 기준 순위. composite_rank로 판단하면 버그.

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
