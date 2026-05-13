# 시스템 프롬프트/Few-shot 엔지니어링 전문가 v2 리뷰 — 가이드 backing 관점

대상: CX v6.0 (1,079 lines) / 직원용 v11.0 (470 lines) / UX v6.0 (626 lines)
모델 가정: GPT-OSS-120B (instruction-following 약·한국어 OK)
원칙: 모든 권고는 「고객중심 언어 가이드」(2026.02 발간) PDF backing 필수. 가이드 silent 항목은 권고 X — 백로그로만 분리. § 비-한국 표기 금지. 권고 옆 가이드 페이지 번호 의무.

---

## 1. v1 retrospective — 가이드 silent였던 권고 분류

v1 비판 9건을 backing 관점에서 재분류.

| v1 권고 ID | 제목 | backing 분류 | 사유 |
|---|---|---|---|
| HIGH-1 | EX 형식 ★★ 볼드 강제 sweep | **silent** | 마크다운 볼드(`**`)는 시스템 출력 메타. 가이드 PDF 9-137p Grep 결과 `**` 강조 표기 0건. 가이드는 "메인 문구(볼드체)"(99p) 명시는 있으나 마크다운 별표 자체는 silent → 운영 메타로만 backing 가능 → 권고 자체는 운영 보조 룰 영역 |
| HIGH-2 | Anti-priming 부정 enum 삭제 | **silent** | "anti-priming"은 prompt 엔지니어링 운영 카테고리. 가이드 backing 없음 → 운영 보조 룰 박스 안 권고로만 backing 가능 |
| HIGH-3 | "X 금지" → "Y만 사용" 변환 | **silent** | LLM IF 약점 운영 카테고리. 가이드 backing 없음 |
| HIGH-4 | 메타 검증 룰 (출력 직전 대조) 삭제 | **silent** | 운영 메타. 가이드 backing 없음. 단 "운영 보조 룰 [4] 가짜 원문 차단 룰 한 줄로 압축"은 운영 보조 박스 안 backing OK |
| MEDIUM-1 | LangChain `{{}}` brace pre-processor | **silent** | LangChain 호환은 가이드 외 운영 영역. backing 없음 |
| MEDIUM-2 | 형식 예 5중 정의 통합 | **silent** | 시스템 출력 메타. backing audit B 분류 |
| MEDIUM-3 | Multi-turn carry-over 차단 룰 | **silent** | LLM 운영 영역. 가이드 backing 없음 |
| LOW-1 | 룰 중복 3회+ 압축 | **silent** | byte budget 운영 영역. backing 없음 |
| LOW-2 | RAG 4계층 분리 직원용·UX 복제 | **silent** | RAG 운영 영역. 가이드 backing 없음 |
| LOW-3 | "안내드립니다" → "발생되었습니다" 사례 의미 mismatch | **partial backing** | 가이드 99p verbatim "행동 결과를 능동형으로 표현. 단, 시스템이 주체가 되어야 하는 경우 피동" — CX L800 사례 "미수금이 발생되었습니다" 판정은 가이드 99p backing OK. v1이 ambiguity 지적한 부분은 사례 wording의 가이드 99p 정합도 → 부분 backing 있음 |

**retrospective 핵심**: v1 9건 중 **8건이 가이드 silent**, 1건만 부분 backing. 가이드 backing 의무 원칙으로 보면 v1 권고는 모두 운영 보조 룰 박스 안에서만 적용 가능한 권고였음. backing audit 분류상 모두 B 카테고리(운영 보조)에 해당.

---

## 2. v2 새로 발견한 backing-있는 권고 (5건)

v1이 prompt engineering 운영 관점에 집중하느라 놓친, **가이드 PDF backing이 명확한 권고**만 별도 list.

### [HIGH-A] CX L657 마케팅 형식 예 — "혜택이 기다리고 있어요~" 물결 어미가 가이드 9p Trustworthy 위반

- **위치**: CX `system_prompt_v6.0_cx_flat_LF_escaped.txt` L653 verbatim:
  ```
  #{{고객명}} 고객님, 혜택이 기다리고 있어요~
  ```
- **가이드 backing**: 가이드 9p Trustworthy "**불필요한 감정 표현은 절제합니다**" verbatim. 가이드 10p 마케팅 톤 "혜택은 정확하게, 핵심가치는 균형 있게 설명합니다" verbatim. 물결표(~) 종결은 가이드 79p "기호" 룰에서 verbatim 등장 0회. 가이드 12p before/after 사례에서도 `~` 종결 어미 사용 0회.
- **위험**: 형식 예 본문이 마케팅 톤 학습 anchor → 모델이 일반 LMS 마케팅에도 `~` 어미 회귀 위험. 가이드 9p Trustworthy "불필요한 감정 표현 절제"와 직접 충돌.
- **개선안 (가이드 9p, 10p 자체 backing)**: L653을 "#{{고객명}} 고객님, 다음 혜택을 안내해 드립니다."로 교체. 마케팅 도메인 EX는 가이드 10p "정확하게·균형 있게" 톤 anchor.

### [HIGH-B] CX L668 마케팅 형식 예 — "↗ 좋은 흐름은 위에서부터! 처음부터 읽어 보세요." 가이드 silent + 자체 발명 화살표 기호

- **위치**: CX L668 verbatim: `↗ 좋은 흐름은 위에서부터! 처음부터 읽어 보세요.`
- **가이드 backing**: 가이드 63-64p LMS 마케팅 verbatim 명시 기호는 ※(심의문구), ■(블록 명칭). 화살표 기호 ↗·↘·→은 가이드 PDF Grep 등장 0회. 가이드 79p 기호 룰도 화살표 silent.
- **위험**: 형식 예 본문에 가이드 미명시 자체 발명 기호가 anchor로 박혀 있어 backing 무결성 audit 분류상 D(자체 발명) 잔재 우려. backing audit이 "0건"으로 판정한 부분과 모순.
- **개선안 (가이드 63-64p backing)**: L668 1줄 삭제 또는 ※ 기호로 변환. 가이드 63-64p verbatim 마케팅 형식 패턴만 사용.

### [HIGH-C] CX L780 / L801 사례 "미수금이 발생되었습니다" — 가이드 28p 중복용어 "발생되" 위반

- **위치**: CX L780 verbatim "#{{고객명}} 고객님, 아래 계좌에 미수금이 **발생되었습니다**." / L801 verbatim `1. "미수금 안내드립니다" → **"미수금이 발생되었습니다"** · 시스템 주체 피동 (가이드 99p)`
- **가이드 backing**: 가이드 28p 중복용어 삭제 verbatim "**정상적으로 처리되지 않았습니다 → 정상 처리되지 않았습니다**" 패턴 (이중 피동·잉여 음절 압축). "발생되었습니다"는 "발생하다"+피동 조합으로 이중 피동 회귀. 가이드 99p verbatim 사례는 "체결되었습니다·처리되었습니다·접수되었습니다" — "발생되" 사례는 가이드 PDF 등장 0회.
- **위험**: 형식 예가 anchor → 모델이 시스템 피동을 "X되었습니다" → "X되되었습니다" 류 회귀.
- **개선안 (가이드 28p, 99p backing)**: L780·L801 모두 "미수금이 발생했습니다" 또는 "계좌에 미수금이 있습니다"로 교체. 가이드 99p 시스템 피동 사례는 verbatim "체결되었습니다·처리되었습니다" 안에 해당하는 동사만 사용.

### [MEDIUM-A] 직원용 L347 EX1 출력 "확인했습니다. 그거 내일 오전 중으로 보내 드리겠습니다." — 가이드 31p 모호 지시어 "그거" 잔재

- **위치**: 직원용 `system_prompt_internal_memo_v11.0.txt` L373 verbatim "확인했습니다. **그거** 내일 오전 중으로 보내 드리겠습니다." (EX1 출력 본문 안)
- **가이드 backing**: 가이드 31p verbatim "**모호 지시어 ('그거/이거/그쪽/이쪽') → 원문 단서로 구체화**". 직원용 L80도 "모호 지시어 ('그거/이거/그쪽/이쪽') → 원문 단서로 구체화" 자체 명시. 그런데 EX1 출력에 "그거" 그대로 잔존 → 룰과 사례 모순.
- **위험**: 모델은 EX 본문 우선 학습 → 모호 지시어 보존 회귀.
- **개선안 (가이드 31p backing)**: 입력 "그거 내일 오전중에 보내줄께"의 "그거"는 입력 단서 부족 → EX1 입력을 단서 있는 입력 ("회의록 내일 오전중에 보내줄께")으로 교체. 또는 출력에서 "그거"를 "해당 자료"로 일반화.

### [MEDIUM-B] 직원용 L131 외래어 표기 "타겟→타깃" — 가이드 79p backing 명시 보강 필요

- **위치**: 직원용 L131 verbatim "메세지→메시지, 멤버쉽→멤버십, 컨텐츠→콘텐츠, 캡쳐→캡처, 비지니스→비즈니스, 런칭→론칭, 레포트→리포트, 스케쥴→스케줄, **타겟→타깃**"
- **가이드 backing**: 가이드 79p 띄어쓰기·기호·외래어 룰 verbatim. 단 가이드 PDF p79 추출본 Grep 결과 "타겟"·"타깃" verbatim 등장 0회. 다른 외래어(메세지·콘텐츠·스케줄)는 가이드 본문 backing 가능성 있으나 "타깃"은 silent → backing audit B로 분류해야 함.
- **위험**: backing audit "0건 자체 발명" 판정과 모순. 가이드 명시 외래어와 silent 외래어가 섞여 있어 사용자가 "이것도 가이드 룰"로 오인.
- **개선안 (가이드 79p partial backing)**: 가이드 79p verbatim 등장 외래어만 박스에 남기고, "타겟→타깃" 등 가이드 silent 항목은 [운영 보조 룰] 박스로 이동 또는 `guide_check_backlog.md`에 분리. 즉 박스 분리 boundary를 외래어 항목별로 재확정.

---

## 3. v1 권고 중 backing 불충분 항목 (재판정)

v1 비판 9건을 강등.

| v1 권고 ID | v2 판정 | 이동처 |
|---|---|---|
| HIGH-1 (★ 볼드 sweep) | LOW (운영 보조) | [운영 보조 룰] 안 권고로 backing audit B 영역 |
| HIGH-2 (anti-priming) | LOW (운영 보조) | 운영 보조 (가이드 silent) |
| HIGH-3 (negation 변환) | LOW (운영 보조) | 운영 보조 (가이드 silent) |
| HIGH-4 (대조 룰 삭제) | LOW (운영 보조) | 운영 보조 [4]에 이미 backing 없음 명시 |
| MEDIUM-1·2·3 / LOW-1·2 | LOW 또는 NA | 운영 보조 (가이드 silent) |
| LOW-3 (피동 ambiguity) | MEDIUM 유지 | 가이드 99p partial backing 있음 |

---

## 4. v2 우선순위 표 — backing-있는 권고만

| 등급 | ID | 위치 (라인 verbatim) | 가이드 backing |
|---|---|---|---|
| **HIGH** | A | CX L653 `#{{고객명}} 고객님, 혜택이 기다리고 있어요~` | 가이드 9p, 10p |
| **HIGH** | B | CX L668 `↗ 좋은 흐름은 위에서부터! 처음부터 읽어 보세요.` | 가이드 63-64p, 79p |
| **HIGH** | C | CX L780, L801 "미수금이 발생되었습니다" | 가이드 28p, 99p |
| MEDIUM | A | 직원용 L373 "그거 내일 오전 중으로 보내 드리겠습니다" | 가이드 31p |
| MEDIUM | B | 직원용 L131 "타겟→타깃" 등 가이드 silent 외래어 boundary | 가이드 79p partial |

---

## 5. 종합 평가

v1 리뷰는 prompt engineering 관점에서는 정확하지만 **9건 중 8건이 가이드 silent 영역(운영 보조 카테고리)에 해당**, 가이드 backing 의무 원칙으로는 권고 자체를 [운영 보조 룰] 박스 안 변경으로 한정해야 함. backing audit 결과(자체 발명 잔재 0건·가이드 모순 0건)는 박스 분리 무결성 기준으로는 production-ready지만, **EX 본문 안 자체 발명 표현**(HIGH-A 물결 어미·HIGH-B 화살표 기호·HIGH-C 발생되 이중 피동) 3건은 가이드 backing 위반이 명확.

특히 HIGH-C "미수금이 발생되었습니다"는 형식 예 본문(L780)과 [수정 사항] 사유 라벨(L801)에 동시 박혀 있어 anchor로 강화된 상태 → 가이드 28p 중복용어·가이드 99p 시스템 피동 verbatim 사례 둘 다와 모순. 사용자 환경에서 시스템 피동 회귀 시 "X되되었습니다" 형 이중 피동 환각을 유발할 가능성.

우선순위 변경 작업 순서:

1. HIGH-C → CX L780·L801 "발생되었습니다" → "발생했습니다" 또는 "있습니다" 1건 sweep (가이드 28p, 99p 직접 backing)
2. HIGH-B → CX L668 ↗ 화살표 1줄 삭제 (가이드 63-64p, 79p backing)
3. HIGH-A → CX L653 "~" 어미 정정 (가이드 9p, 10p backing)
4. MEDIUM-A → 직원용 L373 EX1 입력·출력 모호 지시어 정정 (가이드 31p backing)
5. MEDIUM-B → 직원용 L131 외래어 boundary 박스 분리 (가이드 79p partial)

각 변경은 1회 1건 사용자 환경 검증 + backing audit 표 업데이트(D→A 이동 또는 박스 분리). v1 9건 중 [운영 보조 룰] 박스 안 권고로 backing 가능한 항목은 별도 트랙(운영 보조 트랙)에서 처리. 사용자 결정에 따라 적용 여부 분리.

byte budget 영향: HIGH 3건 sweep은 약 +50 byte 미만(교체 어휘 길이 비슷). 운영 보조 트랙(v1 9건)은 별도 작업.
