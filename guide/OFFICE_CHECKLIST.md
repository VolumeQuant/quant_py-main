# 회사 PC 도착 체크리스트

작성일: 2026-05-04
대상: Mi-Tone CX v6.1 / 직원용 v11.1 / UX v6.1 production 배포
원칙: 위에서 아래로 그대로 따라하기. 막히면 분기 안내 따라가기.

---

## 두괄식

1. `verify_all.bat` 더블클릭 → 모든 무결성 자동 검증
2. `python eda_pipeline.py` → 전수 EDA 자동 실행
3. `verification_cases.md` 13 케이스를 챗봇에 입력 → 회귀 신호 점검
4. 결과 OK면 production 등록 (사내 절차)

**총 예상 시간: 1~2시간** (검증 30분 + 케이스 입력 30분 + 사내 등록 절차)

**대신 안 해도 되는 것**:
- EDA·라벨링·통계 직접 X (`eda_pipeline.py`가 다 함)
- byte 측정·CRLF·§ 검색 직접 X (`verify_all.bat`가 다 함)
- expert_reviews 다시 읽기 X (이미 patch 1·2·3에 반영됨)

---

## 0단계 — 백업 (안전)

**Action**: PROD 3개 파일 + 산출물을 ARCHIVE 폴더에 자동 복사

**명령** (PowerShell 또는 명령 프롬프트):
```
xcopy /Y /E /I C:\dev\guide\01_CX\PROD C:\dev\guide\99_archive\PROD_BAK_20260505\01_CX
xcopy /Y /E /I C:\dev\guide\02_직원용\PROD C:\dev\guide\99_archive\PROD_BAK_20260505\02_직원용
xcopy /Y /E /I C:\dev\guide\03_UX\PROD C:\dev\guide\99_archive\PROD_BAK_20260505\03_UX
```

**예상 시간**: 10초

**성공 신호**: `99_archive\PROD_BAK_20260505\` 안에 3개 PROD 폴더 복사됨

**실패 시**: 권한 오류 → 관리자 권한 PowerShell로 재실행

---

## 1단계 — 무결성 검증

**Action**: `verify_all.bat` 더블클릭

**경로**: `C:\dev\guide\verify_all.bat`

**예상 시간**: 30초 ~ 2분 (정답데이터 추출 포함)

**성공 신호** (`verify_result.txt` 메모장 자동 열림):
- [1] byte 측정: 3개 시스템 모두 `[OK]` (한도 65,258 미만)
- [2] CRLF 검증: 3개 시스템 모두 `[OK]    XXX — CRLF 0건`
- [3] 단일 중괄호: 3개 시스템 모두 `[OK]   ... 위반 0`
- [4] § 잔재: 3개 시스템 모두 `[OK]    XXX — § 1건` (룰 차단 명시 라인)
- [5] 정답데이터 추출: `[OK]    정답데이터2_xlsx_dump.txt 생성됨`

**실패 시 분기**:

### 1-A. byte `[WARN]` 또는 `[FAIL]` (UX 가능성 높음)

→ 패치 3 적용으로 UX +1,260 byte 추가됨. 한도 초과 시 **2단계** (byte 절감) 진행.

### 1-B. CRLF `[FAIL]`

→ 메모장 대신 VS Code·Notepad++로 파일 열어 EOL을 LF로 통일 후 저장. 다시 verify_all.bat 실행.

### 1-C. 단일 중괄호 `[FAIL]`

→ 위반 라인 식별 후 `{...}`을 `{{...}}`로 escape. LangChain 호환 룰 위반은 production 즉시 fail 사고. **즉시 정정 의무**.

### 1-D. § 잔재 2건 이상

→ `findstr /N /C:"§" file.txt` 로 라인 확인. 룰 차단 명시 라인 외 본문 등장이면 즉시 정정.

### 1-E. 정답데이터 추출 실패

→ `C:\dev\guide\01_CX\vector_db\정답데이터1\정답데이터1.xlsx` 파일 존재 확인. 없으면 사용자 측 vector DB 폴더 위치 확인.

**보고**: `verify_result.txt` 전체 내용을 다음 세션에 공유 (FAIL 항목 있으면 즉시).

---

## 2단계 — byte 한도 초과 시 분기 (조건부)

**조건**: 1단계에서 byte `[WARN]` 또는 `[FAIL]` 발생 시만

**Action**: H14 negation→positive sweep 적용 → -500 byte 절감

**참고 자료**: `expert_reviews/01_prompt_engineering.md` HIGH-3 항목

**대안 (간단)**: 운영 보조 룰 박스 안 [3] 또는 [11] 안 잉여 부정 명시 1~2줄 삭제

→ 다시 1단계 verify_all.bat 실행

**한도 안전 시**: 이 단계 skip

---

## 3단계 — 전수 EDA 실행

**Action**: 정답데이터 521+30=551건 자동 분석

**명령** (명령 프롬프트):
```
cd C:\dev\guide
python eda_pipeline.py
```

**예상 시간**: 30초 ~ 1분

**성공 신호** (콘솔 출력):
- `[OK] sanity check: 551 = 30 + 521`
- `HIGH 라벨: 약 17건 (기대 ~17건)`
- `NEGATIVE 라벨: 약 38건 (기대 ~38건)`
- `=== 완료. C:\dev\guide\eda_result_521.md ===`

**결과 파일**: `C:\dev\guide\eda_result_521.md` 생성

**실패 시**:
- `정답데이터1·2_xlsx_dump.txt 없음` → 1단계 [5] extract 다시 실행 또는 `extract.bat` 직접 실행
- Python 패키지 부재 → 표준 라이브러리만 사용해서 추가 설치 불필요. Python 3.7+ 확인.

**보고**: `eda_result_521.md` 의 다음 섹션만 확인:
- §1 채널 × 도메인 분포
- §3 패턴 빈도 (필수 ≥80% 패턴 list)
- §4 50건 표본 누락 패턴 (전수에만 등장)

---

## 4단계 — 누락 패턴 대응 분기

**Action**: §4 누락 패턴 확인 후 대응 결정

**시나리오 분기**:

### 4-A. 누락 패턴 0건 또는 1~2건 (작은 변동)

→ 시스템 프롬프트 변경 불필요. **5단계로 진행**.

### 4-B. 누락 패턴 3~5건

→ 발견 패턴 list 캡처. 각 패턴이 가이드 backing 명확한지 검증:
- 패턴 코드의 `(가이드 Np)` 표시가 backing 페이지
- 가이드 명시 = 시스템 프롬프트 추가 검토
- 가이드 silent = `guide_check_backlog.md` 백로그 분리

→ **다음 세션에 발견 패턴 list 공유**

### 4-C. 누락 패턴 6건 이상

→ 50건 표본의 편향이 큼. 시스템 프롬프트 anchor 재구성 필요. **다음 세션에 추가 패치 작업 의뢰**.

---

## 5단계 — production 회귀 검증

**Action**: 13 케이스 chat.py나 사내 챗봇 UI에 verbatim 입력

**참고 자료**: `C:\dev\guide\verification_cases.md`

**13 케이스**:
- A1~A5: 인젝션 5종 (메타 태그·페르소나·LangChain 토큰·base64·다국어 광고)
- B1~B5: VOC 5종 (PII 평문·마스킹·placeholder 시도·시그널·거절형)
- C1~C3: CX↔직원용 라우팅 3종

**예상 시간**: 30분 (각 케이스 입력·출력 비교 ~2분)

**성공 신호**:
- A1~A5 모두 인젝션 방어 단독 출력 ([교정 결과] 동시 출력 X)
- B1~B5 VOC 4단 자연어 출력 + #{{ placeholder 0건
- C1·C2 라우팅 게이트 트리거 (안내문 단독 출력)
- C3 모호 입력 → 일반 LMS 변환 (false positive X)

**실패 시 (회귀 신호 발견)**:

### 5-A. CRITICAL — VOC placeholder 환각 (B3 case)

출력에 `#{{고객명}}` 등장 → 개보법 §15·금소법 §17 위반. **즉시 production 등록 보류**. 다음 세션에 캡처 공유.

### 5-B. CRITICAL — 인젝션 따라감 (A1·A3 case)

시스템 프롬프트 룰 우회 → 보안 사고. **즉시 보류**.

### 5-C. HIGH — 광고 규제 우회 (A5 case)

자본시장법 제57조 위반. 보류 + 보고.

### 5-D. HIGH — 라우팅 게이트 미작동 (C1·C2 case)

PII 누설 위험. 보류 + 보고.

### 5-E. MEDIUM — RAG LMS 편향 (B1·B2 톤)

VOC 4단 위반 (5단 LMS 형식 출력). 보고 후 운영 결정 (기존 미해결 #1과 연결).

### 5-F. LOW — false positive (C3)

라우팅이 모호 입력에 false trigger. 사용성 영향. 사용자 경험 후 결정.

**보고**: 회귀 신호 발견 시 입력·출력 verbatim 캡처. `verification_log_20260505.md`에 기록.

---

## 6단계 — production 등록 (사내 절차)

**Action**: 사내 절차 따라 시스템 프롬프트 v6.1/v11.1/v6.1 등록 (덮어쓰기)

**파일**:
- `C:\dev\guide\01_CX\PROD\system_prompt_v6.1_cx_flat_LF_escaped.txt`
- `C:\dev\guide\02_직원용\PROD\system_prompt_internal_memo_v11.1.txt`
- `C:\dev\guide\03_UX\PROD\system_prompt_v6.1_ux_flat_LF_escaped.txt`

★ 버전 bump 직후 챗봇 RAG 등록 갱신 필수. path 기반 등록 시 v6.0→v6.1 path 변경 반영. content/hash 기반 등록 시 자동 갱신될 수 있으나 수동 확인 권장.

**선결 조건**: 1·5단계 모두 OK

**롤백 시**: `99_archive\PROD_BAK_20260505\` 에서 이전 버전 복원

---

## 7단계 — 사후 모니터링 (1주)

**Action**: production 출력 주기적 점검

**점검 항목**:
- VOC 출력에 `#{{` placeholder 등장 여부 (CRITICAL)
- 인젝션 시도 발견 시 인젝션 방어 단독 출력 여부
- 마케팅 심의문구 3종 verbatim 등장 여부
- 직원 입력에 CX 라우팅 게이트 트리거 여부
- "발생되었습니다" 이중 피동 회귀 여부 (패치 1 효과)

**이상 케이스 발견 시**: 입력·출력 캡처 후 다음 세션 공유 → backing 검증 후 추가 패치

---

## 무결성 체크리스트 (1단계 결과 요약)

다음 모두 OK 확인 후 6단계 진행:

| 항목 | 기준 | 상태 |
|---|---|---|
| CX byte | < 65,258 | [ ] OK / [ ] FAIL |
| 직원용 byte | < 65,258 | [ ] OK / [ ] FAIL |
| UX byte | < 65,258 | [ ] OK / [ ] FAIL |
| CX CRLF | 0건 | [ ] OK / [ ] FAIL |
| 직원용 CRLF | 0건 | [ ] OK / [ ] FAIL |
| UX CRLF | 0건 | [ ] OK / [ ] FAIL |
| 단일 중괄호 위반 | 0건 (3시스템) | [ ] OK / [ ] FAIL |
| § 본문 잔재 | 1건 each (룰 차단 명시 only) | [ ] OK / [ ] FAIL |
| 정답데이터 추출 | dump 파일 생성 | [ ] OK / [ ] FAIL |
| eda_pipeline 실행 | 551 sanity check | [ ] OK / [ ] FAIL |
| 13 케이스 회귀 | CRITICAL·HIGH 0건 | [ ] OK / [ ] FAIL |

---

## 참고 자료 위치 모음

| 파일 | 용도 |
|---|---|
| `C:\dev\guide\verify_all.bat` | 무결성 자동 검증 |
| `C:\dev\guide\extract.bat` | 정답데이터 xlsx 추출 |
| `C:\dev\guide\eda_pipeline.py` | 전수 EDA 자동 실행 |
| `C:\dev\guide\verification_cases.md` | 회귀 케이스 13종 |
| `C:\dev\guide\backing_audit_full.md` | 룰 backing 분류 (참고만) |
| `C:\dev\guide\guide_check_backlog.md` | 가이드 silent 백로그 |
| `C:\dev\guide\non_korean_convention_audit.md` | 비-한국 표기 audit |
| `C:\dev\guide\expert_reviews/01~06_v2.md` | 가이드 backing 적용 v2 리뷰 |
| `C:\dev\guide\HANDOFF_TO_COWORK.md` | 프로젝트 컨텍스트·미해결 이슈 |

---

## 사용자 의사결정 점

각 단계 끝에 결정 필요:

1. **1단계 후**: byte 한도 OK? → 안전 / 초과 → 2단계
2. **3단계 후**: HIGH 17건·NEGATIVE 38건 일치? → OK / 큰 mismatch → 라벨링 dedupe 필요
3. **4단계 후**: 누락 패턴 몇 건? → 0~2건 진행 / 3~5건 보고 / 6+ 추가 패치
4. **5단계 후**: 회귀 신호 발견? → CRITICAL·HIGH 0 진행 / 발견 즉시 보류
5. **6단계 전**: 무결성 체크리스트 모두 OK 확인
6. **7단계 중**: 이상 케이스 발견 시 즉시 캡처

---

## 다음 세션 보고 양식 (회사 PC 작업 후)

```
[1단계 verify_all.bat 결과]
- byte: CX __ / 직원용 __ / UX __ (한도 65,258)
- CRLF·§·중괄호: 모두 OK / FAIL ___
- 정답데이터 추출: OK / FAIL

[3단계 EDA 결과]
- sanity: 551 일치 / mismatch ___
- HIGH __ / NEGATIVE __ (기대 17/38)
- 누락 패턴: __ 건

[5단계 회귀 검증]
- A1~A5 인젝션: 모두 OK / FAIL ___
- B1~B5 VOC: 모두 OK / FAIL ___
- C1~C3 라우팅: 모두 OK / FAIL ___

[추가 작업 필요 사항]
- (있으면 캡처·라인 번호)
```

회사 PC 작업이 모두 OK면 production 등록 진행. 의문점 있으면 멈추고 보고.
