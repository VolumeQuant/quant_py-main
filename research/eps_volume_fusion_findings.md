# KR PRODUCTION × KR EPS 융합 연구 (2026-06-13 시작)

> 수천만원 걸린 의사결정. 면밀 검증 필수. 진행 중 — 단계별 기록.

## Step 1: 두 시스템 특징 (확정)

| | VOLUME (production v80.27) | KR EPS |
|---|---|---|
| 신호 | 실현 성장(DART rev_z/oca_z) + 가격모멘텀(12m) | **NTM(향후12M) EPS 추정치 90일 상향 모멘텀 + 가속보정(adj_score)** |
| 방향성 | 백워드(이미 일어난 실적) | **포워드(애널이 앞으로 좋아질 거라 추정 상향)** |
| 데이터 | DART+FnGuide(actuals) + pykrx | yfinance 애널 컨센서스 추정 |
| 유니버스 | ~1900 (소형 포함, 필터링) | 474 대형·중형(애널 커버 있는 것만) |
| 가중 | V0.15 Q0 G0.55 M0.30 +신팩터 +과열캡 | adj_score(추정상향) + 품질필터 + 저평가 |
| 검증 | 7.4년 BT, WF, 인접CV 통과 | **BT0 (cold start), 8일 live, paper 단계** |
| 룰 | wr 3일, E3X6S3, regime cash | 3일확인 top3, 매도 10위밖/실적하락 |

EPS score 공식: `seg1+seg2+seg3+seg4` (NTM 인접스냅샷 %변화 합) × `(1+clamp(가속/30, ±0.3))`.

## Step 2: EDA — 직교성 ✅ 확인 (융합 가치 있음)

**EPS 추정상향 신호 vs 볼륨 팩터 상관 (2개 독립분석 일치):**
- 내 분석(546행): score vs G **0.25**, vs M 0.28, vs V −0.15
- 기존 step2_corr(101행): **growth_s vs NTM −0.067**(거의 0!), rev_z −0.16, m_score 0.29
- → **EPS 추정상향은 볼륨 실현성장(G)과 거의 직교 = 새로운 정보 = 융합 유망**
- ⚠️ rev_growth는 G와 0.74 중복 → 팩터화 X (이건 이미 G에 있음)

**겹침**: EPS 474 중 볼륨 랭킹에 ~102~145종목(45%, 대형·중형만). 소형은 NTM 커버 없음.

## ❌ 치명적 제약: 과거 NTM 데이터 없음 → factor-BT 불가

- yfinance는 **현재 추정치만** 제공 → 7d/30d/60d/90d 스냅샷은 시스템이 **직접 시계열 저장**한 것. **저장 시작 = ~2026-05-13**. 그 이전 history 없음.
- 따라서 NTM 기반 팩터를 **볼륨 BT기간(2019-2026)에 backtest 불가.**
- KR_EPS_V84_PORT_PLAN.md 공식 명시: "cold start(BT0), 실자본은 60일 KR BT 통과 후, 그 전까진 production이 실자본 주력."
- KOSDAQ NTM 커버리지도 빈약(extension_results: 대부분 snap_ok_count=0).

## 융합 경로 3가지 (제약 반영)

| 경로 | 가능성 | 검증 | 리스크 |
|---|---|---|---|
| **A. 컨센서스 history 취득**(DataGuide 등 유료) → 다년 NTM 복원 → 정식 factor-BT | 가능하나 데이터 비용/공수 | ✅ 볼륨 수준 검증 가능 | 데이터 취득 결정 필요 |
| **B. forward paper-trade 융합**(60일+ 누적) | 즉시 가능 | ⏳ 느림, 실시간만 | 실자본 전까지 검증 지연 |
| **C. 포트폴리오 배분**(볼륨 X% + EPS Y%) | 구조적 가능 | ❌ EPS 자체 미검증 | 미검증 시스템에 자본 배분 = 시기상조 |

## 잠정 결론 / 다음 단계
- **직교성은 진짜** → 융합은 이론적으로 타당.
- **단 현재 데이터로는 rigorous BT 불가** → "유망"이지 "검증"이 아님. **실자본 투입 금지(검증 전).**
- 권장: ① 팩터 설계(NTM z-score) + forward 추적 시작(B) ② 데이터 취득 가능성 조사(A, 사용자 비용결정) ③ 검증 전 실자본 X.

## Step 3: 팩터 설계 + 메커니즘 실험 (2026-06-13, path A)

**팩터**: `ntm_z = winsorize(zscore(adj_score), ±2)`, 단 **num_analysts≥8만 신뢰**(미만/미커버=0). `fused = volume_score + 0.2×ntm_z`.

**노이즈 결함 발견·수정**: min_analysts 필터 없으면 티에스이(adj_score 151.8, **애널 2명**)가 +4σ로 융합 #1 급부상 = 노이즈 아티팩트. 애널수 통제 필수(적은 애널 추정변화는 노이즈). min≥8 적용 시 제거됨.

**메커니즘 (06-12, w0.2, min8, winsor±2)** — 융합 top6: 제주(1)/삼성(2)/디바이스(3)/에이피알(4)/SK(5)/에이치브이엠(6):
- 삼성 cr5→2 (애널35, ntm_z+1.99 추정상향), 에이피알 cr7→4 (애널25, +0.81) 승격
- **SK cr1→5 강등** (애널33, ntm_z−2.0 = 애널이 SK forward EPS 하향) ← 가장 consequential·미검증 call
- 엔씨소프트 cr71→32 (애널17, +2.0)이나 볼륨점수 낮아 top 못 옴(고EPS-저볼륨 지배 안 함, 정상)

**미검증 리스크**: 융합이 SK(볼륨#1)를 #5로 내리는 게 맞는지 forward로만 판정. w0.2·min8·winsor±2는 BT 없이 정한 값(forward 튜닝 필요). 커버 47종목(대형 한정).

**다음**: forward 추적기로 매일 volume-top3 vs fused-top3 + 각 forward수익 누적 → 60일+ 후 융합>볼륨 여부 판정. 실자본 전.

## Step 4: FnGuide 컨센서스 검증 + 제2소스 구축 (2026-06-13)

**계기(사용자)**: yfinance 부실하면 FnGuide로 교차검증하면 되지 않나 → 연쇄 성과.

1. **FnGuide get_consensus_data 버그 수정** (commit): analyst_count=1 하드코딩 → 실제 '추정기관수' 컬럼(table[7]) 파싱. 검증: 티에스이 yf2=FnG2 일치.
2. **yfinance 데이터 검증됨**: 예상EPS가 FnGuide와 ±14% 일치(정의차이) → yfinance 입력 신뢰 가능. 티에스이 12k는 가짜 아님(FnG도 10.8k).
3. **티에스이 저커버리지(2명) 양 소스 확정** → 노이즈 필터 우려 데이터 근거 확보.
4. ⭐ **FnGuide 커버리지 = yfinance의 2배**: 샘플 25종목서 FnG 68% vs yf 35%(168/474). KR 네이티브라 당연.
5. **fnguide_consensus_snapshot.py 구축**: 시총≥2000억 943종목 일별 FnGuide 컨센서스(fwd_eps/per/추정기관수/목표가) 스냅샷 → data_cache/fnguide_consensus_history.parquet 누적. 표본20 100%커버·애널수정상 검증. 매일 쌓으면 yfinance보다 나은 NTM revision history(향후 BT용).

**정정 기록(투명)**: Step3에서 티에스이를 "stale, 안 변했다"고 보고했으나 오류 — 실제 NTM은 6175→12149(2배) 변함. 점수 요약만 보고 원천(NTM값) 미확인한 careless error. 사용자 지적으로 정정. 교훈: money-critical 주장은 요약 아닌 원천데이터까지 확인.

**다음**: ① FnGuide 일별 스냅샷 스케줄러 등록(history 축적) ② 충분히 쌓이면 yfinance→FnGuide 소스전환/블렌드 ③ forward 추적기에 필터/무필터/애널가중 3버전 비교.

## Step 5: 자동화 검증 + 더 좋은 융합방법 (Phase 1-2, 2026-06-13)

**자동화 검증(실행으로 확인)**: ✅ 스케줄러 QuanT_EPS_Fusion_Daily 평일17:30 등록. ⚠️→✅ 추적기 **overwrite 버그**(매일 돌면 이전기록 삭제) 발견·수정(append+dedup). ⚠️→✅ NTM **0글리치 필터**(SK ntm_30d=0→가짜 -80 score로 잘못 강등, 168중 12종목 영향) 추가. wrapper eps_fusion_daily.py 커밋.

**더 좋은 융합방법(BT불가→메커니즘·견고성)**:
- EPS신호: adj_score가 가장 직교(corr 0.41 < eps_raw/chg 0.45) → 현 선택 맞음.
- ⚠️ **factor-fusion 근본약점=가중치 민감**: 06-12 additive에서 w0.1=삼성없음 / w0.2=삼성3위 / w0.3=삼성1위. **검증불가 임의 가중치가 답을 좌우.** 방법(add/rank)별로도 날마다 발산.
- rank-bounded(랭크 ±N 제한)가 additive보다 견고하나, 모든 factor-fusion이 가중치 문제 공유.

## Step 6: ★제3의 방법 + 핵심 통찰 (Phase 3)

**볼륨 top10 × EPS 신호(06-12)**: top10 중 **8개가 EPS 커버없음**(제주·디바이스·티에스이 등 소부장 애널0~2명). 볼륨 top3(SK/제주/디바이스)에 EPS 정보 0(SK글리치, 제주·디바이스 무커버). 교집합(볼륨top15 ∩ EPS강한상향)=**1종목(삼성)뿐.**

★**핵심 통찰**: **두 시스템은 구조적으로 다른 유니버스를 본다** — 볼륨=커버없는 소부장 소형주(핵심알파), EPS=커버되는 대형주. 그래서:
- 어떤 signal-fusion도 **대형주 소수만 건드림** → 볼륨의 소형주 알파(제주·디바이스) 개선 불가.
- 게이팅/교집합도 무커버라 실전 픽 평가 못 함.
- → **신호융합이 아니라 포트폴리오-레벨 분리(2개 sleeve)가 자연스러운 답**: 볼륨sleeve(소형 소부장, 검증된 알파) + EPS sleeve(대형 추정상향, 다른 종목=분산). 자본배분(예 70/30). 단 EPS sleeve는 아직 미검증(BT0)이라 소액/관찰.

**최종 정리**: 융합은 "유망하나 구조적 한계+미검증". signal-fusion은 가중치문제+대형주 한정. **실전 답 = 볼륨 단독(검증됨) 주력 + EPS는 별도 sleeve로 분리 관찰**(섞지 말고). 자동화로 데이터 축적 중 → 60~90일 후 EPS sleeve 자체 검증 가능.
