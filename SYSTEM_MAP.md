# SYSTEM_MAP — KR 퀀트 시스템 전수 지도

**목적**: 전략 변경 시 맹점 제로 보장용 영구 문서. 다음 교체(v80 등)에도 재사용.
**작성**: 2026-04-15, v77.1 → v79 전환 준비 중
**검증 원칙**: 모든 전략 변경은 본 문서의 체크리스트를 통과해야만 커밋 가능

---

## 1. 데이터 플로우 (파이프라인)

```
[KRX/pykrx/DART/yfinance]
    ↓ data_refresher.refresh_all(base_date)
[data_cache/*.parquet]
    ↓ run_daily.py → subprocess.Popen (2병렬)
[fast_generate_rankings_v2.py]  (V/Q/G/M + G_SUB + MOM 환경변수 수신)
    ├→ boost: --state-dir=state/
    └→ defense: --state-dir=state/defense/
    ↓ (d)+(d')+(e) 필터 적용 후 z-score 계산
[state/ranking_{date}.json], [state/defense/ranking_{date}.json]
    ↓ run_daily._postprocess_ranking (activemode 파일만)
    ├ + weighted_rank (T0×0.5 + T1×0.3 + T2×0.2)
    ├ + per/pbr/roe (pykrx 캐시에서)
    └ + mode (active regime)
    ↓ send_telegram_auto.py
    ├ calc_system_returns() — 과거 전체 순회, 날짜별 regime 판단
    ├ load_ranking_for_regime() — 국면별 파일 선택
    └ create_*_message() — Signal/Watchlist/전환 메시지
    ↓ TEST_MODE=1 → 개인봇  |  미설정 → 채널
```

---

## 2. 파일별 역할 + 하드코딩 위치

### 2.1 `C:\dev\regime_indicator.py` — 국면 판단 + 전략 파라미터 진본
**역할**: boost/defense/cash 국면 판단 + V/Q/G/M/G_SUB/mom/E/X/S 모든 파라미터 정의
**하드코딩**:
| line | 항목 | v77.1 값 | v79 변경 |
|---|---|---|---|
| 64 | `CRASH_RET20_THRESHOLD` | -0.20 | **삭제** (Crash 제거) |
| 65 | `CONFIRM_DAYS` | 5 | **7** |
| 68-82 | `check_crash_cash()` 함수 | — | **삭제** |
| 118-128 | crash_active 로직 | — | **삭제** |
| 131-134 | final_mode `cash` 분기 | — | **삭제** (또는 항상 underlying_mode 반환) |
| 175-189 | cash params dict | all zero | **삭제** (또는 유지하되 호출 제거) |
| 190-206 | boost params | V5/Q0/G65/M30, 3f(rev+oca+gp, 0.5/0.3/0.2), 12m-1m, E7X8S3 | **V15/Q5/G50/M30, 3f(rev+oca+gp, 0.5/0.3/0.2), 12m, E3X6S3** |
| 207-223 | defense params | V30/Q5/G10/M55, 2f(rev_accel+op_margin, 0.5), 6m-1m, E3X6S7 | **V30/Q15/G15/M40, 2f(rev+oca, 0.7), 6m-1m, E3X6S7** |
**의존**: state/regime_state.json R/W
**호출처**: run_daily.py, send_telegram_auto.py (get_regime_params, get_current_regime)

### 2.2 `C:\dev\run_daily.py` — 파이프라인 오케스트레이션
**역할**: 일일 실행 드라이버. data_refresh → regime → FG dual → postprocess → telegram
**하드코딩**:
| line | 항목 | 설명 |
|---|---|---|
| 127-144 | `_build_mode_env()` | regime params → FG ENV 변환 (자동, 하드코딩 값 없음) |
| 145-205 | `_postprocess_ranking()` | wr + per/pbr/roe 후처리 (핵심) |
| 199 | `PENALTY = 50` | wr 계산 T-1/T-2 부재 시 penalty |
| 204 | wr 공식 `r0*0.5 + r1*0.3 + r2*0.2` | — |
| 482 | 주석 "v76: KP_MA200_5d" | **v79 주석 업데이트** |
| 490-503 | kospi/ma200/ret20 계산 | 그대로 유지 (ret20는 사용 안 하지만 파라미터만) |
| 510 | `get_current_regime(..., kospi_ret20=...)` | Crash 제거 시 ret20 인자 의미 없음 (regime_indicator 변경으로 자동 처리) |
| 553-555 | REGIME_CRASH_* ENV | v79에선 의미 없음. 로직 유지해도 무해 (crash_active 항상 False) |
**의존**: regime_indicator, data_refresher, fast_generate, send_telegram_auto, ranking_manager
**v79 변경점**: line 482 주석, (선택) 553-555 REGIME_CRASH env 정리

### 2.3 `C:\dev\send_telegram_auto.py` — 메시지 전송 + 시스템 수익률 계산
**역할**: Signal/Watchlist/전환 메시지 생성 + 개인봇/채널 전송
**하드코딩 (v79 변경 필수)**:
| line | 항목 | v77.1 값 | v79 변경 |
|---|---|---|---|
| 78 | 주석 v77.1 | — | **v79** 주석 |
| 352 | `if _stk >= 5` | 5 (calc_system_returns 내부 국면 재판단) | **7** |
| 802 | 주석 v77.1 | — | **v79** |
| 808 | `'📊 <b>v77.1 백테스트 성과</b>'` | — | **v79** |
| 810 | `'5.25년(2021~): CAGR +128% · MDD -28% · Calmar 4.58'` | v77.1 BT 수치 | **Phase 8 재측정 기준**: CAGR +105% · MDD -33% · Cal 3.18 |
| 811 | `'7.8년(2018-07~): CAGR +82% · MDD -55% · Calmar 1.50'` | v77.1 BT 수치 | **CAGR +121% · MDD -38% · Cal 3.20** |
| 818-846 | cash 모드 전환 메시지 전체 블록 | — | **전체 삭제 또는 비활성** |
| 841 | `'KOSPI > 200일선 5거래일 연속 → 공격 모드'` (cash 메시지 내) | — | cash 블록 삭제 시 무관 |
| 843 | `'사례: 2020-03 COVID ... Cal 1.35→1.50'` | v77.1 전용 | cash 블록 삭제 시 무관 |
| 856 | `'KOSPI가 200일 이동평균선 위에서 5거래일 연속 마감'` (boost 전환) | 5 | **7거래일** |
| 863 | `'📈 <b>공격 모드 상세 (v77.1)</b>'` | — | **(v79)** |
| 868 | `'Growth(성장) 65% + Momentum(추세) 30%'` | — | **Growth 50% + Momentum 30%** |
| 869 | `'+ Value(가치) 5%'` | — | **+ Value 15% + Quality 5%** |
| 871 | `'Growth 세부: 매출성장 50% + 영업이익변화 30% + 매출총이익성장 20%'` | — | **동일 유지 (3f gp 계속)** |
| 872 | `'모멘텀: 12m-1m (최근 1개월 제외)'` | — | **모멘텀: 12m (최근 1개월 포함)** |
| 874 | `'매수: 3일 연속 상위 7위 이내 ✅'` | 7 | **3위 이내** |
| 875 | `'보유: 최대 3종목'` | — | **동일 유지** |
| 876 | `'매도: 가중순위 8위 밖 이탈'` | 8 | **6위 밖** |
| 883-885 | `cash→defense 복귀 메시지` | — | **전체 삭제** |
| 888 | `'KOSPI가 200일선 아래에서 5거래일 연속'` (defense 전환) | 5 | **7거래일** |
| 902 | `'📉 <b>방어 모드 상세 (v77.1)</b>'` | — | **(v79)** |
| 907 | `'Momentum 55% + Value 30%'` | — | **Momentum 40% + Value 30%** |
| 908 | `'+ Growth 10% + Quality 5%'` | — | **+ Growth 15% + Quality 15%** |
| 910 | `'Growth 세부: 매출가속도 50% + 영업이익률변화 50%'` | v77 defense | **매출성장 70% + 영업이익변화 30%** |
| 911 | `'모멘텀: 6m-1m'` | — | **동일 유지** |
| 913 | `'매수: 3일 연속 상위 3위 이내'` | — | **동일 유지** |
| 914 | `'보유: 최대 7종목'` | — | **동일 유지** |
| 915 | `'매도: 가중순위 6위 밖 이탈'` | — | **동일 유지** |
| 918 | `'※ 20일 수익률 -20% 급락 시 자동 현금 도피'` | Crash | **삭제** |
| 970-987 | cash 모드 signal 메시지 | — | **블록 전체 삭제** |
| 987 | `'KOSPI > 200일선 5일 → 공격'` | 5 | (블록 삭제 시 무관) |
| 1267 | 주석 v77.1+ | — | **v79** |
| 1386 | 주석 v77.1 cash | — | **삭제 or v79 주석** |
| 1794 | 주석 v77.1 cash 전환 | — | **삭제 or v79 주석** |

**기타 기능**:
- `_rerank_for_regime` (111-191), `reranking_wrapper` (195-295): v78 재순위 기능 — **v79 비활성화 유지** (코드 남겨두되 실제 호출 없음)
- `calc_system_returns` (296-): 과거 전체 순회, 날짜별 regime 재판단, boost_data + defense_data 로드
- `load_ranking_for_regime` (76): 국면별 파일 선택
- wr 사용처: line 1083, 1234, 1246, 1579, 1682 — 모두 fallback `.get('weighted_rank', 999)` 있음

### 2.4 `C:\dev\data_refresher.py` — 데이터 캐시 갱신 (전략 무관)
**역할**: pykrx/DART/yfinance → data_cache/*.parquet 증분
**함수**: `refresh_all(base_date)` → 시가총액/펀더멘털/OHLCV/섹터/KOSPI/KOSDAQ 인덱스
**v79 변경점**: **없음** (전략 무관)

### 2.5 `C:\dev\backtest\fast_generate_rankings_v2.py` — FG 스코어링 (BT + 프로덕션 공용)
**역할**: 멀티팩터 점수 계산, ranking JSON 생성
**ENV 입력**:
| ENV | 의미 | v77.1 boost / defense | v79 boost / defense |
|---|---|---|---|
| FACTOR_V_W | V weight | 0.05 / 0.30 | **0.15 / 0.30** |
| FACTOR_Q_W | Q | 0.00 / 0.05 | **0.05 / 0.15** |
| FACTOR_G_W | G | 0.65 / 0.10 | **0.50 / 0.15** |
| FACTOR_M_W | M | 0.30 / 0.55 | **0.30 / 0.40** |
| G_SUB1 | G 서브1 | rev_z / rev_accel_z | **rev_z / rev_z** |
| G_SUB2 | G 서브2 | oca_z / op_margin_z | **oca_z / oca_z** |
| G_SUB3 | G 서브3 | gp_growth_z / None | **gp_growth_z / None** |
| G_W1 | 서브1 가중 | 0.5 / None | **0.5 / None** |
| G_W2 | 서브2 가중 | 0.3 / None | **0.3 / None** |
| G_W3 | 서브3 가중 | 0.2 / None | **0.2 / None** |
| G_REVENUE_WEIGHT | 2f rev 비중 | 0.0 / 0.5 | **0.0 / 0.7** |
| MOM_PERIOD | 모멘텀 | 12m-1m / 6m-1m | **12m / 6m-1m** |
| FILTER_NO_NEW_LISTING | (d) 필터 비활 | 미설정(=활성) | **유지** |
| FILTER_NO_CAPPED | (e) 필터 비활 | 미설정(=활성) | **유지** |
| PRODUCTION_MODE | 빠른모드 | 1 | **1** |

**출력 필드** (ranking JSON):
`rank, composite_rank, ticker, name, score, sector, value_s, quality_s, growth_s, momentum_s, rev_z, oca_z, rev_accel_z, gp_growth_z, op_margin_z, cfo_growth_z, mom_6m_s, mom_6m1m_s, mom_12m_s, mom_12m1m_s, price`
**wr 필드**: ❌ 생성 안 함 (run_daily._postprocess_ranking에서 후처리)

### 2.6 `C:\dev\ranking_manager.py` — wr 계산 중복 구현
**역할**: send_telegram에서 ranking을 가공할 때 wr 재계산 용도
**하드코딩**: wr 공식 line 157, 372 (run_daily와 동일 수식 `r0*0.5 + r1*0.3 + r2*0.2`)
**v79 변경점**: **없음** (수식 동일)

### 2.7 `C:\dev\backtest\regenerate_all_v77.py` — 과거 state 재생성 (재활용)
**하드코딩 (v79용 복제 필요)**: BOOST_ENV, DEFENSE_ENV, START_DATE, END_DATE
**v79 변경점**: **새 파일로 복제** `regenerate_all_v79.py`

### 2.8 `C:\dev\run_phase3_bt_regen.py` — Phase 3 BT 전체 재생성 (재활용 참고)
v77 파라미터 하드코딩. v79는 prod만 필요(bt_extended 무관).

---

## 3. 데이터 경로

| 경로 | 용도 | 기간 | 변경 여부 |
|---|---|---|---|
| `C:/dev/state/ranking_*.json` | 프로덕션 boost (+wr 활성모드만) | 2021-01-04 ~ 2026-04-14 (1294일) | **전체 재생성** |
| `C:/dev/state/defense/ranking_*.json` | 프로덕션 defense | 동일 | **전체 재생성** |
| `C:/dev/state/regime_state.json` | 국면 상태 (mode/streak/history) | — | **v79로 라벨 업데이트** |
| `C:/dev/backtest/bt_extended/ranking_*.json` | BT boost | 2018-07-02 ~ 2020-12-30 (617일) | **불필요** (시스템 수익률은 state/만 사용) |
| `C:/dev/backtest/bt_extended_defense/ranking_*.json` | BT defense | 동일 | **불필요** |
| `C:/dev/data_cache/kospi_yf.parquet` | KOSPI 종가 + MA200 원천 | 2017-06~현재 | **refresh 필요** (14:36 완료) |
| `C:/dev/data_cache/market_cap_*.parquet` | 시총 | 일별 | 동일 |
| `C:/dev/data_cache/fundamental_*.parquet` | pykrx 펀더멘털 | 일별 | 동일 |
| `C:/dev/data_cache/all_ohlcv_*.parquet` | OHLCV | 2017-06~현재 | 동일 |
| `C:/dev/data_cache/fs_dart_*.parquet` | DART 재무제표 | 종목별 | 동일 |
| `C:/dev/data_cache/krx_sector_*.parquet` | 섹터 | 일별 | 동일 |

**백업**: `C:/dev/state_backup_20260415_v77_1/` (완료, 1295+1294 파일)

---

## 4. 외부 의존성

### 4.1 스케줄러 (Windows Task Scheduler)
| 태스크 | 스케줄 | 용도 | 상태 |
|---|---|---|---|
| `QuanT_DailyPipeline` | 평일 16:00 | run_daily.py | **v79 작업 중 비활성화 완료** |
| `QuanT_RefreshTickerNames` | 일요일 10:00 | 종목명 캐시 | 유지 |
| `QuanT_DataAvailTest` | N/A | 비활성 | — |
| `QuanT_Notice_Once` | N/A | 비활성 | — |

**v79 적용 후**: `QuanT_DailyPipeline` **재활성화 필수** (`schtasks /Change /ENABLE`)

### 4.2 텔레그램
- `TEST_MODE=1`: 개인봇만 (검증용, 기본)
- `TEST_MODE` 미설정: 채널 전송 (고객용, **명시 승인 시에만**)
- 토큰/챗ID: `config.py` 참조

### 4.3 외부 API
- pykrx: 1초 sleep 필수, 병렬 금지 (IP 차단)
- DART: 증분 업데이트
- yfinance: KOSPI/KOSDAQ 인덱스 fallback

---

## 5. v77.1 → v79 변경 체크리스트 (맹점 제로)

### 5.1 코드 변경
- [ ] `regime_indicator.py`
  - [ ] CONFIRM_DAYS 5 → 7 (line 65)
  - [ ] CRASH 로직 전부 제거 (line 64, 68-82, 118-128, 131-134)
  - [ ] `cash` 모드 분기 제거 (line 175-189)
  - [ ] boost params (line 190-206) → V15/Q5/G50/M30, 12m, E3X6S3
  - [ ] defense params (line 207-223) → V30/Q15/G15/M40, 2f(rev+oca, 0.7), E3X6S7
  - [ ] 주석 line 1~16 v79로 업데이트

- [ ] `send_telegram_auto.py`
  - [ ] line 352 `_stk >= 5` → `>= 7`
  - [ ] line 808 v77.1 → v79
  - [ ] line 810-811 성과 수치 재측정값 반영
  - [ ] line 818-846 cash 메시지 블록 제거 (또는 return이 절대 안 닿도록)
  - [ ] line 856 "5거래일" → "7거래일"
  - [ ] line 863, 867-877 공격 모드 상세 v79 파라미터
  - [ ] line 883-885 cash→defense 메시지 제거
  - [ ] line 888 "5거래일" → "7거래일"
  - [ ] line 902, 906-916 방어 모드 상세 v79 파라미터
  - [ ] line 918 Crash 경고 제거
  - [ ] line 970-987 cash signal 메시지 블록 제거
  - [ ] 주석 v77.1 → v79 (line 78, 802, 1267, 1386, 1794)

- [ ] `run_daily.py`
  - [ ] line 482 주석 "v76: KP_MA200_5d" → "v79: KP_MA200_7d"

### 5.2 데이터 재생성
- [ ] `state/` 1294일 재생성 (v79 boost ENV)
- [ ] `state/defense/` 1294일 재생성 (v79 defense ENV)
- [ ] **병렬 2워커** (boost_prod + def_prod, bt_extended 불필요하므로 4워커 불필요, 메모리/속도 최적)
- [ ] wr 후처리 batch (1294일 × 2 = 2588회 `_postprocess_ranking`, 과거 시스템 수익률 정확도 향상, ~1분)
- [ ] 샘플 검증: 랜덤 10일 Top 20 spot-check + wr 필드 존재 확인

### 5.3 상태 업데이트
- [ ] `state/regime_state.json` version/rule 필드 → `v79_final` / `KP_MA200_7d`
- [ ] crash_active 필드 제거 또는 False 고정

### 5.4 검증
- [ ] TEST_MODE=1 run_daily 실행 → 개인봇 메시지 도착
- [ ] 메시지 내용 v79 파라미터 반영 확인
- [ ] ranking_20260414.json weighted_rank 필드 존재 + 값 합리
- [ ] calc_system_returns 결과 Phase 8 BT와 ±10% 이내
- [ ] 현재 국면 boost 유지 (KOSPI 5967 >> MA200 4172)

### 5.5 배포 (사용자 승인 후)
- [ ] 커밋 메시지 v79 상세 기록
- [ ] 푸시 (사용자 명시 승인 후)
- [ ] `schtasks /Change /ENABLE` 스케줄러 재활성화 (`QuanT_DailyPipeline`)
- [ ] CLAUDE.md v77.1 → v79 섹션 전환
- [ ] MEMORY.md 업데이트
- [ ] 개인봇으로 전환 안내 (TEST_MODE=1, **채널 전송은 명시 승인 후**)
- [ ] **사용자에게 "과거 시스템 수익률 숫자 변경" 사전 고지**:
  - 어제까지 메시지에 표시되던 "5.25년 CAGR +128% / Cal 4.58"이 오늘부터 "+105% / Cal 3.18"로 바뀜
  - 이는 v79 전략으로 과거를 재계산한 결과 (BT 재측정 기준)
  - 사용자 입장에선 "수치가 왜 바뀌었지?" 의문 가능 → 사전 안내 필수

### 5.6 롤백 계획
- [ ] `regime_indicator.py.bak_20260415` 복원 가능 (완료)
- [ ] `send_telegram_auto.py.bak_20260415` 복원 가능 (완료)
- [ ] `state_backup_20260415_v77_1/` 복원 가능 (완료, 1295+1294 파일)

---

## 6. 다음 전략 교체 시 재사용 가능한 메타 체크리스트

(영구. 이 섹션이 본 문서의 핵심 자산)

### 6.1 "파라미터 진본" 수정
- [ ] `regime_indicator.py` 내부 dict 수정
- [ ] V/Q/G/M 합=1.0 확인
- [ ] E/X/S 합리성
- [ ] G_SUB + G_W 일관성 (3팩터면 가중 합=1.0, 2팩터면 G_REVENUE_WEIGHT 설정)

### 6.2 "메시지 업데이트" (하드코딩 전수 grep)
```bash
# 다음 grep으로 매번 확인
grep -n "v[0-9]\+" send_telegram_auto.py
grep -n "Calmar\|CAGR\|MDD" send_telegram_auto.py
grep -n "5거래일\|5일\|7일\|7거래일" send_telegram_auto.py
grep -n "Growth.*[0-9]\+%\|Momentum.*[0-9]\+%\|Value.*[0-9]\+%" send_telegram_auto.py
grep -n "매수:\|매도:\|보유:" send_telegram_auto.py
```

### 6.3 "국면 로직 중복 점검"
- [ ] `regime_indicator.py` CONFIRM_DAYS
- [ ] `send_telegram_auto.py` calc_system_returns 내부 국면 재판단 상수 (line 352)
- [ ] 두 값 **반드시 일치**

### 6.4 "state 재생성"
- [ ] `regenerate_all_*.py` 복제 → 새 버전
- [ ] boost + defense 양쪽 ENV 변경
- [ ] START_DATE/END_DATE 최신화
- [ ] 재생성 후 **wr batch 후처리 필수**
- [ ] 샘플 검증 (랜덤 10일)

### 6.5 "파이프라인 테스트"
- [ ] data_refresher 최신 실행
- [ ] `TEST_MODE=1 python run_daily.py` → 개인봇 확인
- [ ] calc_system_returns 결과가 BT와 ±10% 일치
- [ ] weighted_rank 당일 파일에 있음

### 6.6 "배포 원칙"
- [ ] 스케줄러 작업 중 비활성화, 완료 후 재활성화
- [ ] state/ 백업 → 롤백 가능
- [ ] 채널 전송은 명시 승인 후만 (TEST_MODE=1 기본)
- [ ] feedback 메모리 업데이트

---

## 7. PIT (Point-in-Time) 보장 체계 (2026-04-15 강화)

### 7.1 데이터 소스별 PIT 상태

| 소스 | PIT 구조 | 구현 |
|---|---|---|
| **pykrx** (OHLCV/market_cap/fundamental/sector/index) | A+ 구조적 | 파일명 자체가 날짜. `find_nearest_cache(..., strict=False)`로 `d <= target_date` 필터 |
| **DART** (fs_dart_*.parquet) | A (rcept_dt 기반) | 파일에 `rcept_dt` 필드. 모든 계산 경로 `rcept_dt <= base_ts` 필터 |
| **FnGuide** (fs_fnguide_*.parquet) | A (2026-04-15 개선) | DART rcept_dt 역추적으로 `rcept_dt` 이식 완료. 130만 건 매칭. |

### 7.2 FnGuide rcept_dt 역추적 (`postprocess_fnguide_rcept.py`)

**문제**: FnGuide 원본 스키마 `['계정','기준일','값','종목코드','공시구분']` — **rcept_dt 없음**.
**해결**: DART의 (기준일, 공시구분) → rcept_dt 매핑을 FnGuide에 이식.
- 매칭 실패 시 기본값: 연간 기준일+90일 / 분기 기준일+45일 (법정 기한)
- 2,766 종목 전체 49초 (4워커), 1,303,389건 매칭
- 결과: FnGuide 파일에 `rcept_dt` 필드 추가됨

### 7.3 FnGuide 매일 증분 (`refresh_fnguide_incremental.py`)

run_daily.py Step 0.1에 삽입됨:
- DART 최근 3일 내 갱신된 종목만 FnGuide 재크롤 (웹 크롤링 부하 최소화)
- 크롤링 후 자동으로 `postprocess_fnguide_rcept.py` 호출 → 신규 파일에도 rcept_dt 이식
- ENV: `FNG_INCR_DAYS` (기본 3일)

### 7.4 잠재 PIT 위반 (경미, 남은 과제)

| 이슈 | 위치 | 영향 |
|---|---|---|
| 섹터 max_gap 120일 | fast_generate line 1525 | 섹터 변경 드물어 실용적 영향 없음 |
| FnGuide rcept_dt 기본값 추정 케이스 | 약 0.1% 레코드 | 연간 90일/분기 45일 기본값. 실제보다 늦게 추정하므로 look-ahead 없음 (보수적) |

## 8. -1.5σ 필터 분석 결과 (2026-04-16)

5옵션 BT 비교로 **baseline(-1.5σ 4팩터) 유지 확정**:
- baseline score=3.36 > B=3.24 > A=D=3.19 > C=2.94
- 연도별 검증에서도 baseline 평균 Cal 6.45로 최고
- 대형 전력주(HD현대일렉, 제룡전기) 누락은 아쉽지만 포함 시 성과 하락
- `EXTREME_MODE` env var로 재실험 가능 (A/B/C/D)
- 분석 스크립트: `phase8_extreme_compare.py`, `phase8_yearly_compare.py`

## 9. 알려진 개선 과제 (v79 이후)

| 이슈 | 위치 | 영향 |
|---|---|---|
| kospi_yf 첫 컬럼 NaN fallback 없음 | send_telegram_auto.py line 339 | 과거 시점 KOSPI 부분 누락 가능 |
| wr 후처리가 활성 모드 파일에만 적용 | run_daily._postprocess_ranking line 309-318 | 비활성 모드 ranking 파일엔 wr 없음 (fallback 999 있어 치명적 아님) |
| v77 이슈조사 미해결 6개 (13 중 7개 해결됨) | fc29095d4 commit | MA120 필터 주석불일치, 지주사 NaN 등 |
| ranking_manager.py wr 재계산 중복 | line 157, 372 | 수식 동일하므로 무해 |
