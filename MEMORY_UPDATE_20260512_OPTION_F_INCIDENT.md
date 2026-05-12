# 메모리 업데이트 — 옵션F 사고 (2026-05-12)

**용도**: Claude Code 메모리 시스템(`%USERPROFILE%\.claude\projects\C--dev-claude-code-quant-py-main\memory\`)에 추가할 내용. 회사 PC에서 pull 후 메모리 디렉토리에 복사하거나, 사용자가 Claude에게 "이 파일 읽고 메모리에 반영해"라고 요청하면 자동 처리 가능.

**컨텍스트**: 5/12 새벽 옵션F 도입 → 가짜 알파 사고 → 회사 PC에서 폐기 + 캐시 재수집 본질 해결. 같은 실수 반복 방지 위해 메모리 정리.

---

## 1) 신규 feedback 5개

### feedback_no_surface_fix_on_corrupted_data.md

```yaml
---
name: 손상된 데이터에 표면 정정 금지 — 재수집이 정공법
description: 데이터 오염 시 항목별 자동 정정은 표면 가림으로 더 위험. 재수집/재구축이 본질 해결.
type: feedback
---
```

데이터 캐시가 오염되었을 때 "항목별 mismatch row만 제거 + 보충" 같은 표면 정정 도구를 만들지 마라. 오염 데이터와 정상 데이터를 섞어 **가짜 알파**를 생성할 수 있다.

**Why**: 2026-05-12 옵션F 사고. fs_dart 캐시가 4/4 SG&A 매핑 버그로 일부 row 오염된 상태에서, `fix_dart_account_mismatch` 함수가 mismatch row만 제거하니까:
- 같은 종목의 **24년 오염 매출(SG&A 값, 작음) + 25년 FN 정상 매출(큼)**이 섞임
- 결과: **가짜 YoY 알파** (매출 폭증 환상)
- KBI메탈 cr 1위 같은 4연상한 추격 매수 위험 종목이 ranking 진입
- BT Cal 3.68 → 4.288 향상도 **가짜 알파에 의한 인플레** (실제 성과 X)

**How to apply**:
- 사용자가 "본질 해결" 강조하면 가장 깊은 원인까지 추적. 데이터 오염 = **캐시 재수집/재구축이 정공법**.
- 항목별/시점별 자동 정정 도구 제안 전에 다음 시나리오 시뮬레이션:
  - 같은 종목 다른 시점 데이터가 섞일 수 있나? → 시간축 정합성 깨짐
  - 임계값 안에 있는 오염은 검출 안 됨 → 부분 오염이 정상으로 위장
- 오염 패턴이 일부 row에 있고 보충 데이터(FN)가 다른 시점에서 정상이면, **섞임 = 가짜 패턴 생성**. 정정보다 격리(전체 폐기 또는 재수집).
- 검출 가능한 mismatch는 광범위 폐기 (기존 `check_data_mismatch` 같은 보수적 접근)가 더 안전. 정밀 정정은 캐시가 깨끗하다는 가정 하에서만.

---

### feedback_suspect_large_bt_gains.md

```yaml
---
name: 데이터 변경만으로 큰 BT 개선 = 가짜 알파 의심부터
description: 코드/규칙 변경 없이 데이터만 정정해서 BT Calmar +0.5 이상 향상 시 가짜 알파 가능성 우선 점검.
type: feedback
---
```

데이터 정정/필터 추가 같은 변경만으로 BT Calmar가 큰 폭(>+0.5 또는 >15%)으로 향상되면 데이터 정확성 향상이 아니라 **가짜 알파 가능성**을 우선 의심하라.

**Why**: 2026-05-12 옵션F 도입 후 BT Cal 3.679 → 4.288 (+0.609, +16.5%) 향상됨. 나는 "데이터 정확성 향상 효과"로 해석했지만 실제로는:
- 옵션F가 오염된 캐시 + 정상 FN 데이터를 섞어서 가짜 YoY 알파 생성
- KBI메탈 등 추격 매수 위험 종목이 cr 1위 진입
- BT 결과는 가짜 알파를 캡처한 인플레

큰 BT 개선이 정당하려면 **명백한 시그널 향상** 메커니즘이 있어야 (예: 새 시그널 추가, 알려진 노이즈 제거). 데이터 mismatch 정정 같은 변경은 **점진적 개선** (Cal +0.1~0.2)이 자연. +0.5 이상이면 가짜 알파.

**How to apply**:
- 변경 후 BT Cal 차이가 클 때 다음 점검:
  1. **이상 종목 진입 점검**: 알 수 없는/위험 종목이 ranking 상위 진입했나? (이격도 폭등, 4연상한, 매출 비현실적 폭증 등)
  2. **변동성 패턴 점검**: 평균 변동성 평소와 다른가? (가짜 알파는 보통 변동성 큰 종목 끌어옴)
  3. **메커니즘 설명 가능성**: 왜 그 변경이 그렇게 큰 효과를 내는지 1줄로 설명되나? 설명 어려우면 의심.
- 변경 후 5/11 같은 최근 ranking으로 표본 검증 시:
  - 호의적 사례 (의도한 종목이 들어옴) ✓
  - **비호의적 패턴 (이상 종목이 들어옴) — 같이 점검 필수** ✗
- BT만 보고 "성과 개선"으로 결론 내지 마라. 진짜 시그널인지 가짜 알파인지 메커니즘 검증.

---

### feedback_bilateral_sample_check.md

```yaml
---
name: 표본 검증 양면 점검 — 호의적 사례만 보지 말기
description: 변경 후 표본 ranking/결과 검증 시 의도한 효과뿐 아니라 이상/비호의적 패턴도 같이 확인.
type: feedback
---
```

변경 후 표본 검증할 때 **의도한 효과(호의적 사례)만 확인하지 마라.** 이상/비호의적 패턴(예상 못 한 종목 진입, 변동성 폭등)도 같이 점검해야 한다.

**Why**: 2026-05-12 옵션F 적용 후 5/11 ranking 표본 검증 시:
- 호의적 사례만 확인: SK스퀘어 매출 14,115 → 104,556 자동 복구 ✓
- 비호의적 사례 누락: **KBI메탈(024840) 같은 4연상한 추격 매수 위험 종목이 cr 1위로 들어옴 — 점검 안 함**
- 결과: 가짜 알파 ranking을 정상이라 판단 → 채널 발송 → 구독자에게 잘못된 매수 추천

**How to apply**: 변경 후 표본 검증 시 다음 두 가지 모두 확인:
1. **호의적 점검 (의도한 효과)**: 변경이 의도한 종목이 올바르게 처리됐나?
2. **비호의적 점검 (예상 못 한 부작용)**:
   - Top 10/20에 알 수 없는/위험 종목 있나?
   - 이격도20 > 1.5 또는 RSI > 85 같은 추격 매수 위험 종목 진입?
   - 매출/점수가 비현실적으로 폭증한 종목?
   - 평소 universe와 다른 섹터/시총 분포?
3. 어느 한쪽만 통과하면 안 됨. **둘 다 통과해야 변경 채택**.

---

### feedback_root_cause_not_workaround.md

```yaml
---
name: 사용자 "본질 해결" 요청 시 가장 깊은 원인까지 추적
description: 사용자가 "맹점 없는 본질 해결" 강조할 때 표면 정정 도구 만들지 말고 가장 깊은 원인(데이터 자체, 코드 자체)까지 추적.
type: feedback
---
```

사용자가 "본질 해결", "맹점 없이", "표면이 아니라 진짜" 같은 표현 쓰면 **가장 깊은 원인까지 추적**해서 해결책 제시해야 한다. 표면 정정 도구를 만들지 마라.

**Why**: 2026-05-12 사고. 사용자 "맹점없는 본질 해결 필요. 7시간 걸려도 상관없어" 강조에:
- 진짜 본질: fs_dart 캐시 자체가 4/4 매핑 버그로 오염 → **재수집이 정공법**
- 내 제안 옵션F: mismatch 항목별 자동 정정 → 표면 가림으로 더 위험 (가짜 알파 생성)
- 사용자가 회사 PC에서 발견 + 옵션F 폐기 + 캐시 재수집 매뉴얼 작성

표면 정정 도구는:
- "자동", "런타임", "정정", "보충" 같은 표현이 들어가면 의심
- 데이터 자체는 그대로 두고 사용 시점에 처리하는 패턴은 표면 처방

**How to apply**:
- 사용자가 본질 해결 강조 시 단계별 질문:
  1. 진짜 원인이 데이터인가, 코드인가, 외부 시스템인가?
  2. 데이터면 어디서 오염됐나? 시점 추적 가능?
  3. **원인 자체를 정정/제거하는 방법은?** (수집 코드 수정, 캐시 재구축, 잘못된 row 삭제 등)
  4. 표면 정정 도구 제안 전에 위 1-3 답하고 사용자 의도 확인.
- "런타임 자동 정정" 같은 패턴은 가짜 정상화의 유혹. 매번 ranking 생성 시 자동 정정이라도 데이터 자체가 깨끗하면 더 좋음.
- 사용자가 "재수집해야 한다"고 명시할 때까지 기다리지 말고, 내가 먼저 "캐시 자체 재구축이 더 정확하지 않을까?" 질문하기.

---

### feedback_5_15_quarterly_surge.md

```yaml
---
name: 1Q/3Q 마감 시기 DART 폭주 대비 — 새 데이터 매핑 사고 자동 감지
description: 5/15(1Q), 8/15(반기), 11/15(3Q) 분기 마감 직후 DART 새 데이터 폭주. 매핑 사고 발생 시 자동 차단 + 개인봇 알림 패턴.
type: feedback
---
```

분기 보고서 법정 마감일(5/15 1Q, 8/15 반기, 11/15 3Q) 직후 DART에 새 데이터 폭주. **매핑 사고 외부 트리거 가능성 가장 높은 시기**. 자동 차단 + 사용자 즉시 알림 패턴 필수.

**Why** (2026-05-12 경험):
- 5/4 SG&A → 매출액 잘못된 매핑이 4/4 commit 이후 한 달간 발현 안 함
- 5/4 외부 트리거(DART API 응답 변동)로 갑자기 발현 → SK 등 대형주 ranking 이탈
- 5/12 옵션F 사고 — 캐시 오염 + 옵션F 정정으로 가짜 알파 생성
- 5/15 1Q 폭주 시기 = 같은 외부 트리거 위험
- LG엔솔/LG화학 영업이익 부호 사고도 비슷한 패턴

**How to apply**:
- monitor_dart_fn_health.py 매일 실행 (run_daily Step 0.2)
- 무결성 의심 시 개인봇 즉시 알림
- 분기 마감 D±5 집중 점검
- pre-commit hook + test_account_map.py 통과 필수

---

## 2) 기존 project 업데이트

### project_option_f_account_mismatch.md (업데이트)

```yaml
---
name: 옵션 F 사고 — 도입 후 가짜 알파 생성 → 호출 폐기 (2026-05-12)
description: 옵션F가 오염된 캐시 + 정상 FN 섞어 가짜 YoY 알파 생성. KBI메탈 cr 1위 사례. 호출 폐기 + fs_dart 179종목 재수집이 진짜 본질 해결.
type: project
originSessionId: 58d96806-d114-4fb3-83cc-4fb6f7875117
---
```

## ⚠️ 사고 결론
**옵션F는 잘못된 해결책**. 5/12 새벽 도입 후 같은 날 사용자가 회사 PC에서 가짜 알파 생성 발견, **옵션F 호출 폐기** (`fast_generate_rankings_v2.py:843`).

## 사고 메커니즘
1. 4/4 commit `409dea9d7`에서 SG&A → 매출액 잘못된 매핑 추가됨
2. 5/4 매핑 제거됐지만 **캐시 디스크 데이터는 그대로 오염** (179종목)
3. 옵션F가 같은 종목 24년 매출(오염=SG&A 값, 작음) + 25년 매출(FN 정상, 큼) 섞음
4. 결과: 매출 폭증 환상 → **가짜 YoY 알파**
5. KBI메탈(024840) 4연상한 추격 매수 위험 종목이 cr 1위로 진입
6. BT Cal 3.68→4.288 향상도 **가짜 알파에 의한 인플레**
7. 5/11 채널 발송 시 가짜 알파 ranking이 구독자에게 잘못된 추천으로 전달

## 진짜 본질 해결 (사용자 회사 PC)
- fs_dart 179종목 재수집 (DART 단일 worker, sleep 0.3초)
- 옵션F 호출 폐기 (함수는 보존 — monitor에서 베이스라인 측정용)
- 자동 방어막 7개 구축 (pre-commit hook, unit test, monitor 강화 등)
- 사건 인계: `HANDOVER_20260512_FS_DART_CACHE_FIX.md`
- 집 PC 매뉴얼: `HOMEPC_DO_THIS.md` (60-90분, 13단계)

## 학습한 교훈 (별도 feedback 파일)
- `feedback_no_surface_fix_on_corrupted_data.md`
- `feedback_suspect_large_bt_gains.md`
- `feedback_bilateral_sample_check.md`
- `feedback_root_cause_not_workaround.md`

---

## 3) MEMORY.md 인덱스 추가 항목

```markdown
- -> [project_option_f_account_mismatch.md](project_option_f_account_mismatch.md): **옵션F 사고** — 도입 후 가짜 알파 생성 → 호출 폐기 (2026-05-12). KBI메탈 cr 1위 사례. 진짜 해결은 fs_dart 179종목 재수집
- -> [feedback_no_surface_fix_on_corrupted_data.md](feedback_no_surface_fix_on_corrupted_data.md): 손상된 데이터에 표면 정정 금지 — 재수집이 정공법
- -> [feedback_suspect_large_bt_gains.md](feedback_suspect_large_bt_gains.md): 데이터 변경만으로 큰 BT 개선(>+0.5) = 가짜 알파 의심부터
- -> [feedback_bilateral_sample_check.md](feedback_bilateral_sample_check.md): 표본 검증 양면 점검 — 호의적 사례만 보지 말고 비호의적 패턴도 확인
- -> [feedback_root_cause_not_workaround.md](feedback_root_cause_not_workaround.md): 사용자 "본질 해결" 요청 시 가장 깊은 원인까지 추적
- -> [feedback_5_15_quarterly_surge.md](feedback_5_15_quarterly_surge.md): 분기 마감(5/15, 8/15, 11/15) DART 폭주 대비 — 매핑 사고 외부 트리거 위험
```

---

## 4) 적용 방법 (회사 PC)

방법 A — Claude에게 위임:
```
회사 PC에서 Claude Code 실행 후:
"MEMORY_UPDATE_20260512_OPTION_F_INCIDENT.md 읽고 메모리에 반영해줘"
```
→ Claude가 자동으로 각 섹션을 메모리 파일로 작성.

방법 B — 수동 복사:
```powershell
# 회사 PC 메모리 디렉토리 위치 확인
notepad $env:USERPROFILE\.claude\projects\C--dev-claude-code-quant-py-main\memory\MEMORY.md
```
위 md 파일 내용을 직접 메모리 디렉토리에 복사.
