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

# 🇺🇸 US 전략 — eps-momentum-us (v84, 2026-05-27)

> 경로: `C:\dev\claude code\eps-momentum-us`

- **국면 오버레이 (v84, 2026-05-27)**: S&P 500 < 200일선(15일 확인) OR VIX > 36(2일 확인) → **defense(방어)**. defense 시 주식 매수 중단 + 채권ETF(**IEF 기본 / BIL 안전**) 권장, 200일선 회복(15일) 시 자동 재개. KR v80.16(defense=현금) 참고. **26년(2000~) 시장데이터 EDA(QQQ 프록시)**: 4대 약세장 포착(dotcom 92/GFC 90/COVID 71(VIX)/2022 77%), MDD -83%→-29%(IEF), Cal 0.11→0.50. 인버스ETF는 탈락(52% 오발일+감쇠, Cal 0.20~0.25). 확인 15일 = 2026-04 얕은 dip 휘프소(-105%p) 거르며 진짜 약세장만 포착(버퍼/데드크로스보다 우월, 깊이 아닌 지속기간 판별). **현재 regime=boost → 배포 즉시 영향 0, 미래 약세장에만 발동.** ⚠️ 신호는 26년 검증, 전략 이득은 프록시 추정(약세장 종목데이터 없음). 구현: `get_market_regime`/`_detect_regime_transition`(regime_state.json)/`_get_system_performance` defense 시 IEF 반영. 킬스위치 `REGIME_OVERLAY_DISABLE=1`, 테스트 `REGIME_FORCE`. research: `research/regime_eda_*.py`

- EPS Revision Momentum, conviction z-score 기반, **2슬롯 80/20 집중** (v83: 균등 3슬롯 → 80/20)
- conviction: adj_gap × (1 + max(up30/N, min(|eps_chg|/100, 3)) + min(min(rg,0.5)×0.6, 0.3))  ← v80.9 X2: cap 3.0, rev_bonus smooth
- adj_gap = fwd_pe_chg × (1 + dir_factor) × eps_quality
- **fwd_pe_chg 가중치 (v80.10)**: **7d 0.30 / 30d 0.10 / 60d 0.10 / 90d 0.50** (90일 누적 PE 압축 강조, long-tail)
- 점수: 일별 z-score(**하한30, 상한 무제한**) → 3일 가중(T0×0.5+T1×0.3+T2×0.2), 빈 날=30점
- **v79**: z-score 상한 100 clamp 제거 → outlier 변별력 보존
- **Case 1 보너스 폐기 (v80.5)**: cr/score_100/part2_rank 정렬 일관성 회복 위해 제거
- 진입: 3일 가중 Top **2** + ✅(3일 검증) + min_seg ≥ 0%, 슬롯 **2** (v82: 3→2)
- **비중 (v83)**: **1위 80% / 2위 20%** (v82 70/30 정정). 슬롯 idx 아닌 점수 순서 기반 배정
- **C2 boost 제거 (v83.2, 2026-05-27)**: v83 C2 rank+3 boost를 완전 제거. `_apply_c2_boost_rerank`/`_is_c2_for_v83` 헬퍼 + 호출 3곳 삭제. part2_rank = 순수 w_gap 순위로 복귀 (DB 71일 재마이그레이션, `research/apply_no_boost.py`). **이유**: leave-one-superwinner-out 검증서 C2 boost edge가 전부 MU 한 종목 — MU 제외 시 gate vs no_boost 동전던지기(239/500), M24 음수. binary는 no_boost보다 -8.64%p로 더 나빴음. C1 boost(과거 미적용)도 SNDK 제외 시 -4.68%p(186/500) = 동일 single-stock 착시. **부수 효과**: BWXT(약한 EPS+dip)가 FIX보다 높게 표시되던 점수 왜곡 + 궤적(cr, boost無) vs 픽(p2, boost有) 불일치 동시 해소
- **퇴출 (v80.10b)**: part2_rank > **10** OR min_seg < -2%  ← 8→10 변경 (회전 정책 재최적화)
- **품질 필터 (v79.1)**: FCF < 0 AND ROE < 0 동시 → eligible 제외
- **rev_up30 ≥ 3 필터 (v80.8)**: 단일 분석가 의존 종목 차단 (WELL 사례)
- **Signal 진입 (v80.2)**: ✅ but min_seg<0/하향과반/저커버리지 탈락 시 다음 ✅ 후보로 슬라이드
- **⏸️ 매도 유예 제거 (v80.10c)**: v80.10 장기 가중치 전환으로 ⏸️ 알파(단기 가중 노이즈 완충재) 소멸. BT N=0이 모든 N>0보다 paired 100/100 우월. `check_breakout_hold` 함수는 유지(약세장 재토글용)
- **v81 롤백**: MA120→MA20 단기 모멘텀 필터 시도 → bt_breakout_hold simulator의 pool-exit price masking 버그 발견 후 롤백 (MA120 유지)
- **HISTORICAL MODE (v83.1)**: yfinance eps_trend `7daysAgo/30d/60d/90daysAgo`가 호출 시점 기준 → MARKET_DATE 과거 재실행 시 window(사용자 날짜)와 EPS 값(yf 시점) misalign → adj_gap drift. `is_historical_mode()` 감지 시 fetch SKIP + DB part2_rank 그대로 사용(write 0). **production cron 영향 없음** (매일 새 날짜 = real_today 정합), test workflow + 과거 날짜만 영향
- composite_rank=당일 conviction 순위(추이 표시), part2_rank=3일 가중 순위(매매)
- RETURN_MATRIX: S&P500 기반 (26년 6,593일), VIX는 yfinance 최신 보완
- 시장 공포 기반 비중 조절 안 함 (portfolio_mode normal 하드코딩 — 알파가 공포 구간에서 발생). 종목간 80/20은 별개
- 상관관계: 🔗 유사도% + BFS 그룹핑 + 택1/택1~2 권장
- **leave-one-superwinner-out 교훈 (v83.2)**: 71일 단일 표본 + 2슬롯 80/20에서 boost/집중 메커니즘은 MU/SNDK 한 종목만 빼도 edge가 무너짐(동전던지기 or 음수) = single-stock 착시. **boost·집중 평가 시 반드시 dominant winner 제외 robustness 확인.**
- **롤백 트리거 (v83.2)**: 5거래일 SPY 대비 알파 -5%p / MDD -10% 초과. backup: `eps_momentum_data.db.bak_pre_c2gate_20260527`. 롤백: backup 복원 + `git revert`

---

# 🇰🇷 KR 전략 — quant_py-main (v80.21, 2026-05-28)

> 코드 진실: `regime_indicator.py` `get_regime_params()`. 아래는 그 코드 기준 현재 production 파라미터. 변경 이력은 CHANGELOG.md.

## 현재 운영 파라미터 종합 (v80.21 기준, 코드 검증됨)

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
| 진입/퇴출/슬롯 | rank ≤ **3** / rank > **4** / **3슬롯** (E3X4S3) |
| 손절 / 트레일링 | **−10% / 없음(v80.21 TS 제거)**. TS 쿨다운 키는 잔존(무효) |
| QoQ 패널티 (D6, v80.12) | 강한 boost(KOSPI > MA220 × 1.06)에서 영업이익 QoQ < +20% → G × 0.7 |
| 계절성 패널티 | curr 식 (Q2+Q4)/(Q1+Q3) > 1.4 → G × 0.3, 단 min/max(4Q) > 0.2 면제 (v80.7/9/10) |

### 방어 모드 (defense) — KOSPI MA20 < MA80
- **cash 100%** (`ENTRY_RANK=0`, v80.16) — 신규 매수 안 함, 보유 종목만 룰대로 청산
- 참고 파라미터(청산 기준): V35 Q15 G15 M35, G 2팩터 rev/oca 0.8/0.2, 6m-1m, EXIT rank > 8, 슬롯 5, SL −10% (v80.21: TS 제거 — defense는 cash라 원래 무효)

### 공통
- **wr 가중치 (v80.13)**: T-0 × 0.4 + T-1 × 0.35 + T-2 × 0.25 (당일 비중 ↓, 3일 검증 강화)
- **순위 기반** (점수 기반 아님 — KR 시장 종목수 ~1900, score 표준편차 노이즈 커서 순위가 명확 우월. 재검증 거부)

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
- 매도 기준선만 표시 (매수 기준선 제거). 매도 OR 조건: ① 매도 기준선 이탈 / ② -10% 시 / ③ 고점대비 -8% 시
- 분할매수 권장: '1차 50% + 다음날 추가'. '시스템은 신호만, 매매는 본인 판단' 명시
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
- DART/FnGuide subprocess timeout: 5시간 (분기마감일 폭주 대비), FnGuide 종목당 30초 (hang 보호)
- 스케줄러 변경 시 구 스케줄러 `schtasks //Query`로 확인 후 삭제

# 백테스트 도구
- TurboSimulator: 5ms/run (56x 가속), turbo_simulator.py
- fast_generate_rankings_v2.py: DART+FnGuide 합침, per-account dates
- grid_search_final.py: 3워커 병렬, Calmar 기준, 안정성 필터. ProcessPoolExecutor 기반 Windows 호환 병렬
- 측정 기준: **7.4년 단일 (2019-01-02 ~)** — 2018 H2 DART 데이터 부족으로 제외
- bt 파일의 score/rank는 무효 — z-score만 유효 (TurboSim이 재계산). 필터 효과 검증은 FG 재생성 기준 (TurboSim 필터링은 z-score 불변이라 낙관적)
- BT noise ±0.10 (Cal). 변경 채택 기준: noise 초과 + WF 안정성 + 인접 안정성 CV < 0.10~0.30 + 약세장 사고 패턴 없음
