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

> **버전 변경 이력 / 거부된 옵션 / 과거 사고 상세 / 검증 단계 기록**: `C:\dev\CHANGELOG.md` (자동 로드 X — 과거 결정 근거가 필요할 때만 검색).
> 이 파일(CLAUDE.md)은 **현재 운영 기준만** 담는다. 전략 교체 시 맹점 제로 체크리스트: `C:\dev\SYSTEM_MAP.md`.
> 코드 경로: KR = `C:\dev` (루트, regime_indicator.py / backtest/fast_generate_rankings_v2.py 등). US = `C:\dev\claude code\eps-momentum-us`.

---

> 🇺🇸 **US 전략 노트는 US 레포에서 관리**: `C:\dev\claude code\eps-momentum-us\CLAUDE.md` (US 작업 시 Claude가 자동 로드). 이 파일엔 공통 작업원칙 + KR만.

# 🇰🇷 KR 전략 — quant_py-main (v80.27 얇은 밸류트랩 필터, 2026-06-10)

> 코드 진실: `regime_indicator.py` `get_regime_params()`. 아래는 그 코드 기준 현재 production 파라미터. 변경 이력은 CHANGELOG.md.

## 현재 운영 파라미터 종합 (v80.23 기준, 코드 검증됨)

### 국면 (regime) — KP_MA_CROSS (v80.18)
- **KOSPI MA20 > MA80 = boost, 미만 = defense**, **5일 연속 확인** 후 전환 (`SHORT_MA=20, LONG_MA=80, CONFIRM_DAYS=5`)
- (옛 단순 MA200/MA220 비교는 호환 코드로만 유지 — v80.18에서 cross로 교체)
- 모든 전환 시 기존 포트폴리오 **전량 청산**
- `MA_PERIOD=200` 상수는 QoQ 패널티 SG6 거리 계산 등 호환용으로만 잔존

### 공격 모드 (boost) — KOSPI MA20 > MA80
| 항목 | 값 |
|---|---|
| V/Q/G/M | **0.15 / 0.00 / 0.55 / 0.30** |
| G 내부 (3팩터) | rev_z 0.4 / oca_z 0.4 / gp_growth_z 0.2 (v80.6.1) |
| 모멘텀 | 12m |
| 가산 신팩터 (v80.20) | + mom_10_z × **0.05** + vol_low_z × **0.06** |
| 과열 캡 (v80.23) | + **pen_cs × 0.2** (성장-밸류 괴리). 가격반응 PER(시총/TTM지배순이익) 단면 z 중 비싼 쪽만 감점(`min(ey_z,0)`), 싼 건 무보상. `FACTOR_OVERHEAT_W=0.2` |
| 진입/퇴출/슬롯 | rank ≤ **3** / rank > **6** / **3슬롯** (E3**X6**S3, v80.24) |
| 손절 / 트레일링 | **둘 다 없음 (v80.22 SL 제거, v80.21 TS 제거)**. 매도는 rank>4 단독 |
| QoQ 패널티 (D6, v80.12) | 강한 boost(KOSPI > MA220 × 1.06)에서 영업이익 QoQ < +20% → G × 0.7 |
| 계절성 패널티 | curr 식 (Q2+Q4)/(Q1+Q3) > 1.4 → G × 0.3, 단 min/max(4Q) > 0.2 면제 (v80.7/9/10) |

### 방어 모드 (defense) — KOSPI MA20 < MA80
- **cash 100%** (`ENTRY_RANK=0`, v80.16) — 신규 매수 안 함, 보유 종목만 룰대로 청산
- 참고 파라미터(청산 기준): V35 Q15 G15 M35, G 2팩터 rev/oca 0.8/0.2, 6m-1m, EXIT rank > 8, 슬롯 5, SL −10% (v80.21: TS 제거 — defense는 cash라 원래 무효)

### 공통
- **wr 가중치 (v80.13)**: T-0 × 0.4 + T-1 × 0.35 + T-2 × 0.25 (당일 비중 ↓, 3일 검증 강화)
- **순위 기반** (점수 기반 아님 — KR 시장 종목수 ~1900, score 표준편차 노이즈 커서 순위가 명확 우월. 재검증 거부)
- **메타 자산 배분 (사용자 영역, 2026-06-08 분기로 변경)**: 투자금의 **70% 시스템 + 30% 현금성**(MMF/RP/CMA/예수금). 리밸런싱 = **분기 첫 거래일(1·4·7·10월) 70:30 정기 + ±5%p 밴드**(분기 사이라도 시스템 비중 65~75% 이탈 시 즉시 리밸, 미세 드리프트 <2~3%p는 no-trade로 세금 절약). **매년→분기 변경 근거(BT)**: 70/30 블렌드(현금 연3%) 7.4년 시뮬에서 **매년 Calmar 3.56(주기 중 최악, MDD 23.4%) → 분기 4.14(MDD 19.2%) / 밴드만 4.15(MDD 18.4%)**. 밴드가 핵심엔진(필요시 정확 작동), 분기는 보조루틴(밴드 놓침 방지). 리밸 시 시스템 매도분 거래세 0.15% 드래그는 미미. 시스템 코드와 무관, 본인 메타 영역. US는 80:20(아직 매년, 미검증), KR이 더 보수적인 이유 = KR 약세장 깊이 + 트라우마 대응. 상세: `~/.claude/projects/C--dev/memory/project_cash_buffer_rule_kr.md`
  - **2026-06-14 정련 (사용자 공격성향·젊음)**: 현금가정 **3%(달러 수시형 발행어음, 보수적·폭락줍줍용 언제든인출)**. 버퍼는 **리스크 다이얼**(Calmar 버퍼크기 무관 평평 ~2.0~2.1) — 수익장치 아님. 공격형은 **90/10**(CAGR~60·MDD29) 또는 **80/20**(53·26) 권장(70/30은 보수형). **재진입 배치**: 강세전환(5일확인) 시 시스템 sleeve를 3종목 1:1:1 전량, 남기는 현금=버퍼(공격형 10~20%). 점진진입 불필요. **KR/US 비중**: 60/40 한국틸트(검증깊이+세금+모니터링), US40=환율헤지/기회/모델분산. ★KR/US 분산은 폭락보험 아님(위기 동반하락)—폭락보험은 현금버퍼. 상세: `project_kr_regime_cash_policy_2026_06_14.md`
  - **국면전환 기준 재검증 (2026-06-14, 최고 레버리지)**: full-config 75조합(단기MA×장기MA×확인일) 재탐색 — **현행 20/80/5 유지가 정답**. 합산 2위(1위 15/80/5와 +0.015=노이즈)지만 ★약세장(2022-23) WF 최소 Cal **1.40으로 1위**(합산 더 높은 후보들은 약세장 0.92~0.97 붕괴=강세장 과적합). 인접CV 확인일0.114/장기MA0.147 안정구간 중앙, 비대칭 무익. **바꾸면 약세장 깨지는 함정.** research: `backtest/_regime_transition_search.py`

## v80.27 얇은 밸류트랩 제외 필터 (대덕류) — 2026-06-10 (배포됨)

> 배포: `backtest/fast_generate_rankings_v2.py` 점수산출 후 **`PER>40 & PBR>0 & PBR<1.5 & 거래대금<50억(단일일)` 종목 제외**. 환경변수 `THIN_VTRAP_DISABLE=1`로 비활성. 다음 16:00부터. 롤백: 필터 블록 제거 + git revert.

**문제:** 지주사/밸류트랩이 PBR 낮아(자회사 장부가) **-1.5σ 밸류 바닥필터 통과** → 추천됨. 대덕(PER184/PBR1.08/거래19억) 06-10 #3 진입권 사고. 회계사기(v80.25 accruals B음수=현금양질)도 아니고 고PBR 모멘텀(브이엠)도 아닌 **"이익 거의 없는데 장부상 싸 보이고 + 거래도 안 되는" 별종**.

**시그니처:** PER>40(이익 미미) & PBR<1.5(장부가 싸게 보임) & 거래대금<50억(유동성 곤란). 대덕 제거, **브이엠(PBR 11.8=고PBR)·정상 저PBR 가치주는 보존**.

**검증(7년 BT):** 수익 **무해 +0.08**(MDD/WF/OOS/LOO 비악화). 제거 카테고리(7년 6종목 32건) **fwd+20d −5.55%/승률 28%** vs 나머지 +3.73%/49% = 일관 열위. 알파가 아니라 **"거래 곤란한 얇은 밸류트랩 제거" 품질필터**. research: `research/auto_bt_kr_holdco_filter.py`.

⚠️ **이 필터가 안 잡는 것**: 고PBR 모멘텀 펌프(제주반도체 PER80/PBR14, 타이거일렉 PER76/PBR6.8)는 대상 아님(의도적, 브이엠 보존 위해). → 모멘텀 펌프는 여전히 **진입≤3 + 3슬롯 분산 + 이탈>6 매도** 구조로 관리. (US 세션 결론과 동일: 가격/모멘텀 필터는 LOWO에서 깨짐.)

## 섹터 표시 정확화 — KSIC 기반 (2026-06-11, 배포됨, 표시 전용·매매 무관)

> 배포: `refresh_ksic_sector.py`로 universe 2615종목 DART `induty_code`(KSIC 5자리) 수집 → `data_cache/ksic_sector_map.parquet`. FG `get_sector_with_override` 우선순위 **수동 override → KSIC(정확) → KRX 대분류 폴백**. 다음 16:00 FG부터 적용, state 재생성 불필요. 증분 갱신: `python refresh_ksic_sector.py`(신규 종목만).

**문제:** KRX 24개 대분류 업종(`업종명`)이 너무 coarse — **'의료·정밀기기' 버킷에 반도체 검사장비(티에스이·미래산업·케이씨텍)·카메라부품(재영솔루텍)·실제 의료기기(인바디)가 혼재** → 전부 '의료기기'로 오표시. pykrx도 동일(같은 KRX 업종). 반도체 세정장비(디바이스이엔지)는 '기계'로 오표시.

**해결 — KSIC 매핑(`ksic_to_sector`):** `261`(칩제조)+`29271`(반도체 제조용 기계)+`272`(정밀계측=반도체 검사장비) → **반도체** / `271` → **의료기기**(진짜) / `273`(광학)·기타 `26`·`28` → **전기전자** / 비반도체 `29` → **기계** / 그 외 → KRX 대분류 폴백. **272→반도체는 사용자 선택**(검사장비 투자체감 일치).

**검증:** 반도체 146(SK·DB하이텍·케이씨텍·미래산업·이오테크닉스·HPSP…), 의료기기 61(클래시스·인바디·레이·뷰웍스 = 진짜 의료만), 폴백 1916(화학/금융/유통 등 KRX 유지). ⚠️ 엣지: HD현대에너지솔루션(태양광 셀)=KSIC 2612(광전 반도체소자)→'반도체' 표시(투자체감과 다름, 진입 시 override 예정). 수동 override(`TICKER_SECTOR_OVERRIDE`)는 KSIC보다 우선(삼성=264지만 미override 시 전기전자, 지주사 등 quirk 보정). research/수집: `refresh_ksic_sector.py`.

## v80.26 표시점수 고정앵커 (1등=100 박제 제거) — 2026-06-09 (배포됨)

> 배포: `send_telegram_auto.py` 점수표시 2곳(Signal L901·Watchlist L1108) → `weighted_score_100()` 호출로 통일. `ranking_manager.py` `weighted_score_100` 가중치 0.5/0.3/0.2→**0.4/0.35/0.25(wr v80.13 일치)** + 앵커 **ws/1.9×100**. **매매 영향 0**(표시만, 진입/퇴출은 순위 기반). 다음 16:00부터. 롤백: 두 곳 인라인 `100-(wr-min)×5` 환원.

**문제(사용자 제기):** 점수가 `100−(wr−1위wr)×5`라 **1등은 항상 100 박제**. 그날 1등이 괴물주든 밋밋하든 무조건 100 (US v112와 동일 문제). EDA: 1등 score 20일간 1.37~1.88 출렁인데 표시는 다 100.

**해결:** 멀티팩터_점수(z합)를 **3일가중(wr과 동일 0.4/0.35/0.25)** → 고정앵커 `ws/1.9×100` clip 0~100. 1등도 강도 반영(약세날 50점대, 보통날 80+, 괴물주 100). **순위(wr)와 동일 가중치라 순위-점수 정합**(어긋남 0). 앵커: 0=score 0(시장평균), 100=1.9(괴물주, 관측 max 1.88).

**왜 3일가중이어야:** 당일 score로 하면 순위(3일 wr)와 기준 달라 어긋남(6위<7위 역전). 3일가중으로 맞춰야 ✅종목 완전 정합. 신규종목(3일 중 빠진 날)은 missing=50위 score fallback(wr PENALTY 50과 정합). + footer 줄간격 compact(매수/매도/시스템 빈 줄 제거). 사용자 "점수는 솔직하게"(앵커 1.9 유지, 강해지면 80점대).

## v80.25 일회성 이익 페널티 (accruals + 분기쏠림) — 2026-06-09 (배포됨)

> 배포: `fast_generate_rankings_v2.py` 계절성 패널티 옆 일회성 페널티 블록(항상활성 + `ONEOFF_DISABLE=1` 킬스위치). regime_indicator/run_daily **무변경**(계절성과 동일 패턴, FG 기본값 사용). 다음 16:00부터 자동 적용. 롤백: `ONEOFF_DISABLE=1` 또는 블록 제거 + git revert.

**문제(사용자 제기):** 에스에이엠티(031330)·삼지전자(037460) 같은 IT유통주가 **한 분기 일회성 이익으로 TTM 뻥튀기** → 06-04~08 에스에이엠티 시스템 **1위**(진입3·슬롯3라 시스템이 매수). 사용자 실제 매수 후 손실. "일회성 스캠을 일괄로 걸러라."

**해결 — 일회성 페널티(일괄, 종목예외 없음):**
- `B = (당기순이익TTM − 영업현금흐름TTM)/자산 ×100` (이익이 현금으로 안 들어옴 = 가짜)
- `C = max(최근4분기 영업이익)/영업이익TTM` (한 분기 쏠림 = 일회성)
- **B>25 AND C>0.7 → 성장_점수 ×0.24** (소프트). PIT(rcept_dt≤base_date), 계절성 패널티와 동일 자리·패턴.

**왜 ×0.24 (하드컷·진입차단 기각):** 7.4년 production-replay(X6 현행) 강도스윕 — **0.30~0.22 무해평탄(Cal~4.48, 2026 +284%)**, 0.20부터 절벽(Cal 4.35·2026 +245.4%, −39p) / hard·진입차단 2026 −25.8p. **0.24 채택**: 에스에이엠티를 **삼성전자 아래(wr 5위)**로 밀되 BT는 0.30과 동급(0.30은 wr 4위로 삼성 위였음). **이유: 에스에이엠티(+393%)·삼지전자(+242%)는 실적이 가짜여도 주가는 폭등 → 0.24로 밀되 강하게 오르면 일부 캡처. 더 세게(0.20) 빼면 −39p 손해([[leave-one-winner-out]]).**

**검증:** MDD 강도무관 동일(공매도 tail은 3슬롯분산+순위이탈이 흡수 — 안 사봐야 상승만 버리고 하방보호 0). 약세장 2022 +6.5% 무해, WF 전블록 ≥baseline(24-26만 개선), 인접 CV 0.014(B22~28×C0.65~0.75×강도), LOWO(제주반도체·엑시콘 제외) 견고. **제주반도체(B21<25)·엑시콘(B20<25) 보존.** 표본검증 06-08 FG: 에스에이엠티 1→4위(진입권 밖), 제주반도체 3→2(승격). 걸린 3종목 전부 반도체/IT유통+accruals 적신호(에스에이엠티·삼지전자·미래반도체).

⚠️ 개인 손실은 한 종목 집중 탓(시스템은 분산+이탈로 흡수). 페널티는 진입권 4위까지만 밀어냄(완전추방=−40p라 안 함). research: `backtest/_oneoff_*.py`

## v80.24 이탈 X4→X6 (과열캡 도입 후 재최적화) — 2026-06-08 (배포됨)

> 배포: `regime_indicator.py` boost `EXIT_RANK: 4 → 6` (진입3·슬롯3 불변) + 메시지 문구("4위 밖"→"6위 밖", send_telegram_auto.py 702행·send_notice_once.py 28행 하드코딩 + 951/1100행은 EXIT_RANK 파라미터 자동반영). **state 재생성 불필요**(매매룰만, 랭킹 불변). 다음 16:00부터 적용. 롤백: `EXIT_RANK 6→4` + git revert.

**계기:** 사용자 "진입/이탈/슬롯 현재가 최적이냐" → 과열캡(v80.23) 도입 후 재최적화하니 이탈 최적이 X4→X6으로 이동.

**왜 v80.17(6→4)과 정반대인가:** v80.17 때는 빡빡한 X4가 과열종목을 빨리 쳐내려 좋았는데, **과열캡(v80.23)이 과열종목을 자동 강등**시키면서 X4의 "빨리 팔기"가 **중복(redundant)**이 됨. 오히려 과열 안 된 승자를 rank 5로 살짝 밀렸다고 조기매도하는 손해만 남음. X6으로 풀면 과열주는 캡이 빼주고 멀쩡한 승자는 더 오래 보유 → 수익↑ MDD↓ 회전↓. (W=0 BT는 X5가 최적, W=0.2는 X6 최적 — 상호작용 입증)

**BT (7.4년, 과열캡 W0.2 baseline, production-replay):** Cal **3.84→4.43**(+15%), MDD 27.1→**25.9%**, CAGR 104→114.7%, **회전 667→385(-42%)**.
- robust 그리드(LOO최악+IS+OOS 최소 기준) **1위** (현재 X4는 7위). raw Cal·IS·OOS·LOO 전부 1위.
- **과적합 아님**: X6 LOO최악(−SK 3.15) > X4 LOO최악(−둘다 3.03) = 어떤 슈퍼위너 빼도 X4 최악보다 안 나쁨. 인접 X5~8 plateau(다 >4.0), W×X 상호작용 W0.2~0.25/X6 정점, WF 4구간 중 3개(약세장 포함) 개선.
- 진입 E3·슬롯 S3는 그대로 최적(전 조합 중 우월), **이탈만** 변경. 미최적화(과적합방지): wr가중치·검증룰·TOP20·슬롯비중.
- research: `backtest/_q4_grid*.py`(E/X/S 그리드+robust+W상호작용)

## v80.23 과열 캡 (성장-밸류 괴리, pen_cs) — 2026-06-05 (배포됨)

> 배포 완료 (2026-06-05): `regime_indicator.py` boost `FACTOR_OVERHEAT_W=0.2` + `run_daily.py` env 전달 + `fast_generate_rankings_v2.py` pen_cs 블록. state 전체 재계산 완료(authoritative). 다음 자동 실행(16:00)부터 자동 반영. 롤백: `FACTOR_OVERHEAT_W` 키 제거 + git revert.

**문제(사용자 제기):** "가격이 폭등/폭락해도 순위가 안 바뀐다." 확인 결과 사실 — V(밸류) 팩터가 동결 pykrx PER(삼성전자 7년간 42.54 고정)이라 가격 예측력 IC 0.01(죽음). v80.20 mom_10/vol_low(0.11)는 G(0.55)에 눌려 체감 약함.

**해결 — 과열 캡:** 매일 `자기 PER = 시가총액(가격반응) ÷ TTM 지배순이익(PIT)` 계산 → 단면 z-score 중 **비싼 쪽만 감점**(`pen_cs = min(ey_z, 0)`, 싼 건 무보상). 주가 오르면 PER↑→감점↑→순위↓ (추격매수 회피), 폭락 시 과열 해소→감점↓. 점수: `... + 0.2 × pen_cs` (boost only).

```python
score += 0.2 × min(zscore(log(시총/TTM지배순이익)), 0)   # 비싼 쪽만 감점
```

- **왜 이 형태만 채택:** EDA(2023-24) + 7.4년 BT로 5개 변형 비교 — 단면 cheap 보상/시계열 PE압축/PBR·PSR/순수 가격이격도/밸류 통째 교체 **전부 top-3 평균수익 악화**(KR top-3은 성장+모멘텀 승자라 밸류 틸트가 모멘텀 희석). **"실적 대비 과열만 감점"(pen_cs)만 유일하게 무해**(top-3 평균 중립 + 승률 84%). 과열 매도(exit) 추가는 redundant(진입 페널티가 이미 rank>4 청산 유발).
- **7.4년 BT (gold-standard 재생성 + production-replay):** Cal **3.14→3.83** (+22%), MDD 28.9→**27.1%**, **WFmin 0.69→1.39**(안정성 대폭↑), OOS 5.85→6.99. 인접 W 0.05~0.3 CV 0.044. **LOO(제룡전기·SK하이닉스 둘 다 제외) +0.7** robust(단일종목 착시 아님). W=0.2 채택(0.15와 동급, MDD·OOS 최선). cap=-0.5/W0.1 peak는 인접급락=과적합으로 기각.
- **변경 파일 3:** `fast_generate_rankings_v2.py`(pen_cs 블록 + JSON overheat_pen 저장 + STORE_OVERHEAT_PEN 모드), `regime_indicator.py`(boost FACTOR_OVERHEAT_W=0.2), `run_daily.py`(env 전달). defense 무변경(cash). state 1822일 authoritative 재계산(state_peg_bt fold).
- ⚠️ 2022-23 약세블록만 소폭 약화(WF 1.64→1.29, 여전히 >1.0)하나 MDD·OOS·전체 개선이 압도. 약세장은 국면 overlay(defense=cash)가 처리. ⚠️ 표시 PER(pykrx)과 pen 기준 ey(시총/TTM순이익)는 출처가 달라 가끔 불일치(제주반도체 표시PER 79인데 pen 0 등) — 표시 nuance, 매매는 ey 기준이 정확.
- research: `backtest/_peg_*.py` (eda4~7 변형비교, bt_grid gold-standard, explore 임계튜닝, fold/rebuild state)

## v80.20 신팩터 — mom_10 + vol_low (가격 자연 반영)

boost 멀티팩터 점수에 단기 모멘텀 + 저변동성 가산. 매일 종가 변동이 ranking에 자연 반영 (분기 G 데이터 90일 불변으로 1등 종목 박제되던 문제 해결 — 사용자 우려 "고객 추격매수 위험").

```python
score = V × 0.15 + G × 0.55 + M × 0.30 + mom_10_z × 0.05 + vol_low_z × 0.06
```
- **mom_10**: 종가 / 10일 전 종가 - 1 (2주 가격 변동률)
- **vol_low**: -1 × (20일 일별 수익률 std) z-score (저변동성 우대)
- 둘 다 cross-sectional z-score (일자별 표준화), ★ 영업일만 사용 (캘린더 인덱스 NaN 자동 필터)
- 변경 파일 3: `backtest/fast_generate_rankings_v2.py` (점수 합산 후 가산), `regime_indicator.py` (FACTOR_MOM_10_W=0.05, FACTOR_VOL_LOW_W=0.06), `run_daily.py` (`_build_mode_env` 환경변수 전달)
- 7년 BT: Cal 2.43→**3.06** (+25%), MDD 31.3→**29.3%** (-2%p), OOS 4.17→**5.60** (+34%), WFmin 0.98. 인접 5x5 grid CV ~0.06 PASS. V/Q/G/M 12 시나리오 재최적화 → V15Q00G55M30 압도적 1위 (변경 X).

## v80.22 변경 — 손절도 제거 (2026-05-28)

7년 비용반영 BT에서 SL−10% 유지가 SL 없음보다 모든 지표에서 살짝 손해(Cal 3.26 vs 3.33, MDD −26.7 vs −26.5, WF min 1.37 vs 1.47), 동시에 연 4회 손절 발동 부담만 있는 worst-of-both. 단일거래 최악도 SL 있어도 갭다운으로 −19% 선까지 깨지는데, SL 없을 때도 rank>4 청산이 −19% 선에서 자연 멈춤 → SL의 보호 효과가 사실상 0. SK하이닉스 leave-one-out도 SL 없음이 우위. 운영 부담(연 4회 손절)의 가장 큰 항목을 데이터 손해 없이 제거.

매도 룰 최종: **3일 가중순위 4위 밖** (단일 조건).

- 변경: `regime_indicator.py` boost/defense `STOP_LOSS: −0.10 → None`
- 연동: `send_telegram_auto.py` SL 로직 None 가드 + 매도룰 메시지 단순화 (둘→하나)
- 연동: `send_notice_once.py` 동일
- state 재생성 불필요
- 다음 자동 실행(16:00)부터 적용

⚠️ 미래 위험: 갭다운 −30%/−50% 같은 극단 case 발생 시 보호 없음. 7년 미발현, 1/3 비중이라 portfolio 임팩트 −15~30% 한도. 롤백 트리거 참조.

## v80.22 롤백 트리거
- 5거래일 KOSPI 대비 알파 −3%p 또는 단일거래 −30% 초과 발생
- 즉시 환원: `regime_indicator.py` boost/defense `STOP_LOSS = -0.10` + git revert

## v80.21 변경 — 트레일링 스탑 제거 (2026-05-28)

비용반영 7년 BT(공식엔진 + production rank 리플레이 양쪽 일치)에서 `TS-8%` 제거 시 회전 360→220거래(−39%)인데 Calmar 우위(중간 3.19→3.32, 고비용 2.77→3.05), MDD도 −26.1→−26.7%로 개선. **SK하이닉스 leave-one-out도 robust**(단일종목 착시 아님). 유일한 비용: 2020-21 코로나형 변동성 boost 구간 −28%p(gross). SL−10% + 순위이탈 유지.

- 변경: `regime_indicator.py` boost/defense `TRAILING_STOP: −0.08 → None`
- 연동: `send_telegram_auto.py` 트레일링 로직 None 가드 + 매도룰 메시지 "최고가 대비 −8%" 제거 (셋→둘). 또한 defense 메시지의 stale 텍스트(MA200 10일 → MA20<MA80 5일) 동시 정정 (v80.18 누락 버그)
- 연동: `send_notice_once.py` 동일 메시지 정리
- state 재생성 불필요 (매매룰만 변경, ranking 점수 불변)
- 다음 자동 실행(16:00)부터 적용

## v80.21 롤백 트리거
- 5거래일 KOSPI 대비 알파 −3%p 또는 코로나형 변동성 급등 구간에서 MDD −10% 초과
- 즉시 환원: `regime_indicator.py` `TRAILING_STOP = -0.08` (보트모드 양쪽) 환원 + git revert

## v80.20 롤백 트리거 (참고)
- 5거래일 KOSPI 대비 알파 -3%p 또는 MDD -8% 초과
- 즉시 환원: `regime_indicator.py` boost params에서 FACTOR_MOM_10_W, FACTOR_VOL_LOW_W 키 제거

---

# 데이터 파이프라인 & 유니버스/필터 (현재 운영)

## 프로덕션 파이프라인
- **run_daily.py → data_refresher → FG(fast_generate_rankings_v2) 직접 호출 → weighted_rank 후처리** (`USE_NEW_PIPELINE=1` 기본)
- data_refresher.py: 시총/펀더멘털/OHLCV증분/섹터/KOSPI인덱스 갱신
- weighted_rank: FG 출력에 wr 가중치(T0×0.4+T1×0.35+T2×0.25) 후처리, per/pbr/roe는 pykrx 캐시로 보충
- 매일 boost + defense 양쪽 ranking 생성 (국면 전환 대비)
- 속도 최적화: `PRODUCTION_MODE=1` (MC 30일+유니버스 FS만 로드), boost+defense 병렬 subprocess, merge_fs_supplement 벡터화
- 시작 시 `git pull --rebase origin main` 자동 (working tree clean 시) — 다른 PC push 자동 반영
- **B 검증/재시도 안전망**: ranking 종목 수 < **150** 시 채널 발송 차단 + 개인봇 알림 + 30분 sleep + 재시도 (wholesale 사고 감지선; 약세장 200대는 정상)
- 주의: send_telegram 단독 실행 금지 (반드시 data_refresher 먼저, OHLCV 미갱신 시 수익률 틀림)

## 유니버스 필터
- 시총 ≥ 1000억, 거래대금(20일평균): 대형(1조+) ≥ 50억, 중소형 ≥ 20억
- 우선주 제거 (티커 끝자리 ≠ 0), KRX 특수코드/외국기업(900xxx/950xxx) 제거
- 금융 키워드 제거: 생명/화재/IB투자/벤처투자/자산운용/신탁/REIT/리얼티/인프라/맥쿼리/지주
- **KRX "금융" 섹터 필터**: 산업지주사(SK스퀘어/LG/CJ/HD현대 등) + 금융사 통합 제외 (이름에 "지주" 없어도 KRX 분류로 차단). 본업 사업체(SK하이닉스=전기전자 등)는 영향 없음
- MA120 필터: 126일(6M) 미만 제외 (모멘텀 계산 불가, IPO 노이즈)

## 데이터 품질 필터
- pykrx PER/PBR/EPS/BPS 전부 0 → 제거
- ROE: pykrx EPS>0 → pykrx. EPS=0 → DART TTM 폴백. ROE NaN → 필터 스킵 (GPA/CFO로 Quality 평가)
- **(d)** DART 분기보고서 8개(2년) 미만 제외 / **(d')** PIT 버전 (rcept_dt ≤ base_date 분기만 카운트)
- **(e)** G 서브팩터 5개 이상 동일값(|v|>1.5) = capped 종목 제외
- **-1.5σ 단일팩터 바닥 필터**: V/Q/G/M 4팩터 중 하나라도 -1.5σ 미만이면 제외. baseline(유지)이 BT 최선 (완화/제거 모두 성과 하락). **부작용**: 주가 급등으로 PER/PBR 비싸진 대형 전력주(HD현대일렉트릭, 제룡전기 등)가 V -1.5 미만으로 탈락. `EXTREME_MODE` env로 A/B/C/D 실험 가능 (미설정=baseline)
- **TTM PER/ROE 밸류 조사 → annual 유지 (2026-06-15~16, 끝장검증)**: 사용자 "PER만 연간(pykrx)이라 불일치(PCR/PSR은 TTM)" 제기 → `USE_SELF_PER`(PER=시총/지배순이익TTM)+신규`USE_SELF_ROE`(ROE=DART TTM 우선)로 완전TTM 7.4년 검증. **결론: annual ≈ TTM 동등(IC 0.030≈0.028, 차이는 3종목 노이즈 ±0.3~0.5)이나, 고정 운영config에서 annual이 일관 −0.2~0.25 우위 → annual 유지. production 무변경.** ⚠️ **초기(회사PC) "annual 3.59 > TTM 3.01 (−16%), G/M과 중복" 주장은 과대해석**: best-vs-best = **max-selection 편향**(가격파일만 바꿔도 TTM +0.61→+0.05 붕괴), 측정상 TTM이 오히려 더 직교(corr -0.069 vs annual -0.146). 진짜 비대칭은 **과열캡(시총/TTM순이익)이 annual에 +0.94 시너지·TTM엔 ~0**(TTM value와 중복). **두 플래그(+TTM_FUND_EQUAL/STORE_OVERHEAT_PEN) default off(재실험용).** 상세: `research/TTM_INVESTIGATION_2026_06.md`(끝장검증 종합·재현법)
  - **집PC 심층 재검증 (2026-06-15, 사용자 "버그 아니냐" 의심)**: 회사PC 결과를 독립 재확인 + 더 깊게. ①누적→분기 차분은 정상(dart_collector Q4=연간−Q3누적, 버그 아님) ②TTM이 균등합 아닌 **최근가중(1.6/1.2/0.8/0.4)** 발견 → `TTM_FUND_EQUAL=1` 플래그로 **진짜 균등TTM** 재생성해 재검증 ③과열캡 **on/off 둘 다** + 멀티팩터 풀그리드 + **진입/이탈/슬롯까지** 전부 재최적. **결과: 균등TTM 완전최적 3.07 < annual 3.79~3.87 (과열0.2). ★결정적: 균등TTM 최적이 V0Q20G70M10 = 옵티마이저가 밸류가중 0으로 버림 = TTM밸류 무용 확증**(annual은 V15 유지). 과열캡은 annual에 **+0.94**(3.79 vs 2.84) 기여 — TTM정보 이미 활용중. 버그2개 잡음(TurboSim `_overheat_w` __init__ precompute 후 설정 무효→생성자 param화 / 재생성 시 `STORE_OVERHEAT_PEN=1` 누락→overheat_pen 0). research: `backtest/_sp_ttm_final.py`·`_sp_ttm_battery.py`·`_sp_overheat_annual.py`, `_sp2`(가중TTM)·`_sp3`(균등TTM) 재생성본 보존
  - **★중대 정정 (2026-06-16 밤샘, 사용자 "납득 안 간다" 재의심)**: "TTM 기각"은 **과대해석**. 정확히는 **annual value ≈ TTM value (동등), 차이가 노이즈 안**. ①IC(노이즈없는 예측력) annual 0.030 ≈ TTM 0.028 동등 ②3종목 집중BT가 미세 데이터차(재생성 비결정성·growth_s 0.029)를 증폭→Calmar 슬롯3 +0.20/슬롯5 −0.42/슬롯10 −0.48/슬롯20 −0.12 **부호까지 뒤집힘=노이즈** ③회사PC −0.58도 노이즈범위 안. 내 설명 4개(G/M중복·예측력·outlier·과열중복) 측정상 다 깨짐. **실전: annual 유지(TTM 개선0), 단 TTM이 나쁜것도 아님(동등)**. fresh-orthogonal 밸류(평균회귀·잔차)도 노이즈 아래라 승자없음. ★교훈: **3종목 집중=미세 팩터비교 불가(노이즈±0.3~0.5), 작은 BT차이는 노이즈로 간주**. research: `backtest/_sp_clean_final2.py`·`_sp_ortho_value.py`, `_sp0b`(annual재생성)·`_sp2b`(TTM재생성) 같은배치
  - **★최종확정 (2026-06-16, 사용자 "제대로 최적화해 비교하라")**: 밸류 강제사용(V≥10)+멀티팩터×슬롯 최적화하니 TTM이 +0.61(WF 약세장도 +0.98~1.09)로 잠깐 우위 보였으나 — **`_sp_validate.py` 견고성검증서 가격파일만 바꿔도 +0.61→+0.05 붕괴**. ★**고정 운영config(V15Q0G55M30)에선 annual이 −0.2/−0.25 일관 승(가격파일 2개 모두)** = 회사PC(annual>TTM)와 일치. 즉 "TTM 우위"는 **max-selection 편향**(145 config 중 운좋은 best 골라 부풀림)이었음. 인접CV 0.234 들쭉날쭉, LOWO 노이즈. **결론: annual 유지 확정.** ★교훈: **팩터비교는 "각자 best끼리" 금지(편향) → 고정config + out-of-sample(다른 prices/기간) 검증**. 전체 인수인계: `research/TTM_INVESTIGATION_2026_06.md`. research: `_sp_proper_opt.py`·`_sp_wf_value.py`·`_sp_validate.py`
- **권리락 자동보정 (무상증자/분할/병합, 2026-06-12 배포)**: OHLCV의 corporate action 불연속(하루 수익률 <-33% 또는 >+45% = KR 가격제한 ±30% 초과 → 권리락 확정) 자동감지 → 이전 주가에 권리락 비율 누적 곱으로 스티칭. **`price_df` 생성 직후 적용**(point-in-time, 미래 권리락 미반영) → 모멘텀·mom_10·저변동성 전 가격팩터 일괄 정확화. 킬스위치 `CORPACTION_ADJ_DISABLE=1`. **계기**: 디바이스(4/28 무상증자 권리락 −46%)가 가짜 급락으로 12m 모멘텀 저평가(수익률↓+변동성↑ 이중), 재영솔루텍(4/30 병합 +484%)이 과대평가. **검증(6/10 boost OFF/ON)**: 디바이스 cr 4→3, 재영솔루텍 랭킹이탈, 비츠로셀 76→40, **매수 top3(제주·SK·디바이스) 불변·종목수 111/111 무에러**. 다음 16:00 run부터 자동적용(state 점진 갱신, wr 3일창 2일 전환). research: `backtest/_corpaction_*.py`. 구현: `fast_generate_rankings_v2.py` `_backadjust_corpaction`

## DART + FnGuide 데이터 수집
- 재무제표: DART + FnGuide 보충 (누락 계정 자동 합침). PER/PBR/ROE는 pykrx (KRX 공식)
- **DART 갱신 list API** (refresh_dart_cache.py): `OpenDartReader.list(kind='A')`로 최근 N일 정기공시 종목만 fetch (전종목 시도 → timeout 사고 방지). 정정공시 보강: mtime < rcept_dt면 재수집
- **옵션 F — 항목별 mismatch 자동 정정** (fast_generate_rankings_v2.py `fix_dart_account_mismatch`): 매출/자산/자본 ratio 0.5~2.0 외, 영업이익/순이익/CF |ratio| 0.2~5.0 + 부호 위반 → 해당 row만 제거 → FnGuide로 자동 보충. preload_data에서 fs_dart 로드 직후 호출 (벡터화 1회). 모니터링: `monitor_dart_fn_health.py` (row > 4000 or 종목 > 1500 → 종료코드 1)
- **document API 폴백 (Phase B)** (dart_collector `_fetch_quarter_via_document`): finstate_all empty 시 XBRL document API로 자동 폴백 (year ≥ current-1). 분기마감일(3/31,5/15,8/14,11/14) finstate_all 누락(5/15 1Q 37%) 자동 보강. PIT 유지 (rcept_dt = rcept_no 앞 8자리). fs_div='DOC' 추적
- **FnGuide PIT 보강** (postprocess_fnguide_rcept.py): FnGuide에 rcept_dt 필드 없음 → DART rcept_dt 역추적 이식. 미매칭 시 연간 +90일/분기 +45일 (법정 기한). 증분: refresh_fnguide_incremental.py (DAYS cutoff 30일 + mtime 비교, ThreadPool=2, 종목당 30초 timeout)
- **매핑 추가 시 검증 절차**: DART/FnGuide 매핑 추가/변경 시 회계 항목 의미 정확히 검증 (특히 비용 vs 수익). ranking에서 대형주가 갑자기 빠지면 첫 의심 = fs_dart 정합성 (영업이익률 > 80% 'y' 매출 row 검사). 과거 SG&A→매출 오매핑 사고(2026-05-04, SK하이닉스 이탈)로 도입 — 상세 CHANGELOG
- Growth 계산: 계정별 날짜 사용 (0 채우기 금지)

---

# 순위 체계 — 모든 판단은 weighted_rank(wr) 기준
- composite_rank(cr): 당일 단독 순위. **판단 기준으로 절대 안 씀.** wr 계산 입력값 + 궤적 표시용.
- weighted_rank(wr): cr_t0×0.4 + cr_t1×0.35 + cr_t2×0.25. **모든 판단의 유일한 기준.**
- Top 20: wr 상위 20개 (rank ≤ 20)
- 진입: ✅ 종목 중 wr 상위 entry_rank개 / 퇴출: wr 값 > exit_rank
- postprocessing 후 rank = wr 기준 순위. composite_rank로 판단하면 버그.
- wr PENALTY: T-1/T-2 cr 매핑 시 Top 20 한정 → 밖이면 PENALTY 50 (BT와 production 동일 룰)

## 표시 체계 (v80.1) — 궤적(cr-rank) + 점수(wr 선형)
- **매매 로직**: 순위 기반 wr 유지 (BT: 순위 Cal 3.39 > 점수 2.62, v79 재검증)
- **궤적 표시**: `r2→r1→r0위` 각 날짜의 **당일 cr-rank** (cr = 당일 순수 실력, wr보다 직관적)
- **동점 tie-breaker**: wr 같으면 `(wr, cr)` — cr 작은 쪽(오늘 더 강한 종목) 우선. 파일 생성/Top 20/진입 picks 전부 튜플 정렬
- **✅/⏳/🆕 상태**: cr Top 30 기준 (verify_n=30, 미국 시스템 정합). T-1/T-2 각각 cr Top 30이었는지. ✅=3일 연속, ⏳=2일, 🆕=1일(오늘만)
- **역할 분리**: 궤적+상태 = cr(일별 강도), 점수 = wr(3일 종합), 매매 = wr(진입/퇴출)
- **점수 공식**: `score_100 = max(5, 100 - (wr - min_wr) × 5)` (Signal/Watchlist 공통). 1위=100, wr 1 증가 = 5점 감소 (선형, 하한 5점). wr 차이가 그대로 점수 차이로 반영
- 🆕/⏳ 검증 안 된 날 r1/r2 = '-' 표시

## 메시지
- Signal: 국면 표시 (방어/공격), 전환 시 별도 안내 메시지 먼저 전송. 시스템 수익률 → 매수 후보 → 선정 과정 → 종목 근거
- **국면 전환 조기경보 (v80.28, 2026-06-14, 표시 전용)**: Signal footer에 `build_regime_alert_lines()` — `regime_state.json`의 `streak_mode != mode`면 전환 진행 중 → "⚠️ 방어 전환 경보 MA20<MA80 N일째 (확인 5일 중), N일 더 지속 시 현금" / "📈 공격 전환 대기" 카운트다운. **매매룰(5일 확인)은 불변, 1일째부터 표시만** (사용자: 5일째 알면 대비 못함). 전환 진행 없으면(streak_mode==mode) 미표시. 다음 16:00부터. 롤백: footer `lines.extend(build_regime_alert_lines())` 제거.
- 매도 기준선만 표시 (매수 기준선 제거). 매도 OR 조건: ① 매도 기준선 이탈 / ② -10% 시 / ③ 고점대비 -8% 시
- **분할매수는 알파 아님 (2026-06-14 full-config BT)**: 한번에 Cal 3.935/CAGR 102 vs 분할(50%+다음날) 3.885/100.7, **MDD 동일 25.9 = 리스크도 안 줄임**, within noise. 신규진입 다음날 평균 +0.20%(모멘텀)라 분할 시 더 비싸게 삼. **강세 재진입은 한 번에 전량이 기본**(버퍼 제외). 분할은 약세·변동장만 미세 유리(2022-23 +0.25)·강세장 불리(2019-21 −0.18) → **체결/심리 안정용 선택일 뿐 수익장치 아님**. research: `backtest/_split_entry_test.py`. '시스템은 신호만, 매매는 본인 판단' 명시
- 순위 이탈 → Watchlist에만 표시
- defense 시 cash 모드 안내. 날짜: 당일 기준 (d <= today_str)
- 이격도20 안전망 (정보): 매수 후보는 그대로, Watchlist 표시. (※ 과거 매수 차단 룰은 검증 후 정보성으로 완화 — CHANGELOG)
- **채널 전송 금지**: 명시적 지시 없으면 무조건 TEST_MODE=1

## 시장 위험 지표
- RETURN_MATRIX: 코스피 기반. 신호등 🟢≥8% / 🟡<8% / 🔴<5%+extreme. VIX 비중 조절 안 함
- NAV 디스카운트 (산업지주사): 별도 트랙, **매매 신호 X 정보만** (nav_discount_module.py, Watchlist 끝). SK스퀘어 ~44% 등

---

# 스케줄러
- 일일 파이프라인: 평일(월~금) **16:00** (장 마감 후, 휴장일 자동 스킵, run_daily.py)
- 종목명 캐시: 매주 일요일 10:00 (refresh_ticker_names.py)
- **EPS×볼륨 융합 데이터 축적: QuanT_EPS_Fusion_Daily 평일 17:30** (research/eps_fusion_daily.py = FnGuide 컨센서스 스냅샷 + 융합 추적기). **연구용 데이터 축적만, 매매 무관.**
- DART/FnGuide subprocess timeout: 5시간 (분기마감일 폭주 대비), FnGuide 종목당 30초 (hang 보호)
- 스케줄러 변경 시 구 스케줄러 `schtasks //Query`로 확인 후 삭제

## EPS×볼륨 융합 연구 (2026-06-13, 연구단계 — 매매 미적용)
> 결론: **signal-fusion 부적합**(두 시스템 다른 유니버스 — 볼륨=무커버 소부장 소형/EPS=커버 대형, 교집합 1종목). factor-fusion은 가중치 검증불가. **답=포트폴리오 분리 sleeve**(섞지 말고 볼륨 주력 + EPS 별도 관찰). EPS는 BT0 미검증 → 실자본 전. FnGuide 커버리지 yfinance 2배(애널수 버그수정 `fnguide_crawler.get_consensus_data`). 일별 자동축적 중(60~90일 후 EPS sleeve 검증). 상세: `research/eps_volume_fusion_findings.md`.

# 백테스트 도구
- TurboSimulator: 5ms/run (56x 가속), turbo_simulator.py
- fast_generate_rankings_v2.py: DART+FnGuide 합침, per-account dates
- grid_search_final.py: 3워커 병렬, Calmar 기준, 안정성 필터. ProcessPoolExecutor 기반 Windows 호환 병렬
- 측정 기준: **7.4년 단일 (2019-01-02 ~)** — 2018 H2 DART 데이터 부족으로 제외
- bt 파일의 score/rank는 무효 — z-score만 유효 (TurboSim이 재계산). 필터 효과 검증은 FG 재생성 기준 (TurboSim 필터링은 z-score 불변이라 낙관적)
- BT noise ±0.10 (Cal). 변경 채택 기준: noise 초과 + WF 안정성 + 인접 안정성 CV < 0.10~0.30 + 약세장 사고 패턴 없음
