# 자율 진행 중 사고 보고 (2026-05-13 새벽)

## 🚨 사고 1: data_cache/all_ohlcv_*.parquet 부재

**시점**: 자동 스크립트 Step 9 진입 직전
**증상**: `data_cache/` 직접 위치에 `all_ohlcv_*.parquet` 파일 없음
**원인 추정**: 어제(5/12) 작업 중 다른 위치로 이동되거나 정리됨. 사용자 회사 PC commit `9a2365624` "untrack + gitignore" 의도는 파일 보존이었으나 working tree에서 사라짐.
**복원**: `_ohlcv_backup/all_ohlcv_20190603_20260330.parquet` (3/30까지) 복원

## 🚨 사고 2: pykrx IP 차단 재발

**시도**: 3/31~5/11 30거래일 증분 수집
**결과**: 모든 일자 빈 DataFrame (KeyError → empty result)
**진단**: 다른 일자 (2025-01-02 등 정상 거래일) 시도해도 빈 결과 = **IP 차단**
**사용자 메모리**: 2026-03-24 차단 해제 확인 → 5/13 새벽 재차단 발견

## 결정 — 백업 3/30 데이터로 진행 (후보 C)

**근거 3개**:
1. **시스템 본질 작업 가능** — Step 9 state 재생성, Step 10 BT, Step 12 commit, Step 13 스케줄러 모두 가능
2. **5/12 16시 자동 스케줄러가 5/12 OHLCV 갱신** — 회사 PC 또는 사용자 일어났을 때 정상 갱신
3. **자율 진행 + 멈춤 금지** 원칙 — pykrx 대기 시간 불확실

## 5/11 비교 SKIP

- Step 11 `state_verify/5/11 ranking 단독 재생성` skip
- 옛 state (옵션F 시대) 5/11 ranking은 `state_backup_pre_optf_20260512/`에 보존
- 새 state는 3/30까지 (5/11 ranking 없음)

## 사용자 일어났을 때 권장 조치

1. **pykrx IP 차단 확인** — 시간 경과 후 자연 해제 또는 ISP 재시작
2. **OHLCV 3/31~5/11 수동 갱신** — pykrx 해제 후 `fix_ohlcv_incremental.py` 재실행
3. **5/12 자동 스케줄러 16시** — 정상 작동 시 5/12 ranking 자동 추가
4. **5/11 production ranking 옵션F 시대 잔존 가능성** — 5/13 16시 이후 새 ranking으로 자동 갱신
