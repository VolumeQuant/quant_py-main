# Mi-Tone v5.21 운영 매뉴얼

> 시스템 유지·운영 절차 정리.
>
> ⚠️ **사용자 검증 필요**: 정답데이터3·4 갱신 절차, 운영 책임자, 사내 부서명·연락처, 매주 모니터링 메트릭 임계값 등은 사용자 회사 실제 운영 환경과 대조해 정정 후 사용.

## 📐 시스템 구조도

```
┌─────────────────────────────────────────────────┐
│  사용자 (직원 2,500명)                            │
│  ↓ 메시지 초안 입력                              │
├─────────────────────────────────────────────────┤
│  Mi-Tone (CX) 챗봇 인터페이스                     │
│  ↓                                              │
├─────────────────────────────────────────────────┤
│  RAG 시스템 (사내 IT 인프라팀 운영)               │
│  - vector DB (임베딩)                            │
│  - 검색 엔진                                     │
│  ↓ 관련 docx chunk 검색                          │
├─────────────────────────────────────────────────┤
│  LLM (Claude/GPT 계열)                           │
│  - 시스템 프롬프트: v5.21 (639줄)                 │
│  - [참고자료]: 검색된 docx chunk                 │
│  ↓ 교정 결과 + 수정 사항 출력                     │
├─────────────────────────────────────────────────┤
│  사용자에게 결과 전달                              │
│  → 사용자 채택·수정·반려 결정                     │
└─────────────────────────────────────────────────┘
```

## 📂 시스템 파일 구조

```
C:/dev/guide/
├ system_prompt_v5.21_cx_flat_LF_escaped.txt  (현재 운영 프롬프트)
├ system_prompt_v5.20_cx_flat_LF_escaped.txt  (롤백 백업)
│
├ guide_rag_cx_docx_flat/    (가이드 본문 분해 + 신규 4 docx)
│   ├ cx_00_index.docx                          ★갱신
│   ├ cx_principle_*.docx (9개)                 그대로
│   ├ cx_channel_*.docx (10개)                  그대로 (단 09 갱신)
│   ├ cx_term_*.docx (9개)                      그대로
│   ├ cx_tone_*.docx (3개)                      그대로
│   ├ cx_pattern_*.docx (7개)                   그대로 (단 passive_to_active, voc_samples 갱신)
│   ├ cx_rules_common_mistakes.docx             ★갱신 (대대적)
│   ├ cx_part4_prompt_meta.docx                 ★신규
│   ├ cx_editorial_policy.docx                  ★신규
│   ├ cx_voc_scenario_misclaim.docx             ★신규
│   └ cx_voc_edit_initial_draft.docx            ★신규
│
├ 정답데이터1/  (메시지검토 시트 30건 본체 — v5.20 원본 보존)
│   └ cx_goldens_01a~01f_review_samples.docx (6개, 모두 신뢰도 HIGH)
│
├ 정답데이터2/  (2차 개선 666건 카드)
│   ├ cx_goldens2_derivatives.docx (28건)       ★신규
│   ├ cx_goldens2_product.docx (25건)           ★신규
│   ├ cx_goldens2_credit_loan.docx (24건)       ★신규
│   ├ cx_goldens2_settlement.docx (28건)        ★신규
│   ├ cx_goldens2_misc.docx (23건)              ★신규
│   ├ cx_goldens2_marketing.docx (18건)         ★신규
│   ├ cx_goldens2_pension.docx (7건)            ★신규
│   ├ cx_exceptions_misuyong.docx (35건)        ★신규 (NEGATIVE)
│   └ 정답데이터2.xlsx (원본 보관)
│
├ tools/  (운영 도구, RAG 미반영)
│   ├ extract_rich_text_sample.py
│   ├ classify_5axis_sample.py
│   ├ classify_all_distribution.py
│   ├ generate_card_sample_v2.py
│   ├ generate_all_cards.py     ← 정답데이터3·4 갱신용 재사용 도구
│   ├ generate_new_rag_docx.py
│   └ pii_scan.py
│
├ deployment_guide.md     (배포 체크리스트)
├ rollback_playbook.md    (사고 시 롤백 절차)
├ log_schema.md           (4-tuple 로그 스키마)
├ raci_matrix.md          (책임 분담)
├ change_note.md          (현업용 1페이지)
└ operation_manual.md     (이 파일)
```

## 🔄 정답데이터3·4 갱신 절차

회사가 정답데이터3 (3차 개선) 또는 정답데이터4 (4차 개선) xlsx를 발간하면:

```bash
# 1. 새 xlsx를 정답데이터3/ 폴더에 둔다
mkdir C:/dev/guide/정답데이터3
mv 정답데이터3.xlsx C:/dev/guide/정답데이터3/

# 2. tools/generate_all_cards.py를 정답데이터3에 맞게 수정
#    - XLSX_PATH = 정답데이터3.xlsx 경로
#    - 시트 이름 매핑 (1차/2차/3차/4차 동일하면 그대로)

# 3. 실행
python tools/generate_all_cards.py

# 4. 결과 docx 정답데이터3 폴더에 생성됨

# 5. PII 스캔
python tools/pii_scan.py

# 6. RAG에 새 docx 임베딩

# 7. 옛 정답데이터1·2 카드 처분 결정 (archive vs 유지)
#    - 같은 msg_code의 새 버전이 있으면 옛 카드 archive (vector DB에서 제거)
#    - archive 폴더에 보관 (사람 추적용)
```

## 📊 운영 모니터링 (매주)

`log_schema.md` 참조. 매주 점검할 메트릭:

- 입력 메시지 수 (채널별·도메인별)
- 사용자 채택률 (accept ≥ 70% 유지)
- 해요체 비율 (행동 요청, 50%↑ 유지)
- ☎ 제거율 (100% 유지)
- 형식적 인사 출현 (5%↓ 유지)
- 카드 검색 명중률 (50%↑ 유지)
- G8 발생률 (v5.22 후처리 도입 후 측정)
- 사고 보고 (0건 유지)

## 🚨 사고 대응

`rollback_playbook.md` 참조. 트리거 조건 발생 시 1시간 이내 v5.20 복원.

## 🔧 트러블슈팅

### 카드 검색 안 됨
- 도메인별 키워드 부족 가능성
- 카드 본문에 도메인 명사가 풍부한지 확인 (예: 신용·만기·연장)
- HyDE 한 줄(`이 사례는...`)이 사용자 입력과 톤 일치하는지 확인

### G8 글자 누락 발생
- v5.21에선 자가 검수로 못 잡음. v5.22 후처리 검증기 트랙 별도 진행
- 임시 대응: 사용자가 발송 전 결과 확인

### 비결정성 (같은 입력 다른 출력)
- temperature 통제 안 됨. RAG 운영팀에 협조 요청
- 카드 검색 자체는 안정적. LLM 샘플링 문제

### 카드 마커 `<v2>` `<v3>`가 출력에 노출됨
- 시스템 프롬프트의 출력 형식 룰 강화 필요
- v5.21.1 패치로 출력 검수 강화 검토

## 📞 운영 책임자

- HTS 개발팀: 시스템 프롬프트·카드·도구 운영
- 금융소비자보호팀: 카드 콘텐츠 검수
- 디지털마케팅팀: UX Mi-Tone 운영 (별도)
- IT 인프라팀: RAG vector DB 운영

## 📝 변경 이력

- v5.21 (2026-04-26): 톤 매트릭스, 검수자 페르소나, 정답데이터2 카드 도입, 다이어트 (840→639줄)
- v5.20 (2026-04-24): 0번 룰, 10대 금지, 3단계 검증, cx_rules_common_mistakes 도입
- v5.19 (2026-04-23 이전): 초기 버전
