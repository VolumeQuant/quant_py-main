# fs_dart 캐시 무결성 사건 — 인계 문서

작성: 2026-05-12 (이전 세션, 컨텍스트 오염으로 종료)
다음 작업자: 새 Claude Code 세션

---

## 1줄 요약

**fs_dart 캐시 파일들 중 일부 종목(추정 1000개+)이 실제 DART API 값의 1/10~1/63 크기로 잘못 저장돼 있고, 옵션F가 이 잘못된 캐시 일부만 정정해서 가짜 YoY 알파를 만들어 링네트(042500) 등을 Top 20에 진입시킴.**

---

## 핵심 발견 (증거)

### 표본 종목 검증 결과 (DART API 직접 호출 vs 우리 캐시)

| 종목 | DART CFS API 24Q1 매출 | fs_dart 캐시 값 | 차이 | 판정 |
|---|---|---|---|---|
| 042500 링네트 | 373.8억 | 33.0억 | 11.3배 | 잘못 |
| 024840 KBI메탈 | 1,839.3억 | 29.1억 | 63.2배 | 잘못 |
| 046940 우원개발 | 655.9억 | 36.2억 | 18.1배 | 잘못 |
| 072950 전진건설로봇 | 153.8억 | 14.8억 | 10.4배 | 잘못 |
| 000660 SK하이닉스 | 124,296억 | 124,296억 | 1.0 | 정상 |
| 088130 동아엘텍 | 339.4억 | 339.4억 | 1.0 | 정상 |
| 196170 알테오젠 | 349.0억 | 349.0억 | 1.0 | 정상 |
| 207940 삼성바이오 | 9,469억 | 9,469억 | 1.0 | 정상 |

### git history도 잘못된 값

- commit `45c375f49` (4/15 v79+PIT) 시점의 fs_dart_042500.parquet도 33-41억 (잘못)
- 즉 **처음부터 잘못된 채로 commit + push됨**
- 다른 PC에 git pull해도 같은 잘못된 캐시
- → DART API 재호출 외 방법 없음

### dart_collector.py 코드 자체는 정상

- 현재 dart_collector.py로 호출하면 DART API 정상값 반환
- 따라서 코드 fix가 아니라 **데이터 재수집**이 필요

---

## 사건 트리거 — 옵션F 사이드이펙트

5/12 새벽 도입된 옵션F (commit `97a80bc03`) `fix_dart_account_mismatch` 함수:

```
KBI메탈 25Q1 매출:
  - DART 캐시: 28.7억 (잘못)
  - FN: 1844억 (정상 연결)
  - ratio 0.016 → mismatch → DART row 제거 → FN 1844억 보충

KBI메탈 24Q1 매출:
  - DART 캐시: 29.1억 (잘못)
  - FN: 데이터 없음 → 정정 안 됨, 별도 매출 추정값 그대로 유지

시스템이 본 YoY 매출 성장:
  25Q1 / 24Q1 = 1844 / 29.1 = 63배 → 가짜 강한 알파 → cr 1위
```

옵션F 도입 전 (`check_data_mismatch`): mismatch 1건이라도 있으면 DART 전체 폐기 → FN만 사용 → FN에 24년 데이터 없으니 KBI메탈 시스템에서 자동 제외 (가짜 알파 발생 안 함).

**즉 옵션F가 잘못된 캐시 문제를 가짜 알파로 노출시킨 셈.** 옵션F 자체는 5/4 SG&A 매핑 버그 같은 일시적 오류 정정엔 효과 있었지만, 광범위한 캐시 무결성 위반 종목에서 가짜 알파를 만듦.

---

## 시도한 작업 (작업 완료/중단 모두)

### 완료
1. ✓ **dart_collector.py 점검** — 코드 자체 정상 확인
2. ✓ **dart_collector.py에 `fs_div` 컬럼 추가** — fs_dart에 CFS/OFS 표시 (지금 당장 진단 가능). 분기별 CFS→OFS 폴백 로직은 그대로 유지
3. ✓ **fs_dart 전체 백업** — `C:/dev/data_cache_backup_20260512/all_fs_dart/` (2613개)
4. ✓ **표본 8종목 재수집** — 4개 잘못 + 4개 정상 확인 (현재 fs_dart에 정상값 들어가 있음)
5. ✓ **표본 ranking 5/11 재생성** — 링네트 13→78, KBI메탈 1→39, 우원개발 2→7, 전진건설로봇 11→51로 가짜 알파 차단 확인
6. ✓ **QuanT_DailyPipeline 스케줄러 비활성화** — 잘못된 캐시 상태로 자동 ranking 생성 방지

### 시도했으나 폐기/롤백
1. **옵션F Part 2 (시계열 검증) 강화 코드** — `fast_generate_rankings_v2.py`에서 폐기 완료. 사용자 지적: 임시 해결책 안 됨, 근본 원인은 데이터 자체.
2. **잘못된 종목 식별 (`identify_bad_cache.py`)** — 표본 검증 실패 (4개 false negative + 1개 false positive). 식별 로직 부정확. 신뢰 X.
3. **백그라운드 재수집** — 1005종목 직렬 → 30분에 12종목만 진행 (느림). 중단. 트리플 키 + 3병렬 스크립트 (`refetch_parallel.py`)는 작성됐으나 미실행.

### 중단됨
- 재수집 (계획만, 실행 보류) — 식별 정확도 문제로 진단부터 다시 해야 함

---

## 현재 시스템 상태 (작업 중단 시점)

| 항목 | 상태 |
|---|---|
| `data_cache/fs_dart_*.parquet` | 표본 8종목만 새 데이터 (정상), 나머지 2605종목 기존 캐시 (일부 잘못) |
| `data_cache_backup_20260512/all_fs_dart/` | 5/12 오후 작업 직전 전체 백업 (표본 4종목은 이미 정상 재수집 후 상태) |
| `data_cache_backup_20260512/fs_dart_*.parquet` | 표본 8종목만 백업 (옵션F 적용 후, 표본 재수집 전 — 진짜 잘못된 상태) |
| `dart_collector.py` | `fs_div` 컬럼 저장 추가 됨. 분기별 CFS→OFS 폴백 로직 그대로 유지 |
| `backtest/fast_generate_rankings_v2.py` | 옵션F Part 1 그대로, Part 2 폐기됨 |
| `state/` | 옛 데이터 기반 ranking 그대로 (잘못된 캐시 영향 받은 상태) |
| `state_sample/ranking_20260511.json` | 표본 4종목 재수집 + Part 2 폐기 후 ranking (참고용) |
| QuanT_DailyPipeline 스케줄러 | **비활성화** (작업 완료 후 재활성화 필요) |

---

## 다음 세션이 해야 할 작업 (구체적)

### Step 1. 진단 (모든 종목, DART API 1회씩)

목표: 어떤 종목이 진짜 잘못된 캐시인지 확실히 식별.

**방법**:
```python
# 각 종목에 대해 DART API에서 25Q1 매출 1건만 가져오기
# fs_dart 캐시의 25Q1 매출과 비교
# 5배+ 차이 또는 캐시에 25Q1 자체가 없으면 → 재수집 대상
```

- 호출 수: 2613종목 × 1 = 2613건 (트리플 키 한도 59,700 안전)
- 시간: 트리플 키 3병렬로 ~5분
- 출력: 진짜 잘못된 종목 리스트 → `bad_cache_tickers_verified.txt`

**주의**:
- 표본 백업(`data_cache_backup_20260512/fs_dart_*.parquet`)으로 식별 알고리즘 사전 검증 필수. 표본 4개 (042500/024840/046940/072950) 모두 식별, 정상 4개 (000660/088130/196170/207940) 미식별 — 100% 정확해야 진행.

### Step 2. 재수집 (Step 1에서 식별된 종목만)

- `refetch_parallel.py` 활용 (이미 작성됨, 트리플 키 + 3병렬)
- 수집 범위: 2016-2026년 (BT 7.8년 2018-07~2026-04 커버하려면 2017년 데이터 필요, 안전 마진 2016년부터)
- 종목당 ~13초, 1000종목 / 3워커 = ~75분

**API 한도 체크**:
- 1000종목 × 11년 × 평균 6호출 = 66,000건 → 트리플 키 한도 59,700 초과 가능
- **해결**: CFS만 호출하고 OFS 폴백은 응답 없을 때만 (현재 dart_collector 로직). 또는 분할 (오늘 500, 내일 500)

### Step 3. 옵션F 폐기 + check_data_mismatch 복원

캐시가 정확해지면 mismatch 정정 자체가 거의 필요 없음.

```python
# backtest/fast_generate_rankings_v2.py line 837-848:
# 옵션F 호출 제거. check_data_mismatch만 사용:

for ticker in all_tickers:
    if ticker in dart_map:
        if ticker in fn_map and check_data_mismatch(dart_map[ticker], fn_map[ticker]):
            data['fs'][ticker] = fn_map[ticker]
            ...
```

`fix_dart_account_mismatch` 함수 자체는 삭제 권장 (Part 1만 남아있어도 미래 사고 원인이 될 수 있음).

### Step 4. state 7.8년 재생성

- `state/` 1294일 × 2tier (boost + defense) 전체 재생성
- 2워커 병렬 ~28분
- 환경변수: `FACTOR_V_W=0.15 FACTOR_Q_W=0.00 FACTOR_G_W=0.55 FACTOR_M_W=0.30 G_SUB1=rev_z G_SUB2=oca_z G_REVENUE_WEIGHT=0.6 MOM_PERIOD=12m` (v80 기본)

### Step 5. BT 검증

- 7.8년 (2018-07~2026-04) BT 실행
- Cal/CAGR/MDD가 v80 baseline (Cal 3.97, MDD 38%) 근처인지 확인
- 옵션F+섹터필터 BT (Cal 4.29, MDD 36%)와 비교 — 옵션F 효과(+0.61)가 가짜 알파였다면 baseline에 가까워야

### Step 6. 5/11 ranking 정확성 검증

- 5/11 ranking 재생성
- Top 20에 가짜 알파 종목 (링네트/KBI메탈/우원개발/전진건설로봇) 없어야
- 우원개발은 진짜 영업이익 폭증 알파라 Top 10 유지 가능 (사용자 확인된 사항)

### Step 7. 모니터링 강화

- `monitor_dart_fn_health.py`에 fs_div 컬럼 활용:
  - 한 종목에서 CFS와 OFS row 혼재 검출
  - DART 매출 vs FN 매출 5배+ 차이 자동 알람
- run_daily.py B 검증/재시도 안전망 유지

### Step 8. 커밋 + 푸시 + 스케줄러 재활성화

- 변경 파일: `dart_collector.py`, `fast_generate_rankings_v2.py`, `data_cache/fs_dart_*.parquet` (잘못된 종목들), `state/` (전체), `CLAUDE.md`, `MEMORY.md`
- 커밋 메시지 예: `fix(data): fs_dart 캐시 무결성 사건 — 1000+ 종목 재수집 + 옵션F 폐기`
- 스케줄러 재활성화: `schtasks /Change /TN "QuanT_DailyPipeline" /ENABLE`

---

## 맹점 / 주의사항

1. **표본 검증 필수**
   첫 식별 시도가 표본 5개 모두 틀림. 다음 세션은 식별 로직 작성 후 표본 8개에서 100% 정확도 확인 후 전체 진행.

2. **옵션F (`fix_dart_account_mismatch`)는 정상 동작이 아님**
   "DART와 FN이 다르면 FN으로 정정" 원칙이 같은 종목 내 24년 별도 + 25년 연결을 섞어버림. 폐기 필수.

3. **시계열 점프 검증 (Part 2) 폐기 사유**
   동아엘텍(088130) 같은 진짜 매출 폭증 종목과 링네트(042500) 같은 별도/연결 변경 케이스를 100% 구별 불가. CV 기반 휴리스틱은 false positive 위험. 데이터 자체를 정정하는 게 정공법.

4. **dart_collector의 분기별 CFS→OFS 폴백**
   같은 종목 내 24년 OFS + 25년 CFS 섞임 가능성은 이론적으로 존재. 표본 검증 결과 4종목 모두 일관 CFS 사용 — 큰 문제 아닌 듯. 종목 단위 fs_div 일관성 로직은 한 번 시도했다가 데이터 누락 발생 (이전 세션) → 롤백. 향후 시도 시 신중.

5. **API 한도 관리**
   트리플 키 일일 한도 59,700건. 1000종목 전체 11년치 재수집은 한도 초과 위험. CFS 우선 + 분할 수집 고려.

6. **5/4 SG&A 매핑 버그 (commit 0e082d1cc)**
   `dart_TotalSellingGeneralAdministrativeExpenses` → `매출액` 매핑 제거 완료. 옵션F 없이도 매핑 자체 정확. 향후 매핑 추가 시 회계 검증 절차 (CLAUDE.md 기록).

7. **우원개발 (046940)**
   매출은 1/18 잘못이었지만 영업이익 폭증은 진짜 (사용자가 별도 검증). 재수집 후 정확한 매출 + 진짜 영업이익으로 ranking 평가하면 cr 7위 정도 (정상 알파).

8. **표본 4종목 현재 fs_dart**
   이미 재수집된 정상값. Step 2에서 다시 재수집해도 동일값. 중복 작업 OK.

---

## 참고 자료

- 표본 백업 (옵션F 적용 직후, 표본 재수집 전): `C:/dev/data_cache_backup_20260512/fs_dart_*.parquet` (8개)
- 전체 백업 (5/12 오후 작업 직전): `C:/dev/data_cache_backup_20260512/all_fs_dart/` (2613개, 표본 4개는 정상)
- 표본 재수집 후 5/11 ranking: `C:/dev/state_sample/ranking_20260511.json`
- 식별 스크립트 (검증 실패): `C:/dev/identify_bad_cache.py`
- 재수집 스크립트 (미실행): `C:/dev/refetch_parallel.py`
- 잘못된 종목 리스트 (부정확): `C:/dev/bad_cache_tickers.txt` (1140종목, 검증 실패 → 무시)
- 우선순위 종목 리스트 (부정확): `C:/dev/bad_cache_priority.txt` (43종목, 검증 실패 → 무시)

---

## 의문점 (다음 세션이 조사하면 좋을 것)

1. **언제/어떻게 fs_dart에 1/10 값이 들어갔나?**
   git history `45c375f49` (4/15)에 이미 잘못된 값. 그 이전 commit은? `bac584104` (7.8년 데이터 확장) 시점에 처음 들어갔을 가능성. 1/10이라는 패턴이 일관적이지 않음 (링네트 11배, KBI메탈 63배, 우원개발 18배, 전진건설로봇 10배) — 단일 매핑 오류가 아닌 다른 원인일 가능성.

2. **어떤 account_id에서 33억 값이 왔는가?**
   링네트 24Q1 DART CFS에서 `ifrs-full_Revenue`는 373.8억. 33억은 어떤 row에서 왔는지 추적하면 과거 매핑 버그 정체 알 수 있음.

3. **시스템 작동 시 dart_collector가 어떤 시기에 실행됐는가?**
   `dart_collector.py` 호출 이력 (run_daily.py의 refresh_dart_cache 단계). 잘못된 캐시가 들어간 시점 + 그때 코드 상태 확인.

4. **다른 회계 항목 (영업이익/자산/CF) 도 잘못된 종목이 있는가?**
   매출만 진단했음. 자산/영업이익 등도 1/10 차이 가능성. Step 1 진단을 다항목 확장 고려.
