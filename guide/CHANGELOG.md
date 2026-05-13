# Mi-Tone System Prompt CHANGELOG

가이드 PDF backing 원칙 적용. 모든 변경은 가이드 페이지 인용 가능.

---

## v6.1 / v11.1 / v6.1 — 2026-05-04 ~ 2026-05-08

**버전 lineage**:
- CX: v6 lineage (v5.45 → v6.0 → v6.1)
- 직원용: v11 lineage (v9.4 → v10.0 → v10.1 → v11.0 → v11.1, 별도 lineage)
- UX: v6 lineage (v5.21 → v6.0 → v6.1)

직원용은 CX보다 lineage 시작이 일찍이라 v11 사용. CX·UX는 v6 lineage. 다음 bump도 각자 lineage 따라 진행.

### CX v6.0 → v6.1
- Step 0 유형 분류 룰 v2 전면 재작성 (A 마케팅 > B 뉴스레터 > C 이메일 > D 알림톡 > E SMS > F LMS 고지 > G VOC 우선순위)
- 한자어 순화 박스 ★★ 강조 — "양지" 자체 변환 의무 (가이드 134p)
- 알림톡 D 시그널: "7일 동안" 단일 매칭 100% 채택
- SMS E 시그널: "[미래에셋증권] 매매 정상 처리되었습니다." 100% SMS
- 마케팅 형식 예 2 박스 본문 통째 삭제 → 한 줄 안내 (byte 절감)
- VOC 형식 예 3 박스 본문 통째 삭제 → "EX-T1 [VOC_BASIC] 본문 참조" 한 줄
- VOC 환각 차단 enum 추가: "VOC전담팀·1588-6800·관련 부서·재발 방지·내부 절차·신뢰" 자체 발명 wording 차단
- EX-T1 [VOC_BASIC]·[VOC_REJECT] wording 정정 (자체 발명 wording 삭제)
- 절대 보호 8번 회사명 verbatim 강제 ("[미래셋증권]" 오타 차단)
- 정답데이터 521건 EDA 기반 ■ 30+ 명칭 enum + 8 형식 예 + 6 신규 룰

### 직원용 v11.0 → v11.1
- 다양한 문체 활용 박스 ([1]) — 가이드 26p verbatim 인용
- 쿠션어 보존 enum 추가: "부탁드려도 될까요?·부탁드릴 수 있을까요?·해 주실 수 있을까요?·해 주시면 감사하겠습니다·가능하실까요?·확인 부탁드립니다"
- 호칭 enum에 "책임님" 추가
- 표준 쪽지 형식 박스 신규 (시작·본문·끝 3단)
- ⚠️ 누락 안내 룰 추가 (인사말·소속·이름·끝 인사 누락 시 출력 마지막에 한 줄)
- 출력 형식 박스에 ⚠️ 1줄 예외 명시
- 형식 예 case 1·2에 ⚠️ 출력 위치 verbatim 추가
- "X 부탁드립니다" 자연 정중 표현 보존 명시 (변환 X)

### UX v6.0 → v6.1
- 6 전문가 검수 critical 위반 일괄 수정
- 알럿·바텀시트·툴팁 컴포넌트 4종 verbatim (가이드 90-98p)
- "꼭 확인해 주세요" 알럿 타이틀 룰
- 줄 분리 + 볼드 룰 통합

---

## ARCHIVE 룰 (다음 bump부터)

매 bump마다 `99_archive\prompts_old\`에 직전 버전 사본 보관:
- `system_prompt_v6.1_cx_flat_LF_escaped.BAK_b4_v6.2.txt` 형식
- 회귀 발견 시 diff로 변경 위치 추적 가능

v6.0 사본은 archive에 없음 (당시 누락). v6.0 → v6.1 변경 추적은 본 CHANGELOG 항목 + git log(있다면)으로만 가능.

---

## verify·OFFICE_CHECKLIST·CHANGELOG cross-ref

bump 시 동시 갱신 의무:
- 파일명 (`_v6.1_` → `_v6.2_`)
- 헤더 첫 줄 ("v6.1 CX..." → "v6.2 CX...")
- `verify.ps1` L9·L10·L13·L23 (path + 출력 메시지)
- `verify_all.bat` L6·L7·L8·L14
- `OFFICE_CHECKLIST.md` 대상·Action·파일 path 4곳
- 본 `CHANGELOG.md` 새 버전 항목 추가

한 곳이라도 빠지면 cross-ref 깨짐. verify_all.bat 실행 시 file missing FAIL 출력.
