# 매일 시스템 건강 체크리스트 (사고 후, 2026-05-12~)

**목적**: 5/15 1Q 폭주 + 미래 매핑 사고 재발 방지를 위한 매일 수동 점검 체크리스트.
**대상**: 자동화 + 사용자 즉시 점검 백업.
**소요**: 약 3분.

---

## 매일 16시 자동 스케줄러 후 (예상 16:30~17:00)

### 1. 텔레그램 메시지 확인 (Signal + Watchlist)
- ✅ Top 5 종목 비정상 없음 (KBI메탈/링네트 같은 4연상한 추격 매수 아님)
- ✅ 종목 수 ≥ 320 (B 검증 게이트 통과)
- ✅ 이격도20 > 1.5 차단 종목 없음 (또는 적정 수)

### 2. 개인봇 알림 확인
- ✅ "⚠️ 캐시 무결성 의심" 메시지 없음
- ✅ "⚠️ ranking 검증 미달" 메시지 없음
- ❌ 위 알림 있으면: §4 즉시 점검 절차

### 3. logs/ 디렉토리 (선택)
- `logs/run_daily_YYYYMMDD.log` 최근 로그 마지막 50줄
- `[health]` 항목별 정상 범위
- ConnectionError 폭주 없음

---

## 매주 일요일 (주간 점검)

### 4. monitor 단독 실행
```powershell
python monitor_dart_fn_health.py
```
- 매출 5배+ 차이 종목 ≤ 5
- 영업이익 부호 다름 ≤ 3
- 정정 row ≤ 4000, 종목 ≤ 1500

### 5. fs_div 추적 가능 범위 확인
```powershell
python -c "import glob, pandas as pd; t=0; w=0
for fp in glob.glob('data_cache/fs_dart_*.parquet'):
    if 'backup' in fp: continue
    try: d=pd.read_parquet(fp,columns=None); t+=1
    except: continue
    if 'fs_div' in d.columns: w+=1
print(f'{w}/{t} ({w/t*100:.1f}%) fs_div 추적 가능')"
```
- 5/12 시작 약 4.7% → 1Q 폭주 후 갱신 종목들 점진 증가 예상

---

## 분기 마감 시기 (5/15, 8/15, 11/15) 집중 점검

### 6. D-1 (5/14, 8/14, 11/14)
- ✅ run_daily 정상 실행
- ✅ monitor baseline 측정
- ✅ ranking 종목 수/품질 평소 수준

### 7. D (5/15, 8/15, 11/15) — 마감일 당일
- ✅ DART 신규 분기 보고서 폭주 → run_daily ConnectionError 가능
  - run_daily.py timeout 3시간 (2026-05-08 변경)
  - 실패 시 다음날 정상 자동 재시도
- ✅ 새 1Q/3Q 매출 데이터 monitor 검사 (영업이익 부호 등)

### 8. D+1 ~ D+5 (5/16~5/20)
- ✅ 매일 monitor + 개인봇 알림 확인
- ✅ 새 BAD 종목 5+ 등장 시 즉시 진단:
  - `python verify_after_refetch.py` 실행
  - `bad_tickers_recent.txt` 생성 후 `refetch_serial.py` 추가 재수집

---

## §4 사고 즉시 점검 절차 (개인봇 알림 발생 시)

### 4-1. 무엇이 잘못됐나
```powershell
# monitor 상세 결과
python monitor_dart_fn_health.py
```
- 매출/영업이익 어떤 항목에서 문제?
- 표본 종목 식별

### 4-2. 매핑 사고인가, 일시적 DART 응답 이상인가
```powershell
# 표본 종목 1-2개 정밀 검사
python -c "import pandas as pd
d = pd.read_parquet('data_cache/fs_dart_{TICKER}.parquet')
fn = pd.read_parquet('data_cache/fs_fnguide_{TICKER}.parquet')
# y 매출/영업이익/당기순이익 DART vs FN 비교
..."
```

### 4-3. 매핑 사고 확정 시 즉시 조치
1. **dart_collector.py 매핑 점검**: `test_account_map.py` 실행
2. **bad 종목 식별 + 재수집**: `bad_tickers_recent.txt` 생성 → `refetch_serial.py`
3. **재수집 후 verify**: `python verify_after_refetch.py`
4. **state 부분 재생성** (선택, 큰 영향 시): 해당 날짜 ranking만 단독 재생성

### 4-4. 채널 발송 보류
- 의심이 강할 때: `schtasks /Change /TN "QuanT_DailyPipeline" /DISABLE`
- 점검 후 재활성화: `/ENABLE`

---

## §5 참고 자료

- `HANDOVER_20260512_FS_DART_CACHE_FIX.md` — 사건 인계 문서
- `HOMEPC_DO_THIS.md` — 13단계 매뉴얼
- `ROLLBACK_PLAN_20260512.md` — BT Cal < 2.5 시 대응
- `monitor_dart_fn_health.py` — 무결성 자동 검사
- `MEMORY_UPDATE_20260512_OPTION_F_INCIDENT.md` — 메모리 동기화
