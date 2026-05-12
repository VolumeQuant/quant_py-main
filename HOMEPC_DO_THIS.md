# 🏠 집PC 작업 매뉴얼 — fs_dart 캐시 정상화

**작성**: 2026-05-12 회사PC 마지막 작업
**소요 시간**: 약 60~90분 (대부분 자동, 사람 개입 최소)
**전제**: 회사PC에서 DART 병렬 호출 사고로 IP 일시 차단. 집PC IP로 진행.

---

## 📋 전체 흐름 (한눈에)

```
1. git pull                              (10초)
2. pre-commit hook 설치                    (10초)
3. python refetch_serial.py                (~16분)
4. python verify_after_refetch.py          (3분)
5. python test_account_map.py              (10초)
6. python diagnose_all.py 미완료 종목       (~15분, 선택)
7. python refetch_serial.py extra          (~3분, 선택)
8. state 재생성                            (~28분)
9. BT 검증                                 (~5분)
10. 5/11 ranking 재생성                    (~3분)
11. git commit + push                      (1분)
12. 스케줄러 재활성화                       (10초)
```

**각 단계는 이전 단계 통과 후에만 진행. 실패 시 멈추고 대응 섹션 참고.**

---

## Step 1. git pull (10초)

```powershell
cd C:\dev
git pull origin main
```

**예상 출력**: "Updating ... Fast-forward"
**실패 시**: 충돌나면 멈추고 보고해. 데이터 손실 위험.

---

## Step 2. pre-commit hook 설치 (10초)

```powershell
# git hooks는 추적 안 되니 수동 설치
Copy-Item C:\dev\hooks\pre-commit C:\dev\.git\hooks\pre-commit
# 또는 bash가 있으면: cp /c/dev/hooks/pre-commit /c/dev/.git/hooks/pre-commit
```

설치 검증:
```powershell
ls C:\dev\.git\hooks\pre-commit
# 파일 있으면 OK
```

**없어도 작업 진행 가능** (수동으로 unit test만 돌리면 됨)

---

## Step 3. 잘못된 179종목 재수집 (~16분)

```powershell
python C:\dev\refetch_serial.py
```

**조건**:
- 단일 worker, sleep 5초, ConnectionError 시 자동 60s→180s→600s 백오프
- 캐시 atomic rename (실패해도 손실 0)

**예상 출력**:
```
============================================================
재수집 — 단일 worker, sleep 5초, exponential backoff
============================================================
입력: C:/dev/bad_tickers_v3.txt
대상: 179종목 (2016-2026 11년치)
예상 시간: 약 16.4분 (호출당 0.3s + 종목당 5s)
============================================================
  [1/179] 000040: ✓ 성공 720 rows (5s)
  [2/179] 000890: ✓ 성공 680 rows (10s)
  ...
  [179/179] 402340: ✓ 성공 ...
============================================================
완료: 성공 179/179, 빈 결과 0, 실패 0
소요: 16.3분
============================================================
```

**실패 케이스**:
- `refetch_failed.txt` 생성 → 그 종목들 수동 확인
- 모두 ConnectionError 실패면 → DART 또 차단됐을 가능성. 30분 쉬고 재시도
- 일부만 실패 → `BAD_LIST=C:/dev/refetch_failed.txt python refetch_serial.py` 로 재시도

---

## Step 4. 자동 검증 (3분)

```powershell
python C:\dev\verify_after_refetch.py
```

**판정**:
- **종료 코드 0**: ✅ 정상화 완료 → Step 5 진행
- **종료 코드 1**: ⚠️ 잔여 BAD 6~20개 → 수동 검토 후 Step 5
- **종료 코드 2**: ❌ 잔여 BAD 20개+ → Step 3 재실행 또는 점검

**예상 출력 (성공)**:
```
[1] bad_tickers_v3 (179) 정상화 검사
  ✓ 정상화: 175/179
  ✗ 잔여 BAD: 4 (지주사 등 false positive 추정)
  -  FN 없음: 0

[2] 전체 fs_dart 5배+ 차이 베이스라인
  현재 big_diff: 4 (기대 ≤ 5)

[3] 영업이익 > 매출 비정상 카운트
  현재 카운트: 32 (기대 ≤ 50)

✅ 검증 통과 — 정상화 완료
```

**잔여 BAD가 있는 종목 확인 (수동)**:
- SK스퀘어(402340) 같은 산업지주사가 잔여로 남으면 진짜 BAD인지 false positive인지 직접 봐야 함
- DART API에서 직접 매출 조회 (1종목씩, 호출 1번):
```powershell
python -c "import sys; sys.path.insert(0,'C:/dev'); from dart_collector import DartCollector; from config import DART_API_KEYS; dc = DartCollector(api_key=DART_API_KEYS[0]); rep = dc.dart.finstate_all('402340', 2024, reprt_code='11013', fs_div='CFS'); print(rep[rep['account_id']=='ifrs-full_Revenue'][['account_nm','thstrm_amount']].head())"
```

---

## Step 5. 매핑 unit test (10초)

```powershell
python C:\dev\test_account_map.py
```

**예상 출력**:
```
✅ 모든 테스트 통과 (4/4)
```

**실패 시**: dart_collector.py 매핑 변경됐을 가능성. 직접 봐야 함.

---

## Step 6. 진단 미완료 1542종목 재진단 (~15분, 선택)

회사PC에서 DART silent fail로 진단 안 된 종목들. 집PC IP로 재진단.

```powershell
# 환경변수로 입력 파일 지정 — diagnose_all.py가 incomplete 사용
$env:DIAG_INPUT = "C:\dev\incomplete_diag_tickers.txt"
python C:\dev\diagnose_all.py
```

**중요**: `diagnose_all.py`는 현재 전종목 (1954)을 검사하도록 하드코딩됨. 시간 단축 위해 incomplete만 검사하려면 임시 수정 또는 스킵.

**선택 가능**:
- (A) 그냥 스킵 (현재 bad_tickers_v3 179종목으로 충분 가능성)
- (B) 전종목 재진단 (~50분, DART 호출 ~15000건 = 한도 안전)

**기대 결과**: 추가 BAD 종목 발견되면 `bad_tickers_v4.txt` 같은 새 리스트 생성 → Step 3 반복

---

## Step 7. extra 24종목 + other_accts 3종목 재수집 (~3분, 선택)

```powershell
$env:BAD_LIST = "C:\dev\bad_tickers_extra.txt"
python C:\dev\refetch_serial.py

# 또는 합쳐서
# 메모장으로 bad_tickers_extra.txt + bad_tickers_other_accts.txt 합쳐서 새 파일 만든 후 재실행
```

---

## Step 8. state 7.8년 재생성 (~28분)

```powershell
# 환경변수 (v80 기본 파라미터)
$env:FACTOR_V_W = "0.15"
$env:FACTOR_Q_W = "0.00"
$env:FACTOR_G_W = "0.55"
$env:FACTOR_M_W = "0.30"
$env:G_SUB1 = "rev_z"
$env:G_SUB2 = "oca_z"
$env:G_REVENUE_WEIGHT = "0.6"
$env:MOM_PERIOD = "12m"

# state/ 1294일 + state/defense/ 1294일 재생성
python C:\dev\run_daily.py --full
# 또는 backtest의 state 재생성 스크립트 (이름 확인 필요)
```

**예상 시간**: 2워커 병렬 ~28분

---

## Step 9. BT 검증 (~5분)

```powershell
# 7.8년 BT
python C:\dev\backtest\fast_run_bt.py --start 2018-07-01 --end 2026-04-30 --tier all

# 5.25년 BT  
python C:\dev\backtest\fast_run_bt.py --start 2021-01-01 --end 2026-04-30 --tier all
```

**기대 결과 (v80 baseline)**:
| BT 구간 | Cal | CAGR | MDD |
|---|---|---|---|
| 7.8년 | **3.97** 근처 | ~121% | ~38% |
| 5.25년 | **4.71** 근처 | ~105% | ~33% |

**Cal이 baseline보다 0.5+ 이탈** → 재수집 데이터에 문제 가능성. 조사 필요.

---

## Step 10. 5/11 ranking 재생성 (~3분)

```powershell
# data_cache 최신 상태로 5/11 ranking 다시 만들기
$env:BASE_DATE = "20260511"
python C:\dev\backtest\fast_generate_rankings_v2.py
```

**확인할 것**:
- Top 20에서 KBI메탈(024840), 링네트(042500), 우원개발(046940), 전진건설로봇(072950), SK스퀘어(402340) 등이 빠졌는지
- 우원개발은 진짜 영업이익 폭증으로 일부 유지 가능

비교용 기존 파일: `state/ranking_20260511.json` (옛 가짜 알파 포함)

---

## Step 11. git commit + push (1분)

```powershell
cd C:\dev
git status

# 핵심 변경분만 stage
git add HANDOVER_20260512_FS_DART_CACHE_FIX.md HOMEPC_DO_THIS.md
git add dart_collector.py refetch_serial.py refetch_parallel.py
git add backtest/fast_generate_rankings_v2.py
git add monitor_dart_fn_health.py run_daily.py
git add test_account_map.py verify_after_refetch.py
git add hooks/pre-commit
git add bad_tickers_*.txt incomplete_diag_tickers.txt
git add diagnose_all.py deeper_diagnose_offline.py deep_check_other_accts.py
git add diagnose_all_detail.json offline_diag_summary.json deep_check_summary.json
git add merge_bad_lists.py check_other_accounts.py

# 재수집된 179+ 종목 파일도 (Step 3 성공 후)
git add data_cache/fs_dart_*.parquet

# state 재생성 결과 (Step 8 성공 후)
git add state/

# 커밋 (pre-commit hook 자동 실행 — 매핑 검사 + 캐시 무결성)
git commit -m "fix(data): fs_dart 캐시 무결성 사건 — 179종목 재수집 + 옵션F 폐기 + 7개 자동 방어막"

# 푸시
git push origin main
```

**pre-commit hook이 차단하면** → 출력 메시지 보고 수정. unit test 실패면 dart_collector.py 점검.

---

## Step 12. 스케줄러 재활성화 (10초)

```powershell
schtasks /Change /TN "QuanT_DailyPipeline" /ENABLE

# 확인
schtasks /Query /TN "QuanT_DailyPipeline" /FO LIST | findstr "상태 Status"
# "Ready" 또는 "준비" 나오면 OK
```

**완료!** 🎉

---

## 🆘 문제 발생 시

### Q. Step 3에서 ConnectionError 계속 나면?
A. 30분~1시간 쉬고 재시도. 집PC IP도 짧게 막혔을 수 있음.

### Q. Step 4 검증에서 잔여 BAD 6~20개 (코드 1)?
A. 일단 Step 5~10 진행. 잔여는 추후 처리. 산업지주사 false positive 가능성 높음.

### Q. Step 8 state 재생성 중 에러?
A. 데이터 캐시 일관성 문제. `python C:\dev\monitor_dart_fn_health.py` 다시 돌려서 확인.

### Q. Step 9 BT Cal이 baseline에서 크게 이탈?
A. 재수집된 데이터에 문제. **commit 하지 마**. `git stash` 후 보고.

### Q. Step 11 push 거부 (pre-commit fail)?
A. 메시지 보고 원인 수정. **--no-verify 절대 쓰지 마**.

---

## 📞 긴급 롤백

만약 작업 중 시스템 정상 가동이 더 우선이면:

```powershell
# 모든 변경 취소 (commit 안 한 것만)
git checkout -- .
git clean -fd data_cache/

# 백업에서 fs_dart 복원
Copy-Item -Recurse -Force C:\dev\data_cache_backup_20260512\all_fs_dart\* C:\dev\data_cache\

# 스케줄러 재활성화 (잘못된 캐시 그대로지만 일단 가동)
schtasks /Change /TN "QuanT_DailyPipeline" /ENABLE
```

→ 옵션F + 잘못된 캐시 상태로 다시 가동됨. **권장 안 함** (가짜 알파 다시 발생). 진짜 응급 시에만.

---

## 🎯 도달 수준 (예상)

| 단계 | 잔여 맹점 |
|---|---|
| 시작 (집PC pull 직후) | 5% |
| Step 4 통과 후 | 2% |
| Step 11 push 후 | **1%** |

100%는 외부 시스템 (DART/FN) 의존이라 불가능. 99% 도달이 목표.

---

## 📚 참고 문서

- `HANDOVER_20260512_FS_DART_CACHE_FIX.md` — 사건 전체 상세 + 식별 알고리즘
- `MEMORY.md` — 영구 기록 (다음 세션이 받는 컨텍스트)
- 회사PC 사고 기록 + 자동 방어막 명단 모두 HANDOVER에 있음
