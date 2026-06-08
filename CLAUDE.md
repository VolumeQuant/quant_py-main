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

# 🇺🇸 US 전략 — eps-momentum-us (v114 MA12 추세홀드 + 점수 고정스케일, master 배포됨, 2026-06-05)

> **배포 완료 (2026-06-05, commit b2ed205)**: v111 MA12 추세홀드 + v112 점수 고정스케일 + v114(보유표시 제거·EPS꺾임 매도 유지·고객 문구 정리·궤적 일별 라벨) master 병합. 다음 cron부터 적용. 롤백: v86e++(PEG 메가홀드)로 git revert.

> 경로: `C:\dev\claude code\eps-momentum-us`

- **v114 보유 표시 제거 (2026-06-04, master 배포됨)**: **추세 보유(MU/SNDK) 메시지 표시 제거 — v110 지시 복원**. v111에서 다시 넣었던 🌟 추세 보유 박스 제거(신규 진입자 "지나간 종목 약올림"). 보유 로직(perf/replay)은 그대로, 메시지엔 매수 후보만. footer "매도: 순위 이탈 또는 실적 꺾임 / 상승추세(>MA12)면 보유". **EPS꺾임 매도 제거(Alt-A)는 검토 후 기각**: BT상 현행과 +0.0p 동일(75일 상승장에선 미발동)이나, min_seg<-2 매도는 **v55(2026-03-13)~ 핵심 퇴출 규칙**이고 v86 문서상 "사이클천장 디레이팅 시 유일보호"로 명시됨 → 무비용≠무가치(상승장이라 보험금 탈 일이 없었을 뿐). 사용자 결정으로 **EPS꺾임 매도 유지/복원**. research: `research/auto_bt_eps_override.py`(altA=현행 동일 +0.0p, altB 순수MA12 -42.2p 기각).

- **v112 점수 표시 고정 스케일 (2026-06-04, master 배포됨)**: 표시점수 `ws/그날최댓값×100` → **고정 앵커 `(ws-30)/70×100` clip 0~100**. 문제: 분모가 "그날 1등"이라 같은 종목도 그날 누가 1등이냐에 따라 출렁(EDA: 일별 최댓값 15일간 83~112 변동 std7.7, +1.2σ 종목이 74~100점 왔다갔다 = "어제 95점이 왜 오늘 100점"). 해결: ws30(하한/missing)→0, ws100(+2.3σ)→100. **날짜 안정**(같은 펀더멘털=같은 점수) + **강도 보존**(괴물주 MU급→100, 밋밋한 날 1등→72). 검증 KEYS72.3/ITT54.4/중앙값31.5. **매매·DB 영향 0**(순수 표시, 매매는 ws 순위 불변), `score_display_map` 한 곳 변경→Signal·Watchlist 자동반영. 사용자 승인(B안, AskUserQuestion 4안 비교).

- **v111 MA12 추세홀드 (2026-06-04, master 배포됨)**: "일찍 안 팔기" — 보유 종목이 **가격 > 12일 이동평균(MA12, 상승추세)**이면 part2_rank>10이어도 보유, **추세 깨지면(가격<MA12) 또는 EPS 꺾임(min_seg<-2)** 매도. **PEG 메가홀드(v86~v110) 전면 교체**. 계기: 시스템이 winner를 순위>10 조기매도 → MU(+156%)/SNDK(+191%)/STX(+118%) 이탈 후 상승 놓침. PEG홀드는 규칙 2개+고객설득력 약함("47위 SNDK 사라고?"), MA12는 규칙 1개+직관적. **검증(paired 100×3+LOWO+walk-forward+인접안정성)**: baseline 대비 +33p(100/100), MA10~15 plateau(MA12=중심), WF 5/5 블록 양수, **LOWO(-MU-SNDK-STX) +2.1p(broad, 단일종목 착시 아님)**, STX(비메가 winner) 포착(PEG홀드 못잡던 것). 재점검 확정 config: 슬롯2/진입 part2≤3/이탈 rank>10/**50-50**. **BT==production 정합**: `_replay_holdings`=perf-sim holdings={MU,SNDK}, sys_cum +204.6% vs SPY +10.4%(74일). **변경**: `_replay_holdings`/`_get_system_performance`/`select_display_top5`/`classify_exit_reasons` 모두 MA12로 통일(단일규칙), `_above_ma12()` 헬퍼(데이터<6 carryover True), mega_score진입/composite게이트 제거→part2 Top 진입, 메시지 PEG/메가→"추세 보유" 언어. dead: `check_mega_hold`/`calc_mega_score`(호출처 0). ⚠️ 75일 in-sample 단일 bull regime, 약세장은 국면 오버레이(S&P 200DMA+VIX→채권)가 portfolio레벨 처리, EPS trend 과거데이터 없어 약세장 BT 불가. **롤백**: v86e++(PEG 메가홀드)로 git revert. research: `research/auto_bt_hold_winners.py`/`auto_bt_ma10_validate.py`/`auto_bt_ma12_reexam.py`/`auto_bt_strategy_compare.py`

- **v86e++ 데이터 정합성·신뢰성·UX 수정 (2026-06-03, v111로 대체됨)**: ① **carryover 버그**: 메가홀드 carryover가 `_get_prev_portfolio`(동결 portfolio_log, log_portfolio_trades 미호출로 2026-03-05 멈춤)를 읽어 라이브 메가홀드가 한번도 작동 안 했음(perf-sim만 동작). `select_display_top5(today_str)` 파라미터 추가 + **`_replay_holdings`(성능sim 동일 forward replay)로 보유 재구성** → BT==production 입증({KEYS,SNDK} 완전일치). ② **수집 건강성 가드(KR <150 이식)**: `_validate_collection_health`(수집<900 OR 에러율>30%) → 미달 시 30분 후 재수집→그래도 미달이면 랭킹 미기록+채널 차단(개인봇 알림). 2026-05-28~29 yfinance 대량실패(에러53%, 수집600/315 vs 정상1240)인데 가드 없어 망가진 신호 발송된 사고 재발 방지. ③ **핵심성장주 표시(고객 친화)**: "메가/PEG<0.22" 전문용어 전면 제거 → **"🌟핵심 성장주(성장 대비 저평가)"**. 매수후보 점수순 정렬(고확신 먼저). **메가 표시는 현재가치 기준**(PEG<0.22+성장≥25%+EPS안꺾임+최근상위권) — 보유이력 무관 → SNDK·MU 같은 메가는 같게 표시(데이터갭으로 보유끊긴 MU 부당누락 모순 해소). 저평가-조건부 보유임을 명시("저평가 해소되거나 실적 꺾이면 매도" — 무작정 홀드 아님). research: `research/auto_bt_unranked_mega.py`(옵션B 순위무관홀드 = MU 단일착시 +3.6p, 기각)

- **메가홀드 오버라이드 (v86, 브랜치 `v86-mega-hold` — master 미병합, 집PC 메시지확인 후 병합)**: 보유 종목이 메가 시그니처(**NTM EPS 추정치 상향 ntm_current/ntm_90d-1 ≥60% AND PEG<0.2**) 유지 시 part2_rank>10이어도 홀드(매도 스킵). min_seg<-2(EPS꺾임) 매도는 유지=펀더멘털 기반 홀드. 계기: MU(NTM+139%/PEG0.06)·SNDK(+147%/0.04)가 초저평가+EPS폭발 유지인데 fwd_pe_chg 식어 순위밀려 회전매도→큰상승 놓침(사용자 "MU 많이 놓침"). **구현(정석, hold_entries)**: `select_display_top5`에서 어제보유(portfolio_log) 메가를 selected에 우선 캐리오버→슬롯점유→신규는 남은슬롯만→성능/슬롯/이탈 자동정합. 메가홀드 포함 시 50/50 균등(저순위 메가가 2step gap으로 0% 되는 것 방지). `check_mega_hold`/`get_mega_hold_tickers` + watchlist 🔒섹션. **BT 100×3**: +81.5p(100/100), Calmar 8.9→10.3, 부분기간(전반+최근) 둘다 100/100(슬롯3 죽인 테스트 통과), LOWO 무해(MU/SNDK제외 시 0 음수아님), 인접성 평탄. 트레일링스탑은 휘프소로 edge파괴(-28p)→가격스탑 없음. **재최적화(메가홀드 ON에서 slots×exit 그리드)**: slot3 실패(-21p), exit12 +6p지만 LOWO -14/-15(MU/SNDK착시) → **v84 파라미터(슬롯2/진입≤3/이탈>10)가 메가홀드 버전에서도 최적, 추가변경 전부 과적합.** ⚠️ N=2 상승장 in-sample, 사이클천장 디레이팅 시 min_seg가 유일보호. 랭킹불변→DB재계산 불필요. research: `research/auto_bt_mega_hold*.py`, `auto_mega_signature.py`, `auto_reoptimize_mega.py`

- **비성장 소비/미디어 업종 제외 (v85, 2026-06-02)**: `OFF_STRATEGY_INDUSTRIES = {엔터, 전문소매}` 블록리스트 (daily_runner.py, COMMODITY_INDUSTRIES와 동일 메커니즘 — eligible 필터 단계서 제거). 계기: WMG(음반, 6/1 첫 진입) 같은 catalyst형 소비재가 "압도적 성장기업만" 사용자 목적에 안 맞음. **숫자 필터 전부 실패 확인**: rev_growth≥25%(FORM 14%/TTMI 19% winner도 차단), PEG/fwd_PE(MU/SNDK 제외 시 -25~-67p 착시), MA20 가격모멘텀(MU/SNDK 착시), revision 집중도(WMG 77% < FORM 88% 분리불가). **WMG와 진짜 winner FORM이 숫자상 거의 동일** → 유일한 robust 분리축 = 업종(반도체 vs 음반사). BT: 300회 paired에서 winning trade 0개 차단, lift +0.00p (비용 0, WMG/FIVE만 제거). 본질은 통계 edge가 아니라 **가치판단**(원자재 제외와 동일 성격). ⚠️ 미래 폭발성장 미디어/소매 나와도 차단됨 (사용자 선호 명시적). 다음 GA 실행부터 적용. 롤백: 상수+필터 4줄 제거. research: `research/auto_bt_sector_exclude.py`, `auto_bt_value_growth.py`, `auto_diag_eda.py`

- **국면 오버레이 (v84, 2026-05-27)**: S&P 500 < 200일선(15일 확인) OR VIX > 36(2일 확인) → **defense(방어)**. defense 시 주식 매수 중단 + 채권ETF(**IEF 기본 / BIL 안전**) 권장, 200일선 회복(15일) 시 자동 재개. KR v80.16(defense=현금) 참고. **26년(2000~) 시장데이터 EDA(QQQ 프록시)**: 4대 약세장 포착(dotcom 92/GFC 90/COVID 71(VIX)/2022 77%), MDD -83%→-29%(IEF), Cal 0.11→0.50. 인버스ETF는 탈락(52% 오발일+감쇠, Cal 0.20~0.25). 확인 15일 = 2026-04 얕은 dip 휘프소(-105%p) 거르며 진짜 약세장만 포착(버퍼/데드크로스보다 우월, 깊이 아닌 지속기간 판별). **현재 regime=boost → 배포 즉시 영향 0, 미래 약세장에만 발동.** ⚠️ 신호는 26년 검증, 전략 이득은 프록시 추정(약세장 종목데이터 없음). 구현: `get_market_regime`/`_detect_regime_transition`(regime_state.json)/`_get_system_performance` defense 시 IEF 반영. 킬스위치 `REGIME_OVERLAY_DISABLE=1`, 테스트 `REGIME_FORCE`. research: `research/regime_eda_*.py`

- EPS Revision Momentum, conviction z-score 기반, **2슬롯 + dynamic weight (2step_t15) + dd_30_25 진입필터** (v84)
- conviction: adj_gap × (1 + max(up30/N, min(|eps_chg|/100, 3)) + min(min(rg,0.5)×0.6, 0.3))  ← v80.9 X2: cap 3.0, rev_bonus smooth
- adj_gap = fwd_pe_chg × (1 + dir_factor) × eps_quality
- **fwd_pe_chg 가중치 (v80.10)**: **7d 0.30 / 30d 0.10 / 60d 0.10 / 90d 0.50** (90일 누적 PE 압축 강조, long-tail)
- 점수: 일별 z-score(**하한30, 상한 무제한**) → 3일 가중(T0×0.5+T1×0.3+T2×0.2), 빈 날=30점
- **v79**: z-score 상한 100 clamp 제거 → outlier 변별력 보존
- **Case 1 보너스 폐기 (v80.5)**: cr/score_100/part2_rank 정렬 일관성 회복 위해 제거
- 진입: 3일 가중 Top **2** + ✅(3일 검증) + min_seg ≥ 0%, 슬롯 **2** (v82: 3→2)
- **비중 (v84, 2026-05-30)**: **2step_t15 dynamic** — 1·2위 score gap ≥ 15 → 1위 100%/2위 0%, gap < 15 → 50:50. v83.3 (90/10) 폐기 이유: 채택 BT가 매일 rebalance simulator(production entry_fixed 불일치)로 +21.45%p 부풀려진 결과였음. entry_fixed 재BT 시 +1.38%p 불과. v84 BT 검증 (entry_fixed 100x3 paired): incl +5.63%p (98/100), excl(MU+SNDK 제외) +17.27%p (99/100), 평균 +11.45%p robust 우월. **메타 자산 배분 80:20 (시스템:BIL) 사용자 영역 별도** — 시스템은 "투자금" = 80% 부분에서만 운영, 본인이 매년 1월 1회 80:20 리밸런싱 (project_cash_buffer_rule)
- **진입 필터 (v84, 2026-05-30)**: **dd_30_25** — 30거래일 high 대비 -25%+ drawdown 종목 매수 후보 제외. 단기 폭락 종목 자동 차단. DB high30 컬럼 추가 (113,746 entries). BT lift: incl +8.73%p (94/100), excl +7.16%p (77/100)
- **비중 이력**: v82 70/30 → v83 80/20 → v83.3 90/10 (폐기, simulator 결함) → **v84 dynamic (2step_t15)**. 슬롯 idx 기반 배정 (진입 시 cash로 매수, 매도 시 cash 환원)
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
- 시장 공포 기반 비중 조절 안 함 (portfolio_mode normal 하드코딩 — 알파가 공포 구간에서 발생). 종목간 dynamic weight는 별개
- 상관관계: 🔗 유사도% + BFS 그룹핑 + 택1/택1~2 권장
- **leave-one-superwinner-out 교훈 (v83.2)**: 71일 단일 표본 + 2슬롯 80/20에서 boost/집중 메커니즘은 MU/SNDK 한 종목만 빼도 edge가 무너짐(동전던지기 or 음수) = single-stock 착시. **boost·집중 평가 시 반드시 dominant winner 제외 robustness 확인.**
- **롤백 트리거 (v84)**: 5거래일 SPY 대비 알파 -5%p / MDD -10% 초과. v84 롤백 시 `daily_runner.py`의 dd_30_25 필터 + 2step_t15 dynamic weight 로직 환원 (v83.2 기준 80/20 정적) + git revert. 단 v83.3 자체가 simulator 결함 결과였으므로 v83.2 (80/20)로 환원이 안전 기준

---

# 🇰🇷 KR 전략 — quant_py-main (v80.24 이탈 X4→X6, 2026-06-08)

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
- **메타 자산 배분 (사용자 영역, 2026-05-28)**: 투자금의 **70% 시스템 + 30% 현금성**(MMF/RP/CMA/예수금). 매년 1월 첫 거래일에 70:30으로 1회 리밸런싱 (±5%p 이상 이탈 시). 시스템 코드와 무관, 본인 메타 영역. US는 80:20, KR이 더 보수적인 이유 = KR 약세장 깊이 + 트라우마 대응. 상세: `~/.claude/projects/C--dev/memory/project_cash_buffer_rule_kr.md`

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
