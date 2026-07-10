# Roll Back 대응 시나리오 (Step 10 BT Cal < 2.5 발생 시)

**작성**: 2026-05-12 (집 PC, Step 3 진행 중)
**적용 시점**: `step3_to_step11_auto.py` 실행 후 Step 10 BT 결과 확인 시

---

## 트리거 조건

| BT 결과 | 판정 | 대응 |
|---|---|---|
| Cal ≥ 3.5 (7.8y) | ✅ Pass | Step 11~13 진행 (정상 흐름) |
| 2.5 ≤ Cal < 3.5 | ⚠️ 재검토 | 본 문서 §1 진단 절차 |
| **Cal < 2.5** | ❌ **Roll back** | 본 문서 §2 복구 절차 |

매뉴얼 baseline: 7.8y Cal 3.97, 5.25y Cal 4.71.

---

## §1 재검토 (2.5 ≤ Cal < 3.5)

### 진단 1: 가짜 알파 제거 효과
- 옵션F 시대 BT (가짜 알파 포함): Cal 4.288
- 옵션F 제거 후 BT: Cal 3.727~3.97 (정상 범위)
- → Cal 3.0~3.5는 **가짜 알파 제거의 정상 효과**일 수 있음. 정확한 알파 = 더 낮음.

### 진단 2: 비교 baseline
```bash
python backtest/compare_optf_bt.py
```
- 옛 state (가짜 알파 포함) Cal vs 새 state (정정) Cal 비교
- 차이가 작으면 Roll back X, 차이 크면 §2

### 판단 기준
- Cal 3.0~3.5: **수용**. 가짜 알파 제거로 진짜 알파만 남은 상태.
- Cal 2.5~3.0: 추가 분석 필요 (Walk-Forward 구간별 확인)

---

## §2 Roll back 절차 (Cal < 2.5)

### Step R1: 즉시 commit 차단 + 상태 보존
```powershell
# 변경 모두 stash (아직 commit 안 함)
git stash push -u -m "rollback-pending-bt-fail"

# 백업 state 복원 (옵션F 이전 상태)
robocopy state_backup_pre_optf_20260512 state /MIR
```

### Step R2: 원인 진단
```bash
# 5/11 ranking 비교 — 어떤 종목이 사라졌나
python -c "
import json
with open('state/ranking_20260511.json') as f: o=json.load(f)['rankings']
with open('state_verify/ranking_20260511.json') as f: n=json.load(f)['rankings']
o_set = set(r['ticker'] for r in o[:30])
n_set = set(r['ticker'] for r in n[:30])
print('사라진 종목:', sorted(o_set - n_set))
print('새 진입:', sorted(n_set - o_set))
"
```

- 사라진 종목이 가짜 알파 (KBI메탈/SK스퀘어 등): **정상 — Roll back 부당**
- 사라진 종목이 정상 우량주: **데이터 손상 의심 — Roll back 정당**

### Step R3: 부분 복구 (선택)
**옵션 A**: 매핑 패치만 유지 + 데이터는 옛 백업 사용
- 5/15 폭주 시 새 데이터는 정정된 매핑으로 들어옴 (안전)
- 과거 BT는 옛 데이터 (가짜 알파 잔존, 그러나 검증 안 함)

**옵션 B**: 완전 Roll back
- `dart_collector.py` 매핑 변경 + 옵션F 폐기는 유지
- 단 fs_dart 캐시는 옛 백업
- 5/15 폭주 후 monitor가 자동 정정

### Step R4: 사용자 보고
```
개인봇 알림:
"❌ BT Cal {value} < 2.5 — Roll back 진행.
state 백업 복원 완료. 5/15까지 monitor 자동 점검."
```

---

## §3 Roll back 안 한 경우 (Cal ≥ 2.5)

### 정상 흐름: Step 11~13 자동 진행
- Step 11: 5/11 ranking state_verify에 단독 생성 + 비교
- Step 12: commit + push (사용자 확인 후)
- Step 13: 스케줄러 재활성화

### 발송 전 안전망 (B 검증 게이트)
- run_daily.py 매일 16시: ranking <320 시 채널 차단 + 30분 재시도
- monitor 매일: 매출 5배+ 차이 종목 > 5 시 개인봇 알림
- 영업이익 부호 다름 > 3 시 개인봇 알림 (2026-05-12 추가)

---

## §4 향후 재발 방지

1. **dart_collector.py 매핑 변경 시**: pre-commit hook + test_account_map.py 통과 필수
2. **fs_dart 캐시 변경 시**: pre-commit hook이 무결성 검사
3. **monitor 매일 자동 실행**: run_daily Step 0.2
4. **fs_div 저장 (사후 추가)**: 매핑 사고 발생 시 데이터 출처 추적 가능
