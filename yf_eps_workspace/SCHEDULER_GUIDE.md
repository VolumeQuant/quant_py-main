# ⚠️ [DEPRECATED] 이 가이드는 폐기됨 (2026-06-01)

**대체**: `.github/workflows/kr_eps_daily.yml` (GHA cron, 매일 KST 08:00 자동 실행)
- Windows Task Scheduler 로컬 의존 = 사용자 PC 종속 = 5/14~5/31 17일 멈춤 사고 원인
- GHA 클라우드로 이전, PC 상태와 무관하게 자동

상세: `yf_eps_workspace/README.md`

---

# (구) KR yf daily probe — Scheduler 가이드

## 1. 수동 실행

```powershell
C:\Users\user\miniconda3\envs\volumequant\python.exe C:\dev\yf_eps_workspace\code\daily_probe.py
```

특정 날짜:
```powershell
... daily_probe.py --date 20260514
```

## 2. Windows Task Scheduler 등록 (권장)

### GUI로 등록

1. `Win + R` → `taskschd.msc`
2. 작업 만들기 → 일반: 이름 `KR_YF_DailyProbe`, "사용자가 로그온할 때만 실행" 또는 "로그온 여부 관계없이 실행"
3. 트리거: 매일 (장 시작 전, 권장 08:00)
4. 동작: 프로그램 시작 → `C:\dev\yf_eps_workspace\code\run_daily_probe.bat`
5. 설정: "이미 실행 중이면 새 인스턴스 시작 안 함"

### CMD로 등록 (관리자 권한)

```cmd
schtasks /create /tn "KR_YF_DailyProbe" ^
  /tr "C:\dev\yf_eps_workspace\code\run_daily_probe.bat" ^
  /sc daily /st 08:00 /f
```

### 작업 확인

```cmd
schtasks /query /tn "KR_YF_DailyProbe"
```

### 작업 삭제

```cmd
schtasks /delete /tn "KR_YF_DailyProbe" /f
```

## 3. 로그 확인

- 매일 로그: `C:\dev\yf_eps_workspace\logs\daily\run_YYYYMMDD.log`
- 데이터: `C:\dev\yf_eps_workspace\data_cache_yf\kr_yf_YYYYMMDD.parquet`

## 4. 60일 누적 후 BT

목표 시점: 약 2026-07-13 (60 거래일)

BT 진행 시:
1. `data_cache_yf/` 60개 parquet 시계열로 통합
2. v80.6 5/14~7/13 production ranking과 매핑
3. NTM 모멘텀 점수 vs v80.6 composite 가중 합 (α 격자)
4. paired BT (v80.6 단독 vs v80.6 + 보조 신호)

## 5. 비용

- 종목당 평균 0.5초 × 1527종목 / 3 worker ≈ **10분/일**
- 일 1회만 실행 (장 시작 전), 충돌 없음
- production `QuanT_DailyPipeline` (16:00) 과 시간 분리

## 6. 안전성

- production data_cache, state, 코드 모두 무관 (격리 워크스페이스)
- yf 호출만 (DART/pykrx 0)
- 실패해도 production 영향 0
