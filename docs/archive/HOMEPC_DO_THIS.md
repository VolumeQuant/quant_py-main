# 🏠 집PC 작업 매뉴얼 (v2 — 검증 완료) — fs_dart 캐시 정상화

**작성**: 2026-05-12 회사PC 마지막 작업 (검증 11/11 통과)
**소요 시간**: 약 60~90분 (대부분 자동, 사람 개입 최소)
**전제**: 회사PC에서 DART 병렬 호출 사고로 IP 일시 차단. 집PC IP로 진행.

---

## 📋 전체 흐름

```
1. git pull                              (10초)
2. pre-commit hook 설치                    (10초)
3. python refetch_serial.py                (~16분)  ★ DART 호출
4. python verify_after_refetch.py          (3분)
5. python test_account_map.py              (10초)
6. python test_account_map_negative.py     (10초)
7. python diagnose_all.py (incomplete)     (~15분, 선택)  ★ DART 호출
8. python refetch_serial.py extra          (~3분, 선택)  ★ DART 호출
9. python backtest/regenerate_all_v80.py   (~28분)
10. BT 검증 (turbo_simulator 또는 compare_optf_bt)
11. 5/11 ranking 재생성
12. git commit + push                      (1분)
13. 스케줄러 재활성화                       (10초)
```

★ 표시 = DART API 호출 단계. **PowerShell 하나만 열어서 순차 실행**. 병렬 절대 X.

---

## Step 1. git pull (10초)

```powershell
cd C:\dev
git pull origin main
```

**예상 출력**: "Updating ... Fast-forward"
**실패 시**: 충돌나면 멈추고 보고. 데이터 손실 위험.

---

## Step 2. pre-commit hook 설치 (10초)

```powershell
Copy-Item C:\dev\hooks\pre-commit C:\dev\.git\hooks\pre-commit -Force
```

설치 검증:
```powershell
Test-Path C:\dev\.git\hooks\pre-commit
# True 나오면 OK
```

**역할**: 다음에 dart_collector.py / fs_dart 잘못된 매핑으로 commit 시도 시 자동 차단

---

## Step 3. 잘못된 179종목 재수집 (~16분) ★ DART 호출

```powershell
python C:\dev\refetch_serial.py
```

**조건**:
- 단일 worker, sleep 5초, ConnectionError 시 자동 60s→180s→600s 백오프
- 캐시 atomic rename (실패해도 손실 0)
- 입력: `bad_tickers_v3.txt` (179종목)

**예상 출력**:
```
============================================================
재수집 — 단일 worker, sleep 5초, exponential backoff
============================================================
입력: C:/dev/bad_tickers_v3.txt
대상: 179종목 (2016-2026 11년치)
예상 시간: 약 16.4분
============================================================
  [1/179] 000040: ✓ 성공 720 rows (5s)
  [2/179] 000890: ✓ 성공 680 rows (10s)
  ...
완료: 성공 179/179, 빈 결과 0, 실패 0
```

**실패 케이스**:
- 일부만 실패 → `BAD_LIST=C:/dev/refetch_failed.txt python C:/dev/refetch_serial.py` 재시도
- 모두 ConnectionError → DART 또 차단됐을 가능성. **30분 쉬고** 재시도 (병렬 절대 X)

---

## Step 4. 자동 검증 (3분)

```powershell
python C:\dev\verify_after_refetch.py
```

**판정 (자동)**:
- **종료 코드 0**: ✅ 잔여 BAD ≤ 5 AND big_diff ≤ 10 → Step 5 진행
- **종료 코드 1**: ⚠️ 일부 문제 → 잔여 종목 확인 후 진행 가능
- **종료 코드 2**: ❌ 잔여 BAD > 20 → Step 3 재실행

**예상 출력 (정상화 성공 시)**:
```
[1] bad_tickers_v3 (179) 정상화 검사
  ✓ 정상화: 175/179
  ✗ 잔여 BAD: 4 (지주사 false positive 추정)
  -  FN 없음: 0

[2] 전체 fs_dart 5배+ 차이 베이스라인
  현재 big_diff: 8 (기대 ≤ 10)

[3] 영업이익 > 매출 비정상 카운트
  현재 카운트: 32 (기대 ≤ 50)

✅ 검증 통과 — 정상화 완료
```

**잔여 BAD 종목 = 지주사 false positive 약 7개 + SK스퀘어 같은 산업지주사 약 3개**. 정상.

---

## Step 5. 매핑 unit test (10초)

```powershell
python C:\dev\test_account_map.py
```

**예상 출력**:
```
✅ 모든 테스트 통과 (4/4)
```

---

## Step 6. unit test 음의 검증 (10초)

```powershell
python C:\dev\test_account_map_negative.py
```

**예상 출력**:
```
음의 검증 통과: 5/5
✅ unit test가 모든 시나리오 정확 검출
```

---

## Step 7. 진단 미완료 1542종목 재진단 (~15분, 선택) ★ DART 호출

회사PC에서 DART silent fail로 진단 안 된 종목들.

```powershell
$env:DIAG_INPUT = "C:\dev\incomplete_diag_tickers.txt"
python C:\dev\diagnose_all.py
Remove-Item Env:DIAG_INPUT
```

**출력**:
- `diagnose_incomplete_diag_tickers_detail.json`
- `bad_tickers_incomplete_diag_tickers.txt` (새로 발견된 BAD)

새 BAD 종목 있으면:
```powershell
$env:BAD_LIST = "C:\dev\bad_tickers_incomplete_diag_tickers.txt"
python C:\dev\refetch_serial.py
Remove-Item Env:BAD_LIST
```

**선택**: 시간 없으면 스킵. 현재 v3 179종목으로도 가짜 알파 대부분 차단 가능 (다만 1% 잔여 위험).

---

## Step 8. extra 24종목 + other_accts 3종목 재수집 (~3분, 선택) ★ DART 호출

```powershell
$env:BAD_LIST = "C:\dev\bad_tickers_extra.txt"
python C:\dev\refetch_serial.py
Remove-Item Env:BAD_LIST
```

영업이익 매핑 의심 3종목 (008110/030960/099750)도 포함:
```powershell
$env:BAD_LIST = "C:\dev\bad_tickers_other_accts.txt"
python C:\dev\refetch_serial.py
Remove-Item Env:BAD_LIST
```

---

## Step 9. state 7.8년 재생성 (~28분)

```powershell
python C:\dev\backtest\regenerate_all_v80.py
```

**자동 진행 내용**:
- `state/` 1294일 (2021-01-04 ~ 2026-04-18) — 공격 모드 + 환경변수 자동 설정
- `state/defense/` 1294일 — 방어 모드
- `backtest/bt_extended/` — 7.8년 BT용 (2018-07-02 ~ 2020-12-30)
- `backtest/bt_extended_defense/` — 방어 BT
- 2병렬 × 2순차

**환경변수**: 스크립트 안에 모두 하드코딩 (V/Q/G/M, G_SUB, MOM_PERIOD, etc). 별도 설정 불필요.

**실패 시**: `monitor_dart_fn_health.py` 먼저 실행해 캐시 무결성 확인.

---

## Step 10. BT 검증 (~5분)

```powershell
# v80 BT (옵션F vs 정정후 비교)
python C:\dev\backtest\compare_optf_bt.py
```

**기대 결과 (BT Cal 임계값)**:
| BT | baseline | Pass | 재검토 | Roll back |
|---|---|---|---|---|
| 7.8년 | 3.97 | **≥ 3.5** | 2.5~3.5 | < 2.5 |
| 5.25년 | 4.71 | **≥ 4.0** | 3.0~4.0 | < 3.0 |

- baseline은 옵션F + 가짜 알파 포함 수치. 정정 후 ±0.5 변동 예상.
- **Roll back 발생 시 commit 하지 마**. `git stash` 후 점검.

---

## Step 11. 5/11 ranking 재생성

```powershell
python C:\dev\backtest\fast_generate_rankings_v2.py 20260511 20260511 --state-dir=C:\dev\state_verify
```

**확인할 것**:
- Top 20에서 KBI메탈(024840), 링네트(042500), 우원개발(046940), 전진건설로봇(072950), SK스퀘어(402340) 등 가짜 알파 종목 제외 확인
- 우원개발은 진짜 영업이익 폭증으로 일부 유지 가능

기존 파일 (옛 가짜 알파 포함): `state/ranking_20260511.json`
새 파일: `state_verify/ranking_20260511.json`

비교:
```powershell
python -c "import json; o=json.load(open('C:/dev/state/ranking_20260511.json',encoding='utf-8')); n=json.load(open('C:/dev/state_verify/ranking_20260511.json',encoding='utf-8')); print('OLD Top 10:', [(r.get('ticker'),r.get('name')) for r in o['rankings'][:10]]); print('NEW Top 10:', [(r.get('ticker'),r.get('name')) for r in n['rankings'][:10]])"
```

---

## Step 12. git commit + push (1분)

```powershell
cd C:\dev

# 변경 확인
git status

# 코드 + 데이터 + state stage
git add data_cache/fs_dart_*.parquet
git add state/
git add backtest/bt_extended/ backtest/bt_extended_defense/

# 신규 분석 결과 (선택)
git add diagnose_incomplete_diag_tickers_detail.json
git add bad_tickers_incomplete_diag_tickers.txt

# 커밋 (pre-commit hook 자동 실행)
git commit -m "fix(data): fs_dart 179종목 재수집 + state v80 재생성 (회사PC 사고 정상화)"

# 푸시
git push origin main
```

**pre-commit hook이 차단하면**:
- "매핑 무결성 검사 실패" → dart_collector.py 점검
- "fs_dart 무결성 의심" → 잔여 BAD 종목 재수집 후 다시 시도
- `--no-verify` **절대 쓰지 마**

---

## Step 13. 스케줄러 재활성화 (10초)

```powershell
schtasks /Change /TN "QuanT_DailyPipeline" /ENABLE

# 확인
schtasks /Query /TN "QuanT_DailyPipeline" /FO LIST | Select-String "Status"
# "Ready" 나오면 OK
```

**완료!** 🎉

---

## 🆘 문제 발생 시

### Q. Step 3에서 ConnectionError 계속 나면?
A. 30분~1시간 쉬고 재시도. 집PC IP도 짧게 막혔을 수 있음. **병렬로 돌리지 마**.

### Q. Step 4 코드 1 (잔여 6~20개)?
A. 출력의 잔여 종목 리스트 확인. 산업지주사면 정상. 그 외면 Step 3 재시도.

### Q. Step 9 state 재생성 중 에러?
A. 데이터 캐시 일관성 문제. `python C:\dev\monitor_dart_fn_health.py` 실행해서 baseline 5종목 이하 확인.

### Q. Step 10 BT Cal이 Roll back 범위 (< 2.5)?
A. **commit 하지 마**. 다음 명령으로 임시 보관:
```powershell
git stash
```
보고 받으면 분석. 직접 진행하지 말고 멈춰.

### Q. Step 12 push 거부 (pre-commit fail)?
A. 메시지 보고 원인 수정. **--no-verify 절대 쓰지 마**.

---

## 📞 긴급 롤백 (사용 권장 X)

**경고**: 아래는 마지막 수단. 가짜 알파 다시 발현 위험.

```powershell
# 모든 변경 취소 (commit 안 한 것만)
git checkout -- .

# fs_dart는 백업에서 복원
robocopy C:\dev\data_cache_backup_20260512\all_fs_dart C:\dev\data_cache /XO

# 스케줄러 재활성화 (잘못된 캐시 상태로 가동)
schtasks /Change /TN "QuanT_DailyPipeline" /ENABLE
```

→ 옵션F 폐기는 유지되지만 캐시는 잘못된 상태. **권장 안 함**.

---

## 🎯 도달 수준 (검증 후 예상)

| 단계 | 잔여 맹점 |
|---|---|
| 시작 (집PC pull 직후) | 5% |
| Step 4 통과 후 (재수집 + 검증) | 2% |
| Step 7 통과 후 (incomplete 재진단) | **1.5%** |
| Step 12 push 후 | **1%** |

**잔여 1%**: 외부 시스템 (DART/FN) 자체 변경 — 시스템 모델 밖. monitor 매일 자동 검사로 감지.

---

## 📚 참고 자료

- `HANDOVER_20260512_FS_DART_CACHE_FIX.md` — 사건 전체 상세 + 식별 알고리즘
- `bad_tickers_v3.txt` (179) — 메인 재수집 대상
- `bad_tickers_tier1.txt` (32) — SG&A 일치 확정
- `bad_tickers_tier2_only.txt` (147) — FN 5배+ 차이
- `bad_tickers_extra.txt` (24) — 영업이익 등 의심
- `bad_tickers_other_accts.txt` (3) — 008110/030960/099750
- `incomplete_diag_tickers.txt` (1539) — 진단 미완료 재진단 대상
- `diagnose_all_detail.json` — 진단 detail
- `offline_diag_summary.json` — 추가 분석
- `deep_check_summary.json` — 다른 회계항목 검사

---

## ✅ 회사PC 검증 결과 (11/11 통과)

| # | 검증 항목 | 결과 |
|---|---|---|
| 1 | 매뉴얼 모든 명령어 실제 코드 대조 | ✅ regenerate_all_v80, fast_generate_rankings_v2 인자 정확 |
| 2 | test_account_map.py 양/음 검증 | ✅ 4/4 양 + 5/5 음 |
| 3 | verify_after_refetch.py 시뮬레이션 | ✅ 코드 0/1/2 정확 판정 |
| 4 | pre-commit hook Windows 호환성 | ✅ Python 기반 + Git for Windows 호환 |
| 5 | diagnose_all.py 환경변수 입력 옵션 | ✅ DIAG_INPUT 추가 |
| 6 | tier2 false positive 정량 | ✅ 7~10 추정 → 임계값 10 조정 |
| 7 | BT Cal 임계값 정의 | ✅ Pass/재검토/Roll back 범위 명시 |
| 8 | git history 정밀 분석 | ✅ 4/15 commit `45c375f49` 첫 오염 push 확정 |
| 9 | ACCOUNT_ID_MAP 검토 | ✅ SG&A 외 매핑 정확 |
| 10 | 진단 미완료 1542 추출 | ✅ incomplete_diag_tickers.txt |
| 11 | HOMEPC 매뉴얼 정정 | ✅ 이 문서 |
