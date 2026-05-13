# Mi-Tone v5.21 배포 가이드

> 사용자가 회사에서 vector DB와 시스템 프롬프트 교체할 때 따라갈 1페이지 안내.
>
> ⚠️ **사용자 검증 필요**: RAG 운영팀 핫라인·연락처, 임베딩 절차의 권한, 백업 저장 위치 등은 사용자 회사 운영 환경과 대조해 정정 후 사용.

## 🎯 배포 작업 흐름

```
0. 백업 (롤백 대비)
   ↓
1. RAG vector DB에 신규 docx 12개 + 갱신 docx 5개 추가/교체
   ↓
2. 시스템 프롬프트 교체 (v5.20 → v5.21)
   ↓
3. 5건 파일럿 테스트
   ↓
4. (사고 시) 롤백
```

---

## 📦 0. 사전 백업 (반드시 먼저)

| 백업 대상 | 백업 위치 | 사유 |
|---|---|---|
| `system_prompt_v5.20_cx_flat_LF_escaped.txt` | 다른 폴더 또는 클라우드 | 롤백용 |
| RAG vector DB 인덱스 (현재 상태) | 운영팀 백업 또는 스냅샷 요청 | 롤백용 |
| 기존 cx_goldens_01a~f.docx (정답데이터1 옛 양식) | 백업 폴더 | 변환 전 보존 |
| 기존 cx_rules_common_mistakes.docx | 백업 폴더 | 갱신 전 보존 |
| 기존 cx_00_index.docx | 백업 폴더 | 갱신 전 보존 |
| 기존 cx_pattern_passive_to_active.docx | 백업 폴더 | 갱신 전 보존 |
| 기존 cx_pattern_voc_samples.docx | 백업 폴더 | 갱신 전 보존 |
| 기존 cx_channel_09_voc_reply.docx | 백업 폴더 | 갱신 전 보존 |

---

## 📂 1. RAG vector DB 갱신

### 1-A. 옛 cx_goldens 6개 제거 (덮어쓰기 변환됨)

기존 정답데이터1 cx_goldens_01a~01f는 **이미 v5.21 양식으로 덮어쓰기**됐어요. RAG에 다시 임베딩만 하면 됩니다.

### 1-B. 신규/갱신 docx 22개 임베딩

**RAG에 추가/교체할 파일 22개**:

#### A. 정답데이터2 카드 8개 (신규)
- `C:/dev/guide/정답데이터2/cx_goldens2_derivatives.docx` (28건)
- `C:/dev/guide/정답데이터2/cx_goldens2_product.docx` (25건)
- `C:/dev/guide/정답데이터2/cx_goldens2_credit_loan.docx` (24건)
- `C:/dev/guide/정답데이터2/cx_goldens2_settlement.docx` (28건)
- `C:/dev/guide/정답데이터2/cx_goldens2_misc.docx` (23건)
- `C:/dev/guide/정답데이터2/cx_goldens2_marketing.docx` (18건)
- `C:/dev/guide/정답데이터2/cx_goldens2_pension.docx` (7건)
- `C:/dev/guide/정답데이터2/cx_exceptions_misuyong.docx` (35건 NEGATIVE)

#### B. 정답데이터1 변환본 6개 (덮어쓰기 — 옛 인덱스 제거 후 재임베딩)
- `C:/dev/guide/정답데이터1/cx_goldens_01a_review_samples.docx` (5건)
- `C:/dev/guide/정답데이터1/cx_goldens_01b_review_samples.docx` (5건)
- `C:/dev/guide/정답데이터1/cx_goldens_01c_review_samples.docx` (5건)
- `C:/dev/guide/정답데이터1/cx_goldens_01d_review_samples.docx` (5건)
- `C:/dev/guide/정답데이터1/cx_goldens_01e_review_samples.docx` (5건)
- `C:/dev/guide/정답데이터1/cx_goldens_01f_review_samples.docx` (4건)

#### C. 신규 RAG docx 4개 (가이드 본문 보강)
- `C:/dev/guide/guide_rag_cx_docx_flat/cx_part4_prompt_meta.docx`
- `C:/dev/guide/guide_rag_cx_docx_flat/cx_editorial_policy.docx`
- `C:/dev/guide/guide_rag_cx_docx_flat/cx_voc_scenario_misclaim.docx`
- `C:/dev/guide/guide_rag_cx_docx_flat/cx_voc_edit_initial_draft.docx`

#### D. 기존 RAG docx 갱신 5개 (덮어쓰기)
- `cx_00_index.docx` (인덱스 갱신)
- `cx_rules_common_mistakes.docx` (대대적 갱신)
- `cx_pattern_passive_to_active.docx` (시스템 주체 피동 OK)
- `cx_pattern_voc_samples.docx` (4 시나리오 매트릭스)
- `cx_channel_09_voc_reply.docx` (신규 voc docx 참조 메모)

### 1-C. 임베딩 작업

업로드 시 일부 docx 임베딩 실패할 수 있음 (사용자 경험: 40개 중 2-3개). 재시도하면 정상 들어감.

---

## ⚙️ 2. 시스템 프롬프트 교체

```
교체:
  v5.20 → v5.21
  파일: C:/dev/guide/system_prompt_v5.21_cx_flat_LF_escaped.txt (639줄)

핵심 변경:
  - 페르소나: 교정 담당 → 금융소비자보호팀 검수자
  - line 9 톤 매트릭스 5단 분기 (해요체 행동요청 등)
  - 시스템 주체 피동 OK 화이트리스트
  - 자가 검수 13 → 5
  - 6 예시 → 3 예시 (SMS·마케팅·VOC)
  - 한자어/외래어/심리불편 표 → cx_term_* RAG 위임
  - tie-breaker 5단계 + 카드 마커 해석 룰
  - 페이지 마스터 12 → 22종
```

---

## 🧪 3. 5건 파일럿 테스트

검증 입력 5건:

| # | 입력 | 검증 포인트 |
|---|---|---|
| 1 | "[미래에셋증권] 융자만기일 안내 #{고객명} 고객님 ~확인하시기 바랍니다." | 해요체 변환 + ☎ 삭제 |
| 2 | "(광고) [미래에셋증권] 이벤트 신청하시기 바랍니다. 수익률 30% 가능!" | 마케팅 해요체 + 광고 규제 + 심의문구 자발 추가 |
| 3 | "[미래에셋증권] 주식 매수가 체결되었습니다." | 시스템 주체 피동 OK 유지 (능동 변환 X) |
| 4 | "거듭 사과드립니다. 금감원 민원 제기를 고려..." | 외부 위험 요소 삭제 + 과한 사과 축약 |
| 5 | "[미래에셋증권] 본인인증번호 123456 입력해 주세요." | 원문 준수 (수정 없음) |

각 입력별 기대 출력:

1. → "확인해 주세요" + ☎ 제거 + LMS 5단 자발 추가
2. → 광고 규제 경고 + "신청해 주세요" 해요체 + 심의문구 3종 자발
3. → 체결되었습니다 그대로 유지 (변환 X)
4. → 사과 1회 + 금감원 언급 삭제 + 해결 중심 클로징
5. → "원문 준수" 메시지 (케이스 3)

---

## 🚨 4. 사고 시 롤백 절차

(`rollback_playbook.md` 상세 참조)

**트리거 조건**:
- 검수 통과율 50%↓ 또는 G8 발생률 60%↑
- 사고 보고 3건↑
- 임원 결정

**롤백 절차** (1시간 이내):
1. 시스템 프롬프트 v5.21 → v5.20 교체
2. RAG에서 신규 12 docx 제거
3. 기존 cx_goldens·cx_rules 등 백업본 복원
4. 5건 파일럿으로 v5.20 정상 작동 확인

---

## 📊 작업 완료 체크리스트

- [ ] 백업 8종 완료
- [ ] 정답데이터2 카드 8 docx RAG 추가
- [ ] cx_exceptions_misuyong.docx RAG 추가
- [ ] 정답데이터1 cx_goldens 6개 RAG 재임베딩 (덮어쓰기)
- [ ] 신규 RAG docx 4종 추가
- [ ] 갱신 RAG docx 5종 덮어쓰기
- [ ] 시스템 프롬프트 v5.20 → v5.21 교체
- [ ] 5건 파일럿 통과
- [ ] 운영 모니터링 시작

---

## 📞 문제 발생 시

1. `rollback_playbook.md` 참조
2. v5.20 백업본으로 즉시 복원
3. 사고 원인 분석 후 v5.22 또는 v5.21.1 패치 검토
