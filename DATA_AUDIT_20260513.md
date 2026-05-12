# 데이터 전수 검사 보고서 (2026-05-13 07:24, 정정판)

## 1줄 결론
**OHLCV + 그 후속(state, bt_extended) 외의 모든 데이터는 정상**. fundamentals/KOSPI 결손 의심은 오판으로 판명.

---

## 데이터별 상태

### ✅ 정상 데이터

| 데이터 | 종목/일자 | 최신 | 비고 |
|--------|----------|-----|------|
| **DART** (`fs_dart_*.parquet`) | 1952 종목 | rcept_dt max 2026-04-07 | 5월=Q1시즌 직전 정상 분포 |
| **FnGuide** (`fs_fnguide_*.parquet`) | 2768 종목 | 기준일 max 2025-12-31 | Q4 일부 종목만 갱신 — 정상 진행 중 |
| **market_cap** (`market_cap_ALL_*`) | 2069 파일 | 5/12=2769 종목 | 최근 7일 2768~2771 일관 |
| **fundamental_batch** (`fundamental_batch_ALL_*`) | 2071 파일 | 5/12=2720 종목 | ⭐ production 매일 사용 |
| **sectors** (`krx_sector_*`) | 266 파일 | 5/12=2615 종목 | 정상 |
| **KOSPI** | 2017-01-02 ~ 2026-05-12 | 5/12 종가 7643.15 | 두 컬럼(종가/kospi) 상호보완으로 NaN 0행 |
| **KOSDAQ** | 2020-06-01 ~ 2026-05-12 | 5/12까지 | 2020-06 이전은 옛날부터 없음 |
| **regime_state.json** | `state/regime_state.json` | 정상 | (root 아닌 state/ 안) |

### ⚠️ 결손 데이터 (회사 PC 도착 후 정상화 필요)

| 데이터 | 상태 |
|--------|------|
| **OHLCV** (`all_ohlcv_20170601_20260512.parquet`) | 결손 1475일 — **백그라운드 refill 진행 중** (ETA 35분) |
| **state/** boost ranking | 1929 파일, 평균 141 종목 (정상 320+), <100 종목 파일 **647개** |
| **state/defense/** | 1929 파일, 평균 140 종목, <100 종목 파일 661개 |
| **bt_extended/** + **bt_extended_defense/** | 617 파일씩 (2018-07~2020-12), 평균 104 종목 |

### 🟨 무시 가능 (production 안 씀)

| 데이터 | 상태 | 비고 |
|--------|------|------|
| `fundamentals_*.parquet` (24개) | 99 종목만 | ❌ **옛날 코드 산출물, 사용 안 함**. 실제는 `fundamental_batch_*` 사용 |

---

## 오판 정정 사항 (검사 보고서 작성 후 발견)

1. **fundamentals 99 종목 결손 → 오판**
   - 진짜 production 파일은 `fundamental_batch_ALL_*.parquet` (5/12=2720 종목 정상)
   - `fundamentals_*.parquet`은 옛 `get_all_fundamentals` 산출물 (분기별, 사용 안 함)

2. **KOSPI/KOSDAQ NaN 행 100% → 오판**
   - 두 컬럼(`종가`, `kospi`) 상호 보완 구조 — `종가` NaN 44개, `kospi` NaN 2247개
   - 어느 한 컬럼 NaN 있는 행이 100%일 뿐, 둘 다 NaN인 행은 **0개**. 정상.

3. **regime_state.json MISSING → 오판**
   - 위치가 `state/regime_state.json` (root 아님). 정상 존재.

---

## 결손 원인 (반복)

- OHLCV 2019-06~2026-03 결손이 모든 BT용 데이터의 근본 원인
- state ranking과 bt_extended의 종목 수 결손은 OHLCV 결손 위에서 fast_generate_rankings_v2.py가 ranking을 만들었기 때문
- 일단 OHLCV refill 완료되면 → state 재생성 → bt_extended 복사로 모두 정상화 가능

---

## 회사 PC 도착 시 액션 (HANDOVER_20260513.md §11.3 + 본 보고서)

1. `git pull origin main` (OHLCV refill 결과 + 보고서 받기)
2. 채널 5/12자 메시지 3개 수동 삭제
3. OHLCV 검증: `pd.read_parquet().notna().sum(axis=1).resample('Q').mean()` — 모든 분기 1500+이어야
4. state 전체 재생성 (1929일×2, 4~6시간)
5. wr batch + 7.8년 BT (Cal ≥ 3.97 목표)
