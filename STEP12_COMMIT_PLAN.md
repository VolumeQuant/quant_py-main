# Step 12 Commit 계획 (사전 작성)

**작성**: 2026-05-12 (Step 3 진행 중)
**적용**: `step3_to_step11_auto.py` 완료 후

---

## 변경 사항 분류

### A. 코드 변경 (매뉴얼 외 추가)
- `refetch_serial.py` — 경로 PROJECT_DIR 기반 + sleep 0.3초
- `verify_after_refetch.py` — 경로 PROJECT_DIR 기반
- `diagnose_all.py` — 단일 worker 변경 (사용자 원칙 준수)
- `monitor_dart_fn_health.py` — 영업이익 부호 다름 검사 추가 (THRESHOLD_OPI_SIGN=3)
- `run_daily.py` — Step 0.2 무결성 의심 시 개인봇 알림 (비차단)
- `backtest/regenerate_all_v80.py` — state 끝 날짜 20260418 → 20260511

### B. 옵션F 시대 산물 삭제
**8개 스크립트 삭제**:
- `swap_state_optf.py`
- `regenerate_may_optf.py`
- `sync_bt_from_state.py`
- `verify_state_optf.py`
- `send_completion_summary.py`
- `backtest/regenerate_all_v80_optf_finfilter.py`
- `backtest/postprocess_wr_state_new.py`
- `backtest/postprocess_pbr_state_new.py`

**6개 디렉토리 삭제 (459MB+)**:
- `backtest/bt_optf_boost/`
- `backtest/bt_optf_defense/`
- `backtest/state_optf_test/`
- `backtest/state_optf_test_511/`
- `backtest/state_finfilter_test/`
- `state_new/`

### C. 데이터 변경
- **fs_dart_*.parquet** ~213종목 재수집 (179 메인 + 34 추가)
- **state/ranking_*.json** + **state/defense/ranking_*.json** (Step 9 재생성, ~1929일 × 2)
- **backtest/bt_extended/** + **backtest/bt_extended_defense/** (Step 9 재생성, 2018-07~2020-12)

### D. 메모리 / 문서
- `MEMORY_UPDATE_20260512_OPTION_F_INCIDENT.md` (새 파일)
- `ROLLBACK_PLAN_20260512.md` (이 파일 외 새 파일)
- `STEP12_COMMIT_PLAN.md` (이 파일)
- `bad_tickers_additional.txt` (10종목)
- `bad_tickers_step3_additional.txt` (34종목 통합)
- `step3_to_step11_auto.py` (자동화 스크립트)

### E. .gitignore 변경
- 옵션F 시대 디렉토리 ignore 유지 (재발 방지)
- `state_new/` 추가

---

## Staging 순서

### Commit 1: 코드 변경 + 옵션F 시대 삭제 + 추가 스크립트
```powershell
# 코드 + 문서
git add refetch_serial.py verify_after_refetch.py diagnose_all.py
git add monitor_dart_fn_health.py run_daily.py
git add backtest/regenerate_all_v80.py
git add .gitignore

# 삭제 (이미 rm 됨, git이 자동 감지)
git rm swap_state_optf.py regenerate_may_optf.py sync_bt_from_state.py
git rm verify_state_optf.py send_completion_summary.py
git rm backtest/regenerate_all_v80_optf_finfilter.py
git rm backtest/postprocess_wr_state_new.py
git rm backtest/postprocess_pbr_state_new.py

# 새 스크립트 + 문서
git add bad_tickers_additional.txt bad_tickers_step3_additional.txt
git add step3_to_step11_auto.py
git add MEMORY_UPDATE_20260512_OPTION_F_INCIDENT.md
git add ROLLBACK_PLAN_20260512.md
git add STEP12_COMMIT_PLAN.md
```

### Commit 1 메시지 (HEREDOC)
```
fix(data): fs_dart 캐시 무결성 정상화 + 추가 안전망 (5/15 폭주 대비)

5/12 옵션F 사고 → 캐시 본질 정정 (179 메인 + 34 추가 = 213종목 재수집).
LG엔솔/LG화학 영업이익 매핑 사고 추가 발견 → monitor 강화.

코드 변경:
- refetch_serial.py: 경로 PROJECT_DIR 기반 + sleep 0.3초
- diagnose_all.py: 단일 worker (사용자 원칙 "DART 병렬 절대 X")
- monitor_dart_fn_health.py: 영업이익 부호 다름 검사 추가 (THRESHOLD_OPI_SIGN=3)
- run_daily.py: 무결성 의심 시 개인봇 즉시 알림 (비차단)
- backtest/regenerate_all_v80.py: state 끝 날짜 4/18 → 5/11

옵션F 시대 산물 정리:
- 8개 일회성 스크립트 삭제
- 6개 디렉토리 삭제 (459MB+ 회수, .gitignore 유지)

자동화:
- step3_to_step11_auto.py: Step 3 후 Step 4~11 자동 진행
- bad_tickers_step3_additional.txt: 추가 34종목 통합 리스트

문서:
- MEMORY_UPDATE_20260512_OPTION_F_INCIDENT.md: 회사 PC 동기화용
- ROLLBACK_PLAN_20260512.md: BT Cal < 2.5 시 대응 시나리오

추가 BAD (10종목, bad_tickers_additional.txt):
- 캐시 분석 4: 004770 써니전자, 007120 미래아이앤지, 052860 아이앤씨, 153460 네이블
- 영업이익 매핑 6: 051910 LG화학, 373220 LG엔솔, 008930 한미사이언스,
                   117670 알파칩스, 104480 티케이케미칼, 063080 컴투스홀딩스
```

### Commit 2: fs_dart 재수집 결과
```powershell
git add data_cache/fs_dart_*.parquet
```
메시지: `data: fs_dart 213종목 재수집 (Step 3 + Step 8 통합)`

### Commit 3: state + bt_extended 재생성
```powershell
git add state/ state/defense/ backtest/bt_extended/ backtest/bt_extended_defense/
```
메시지: `state: v80 7.8년 재생성 (옵션F 폐기 후 깨끗한 캐시)`

---

## pre-commit hook 통과 확인 사항
1. dart_collector.py 변경 없음 (기존 5/4 fix 유지) → test_account_map 통과
2. fs_dart_*.parquet 변경 시 무결성 검사 자동 실행
3. 의심 종목 발견 시 commit 차단 → refetch 추가

## Step 13 스케줄러 재활성화 (commit 후)
```powershell
schtasks /Change /TN "QuanT_DailyPipeline" /ENABLE
schtasks /Query /TN "QuanT_DailyPipeline" /FO LIST | Select-String "Status"
```
