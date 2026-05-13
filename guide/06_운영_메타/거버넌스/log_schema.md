# Mi-Tone v5.21 로그·텔레메트리 스키마

> 사후 분석을 위해 모든 요청·응답을 4-tuple로 기록. v5.21 효과 측정 + 사고 원인 분석 필수.
>
> ⚠️ **사용자 검증 필요**: PII 마스킹 방식(SHA-256), 보관 기간(90일), 권한 분배 등은 사용자 회사 정보보호 정책·운영팀 결정사항으로 대체. 본 문서는 스키마 제안이며 실제 운영팀 협조 후 확정.

## 🎯 4-tuple 로그 스키마

```json
{
  "request_id": "uuid",
  "timestamp": "2026-04-26T14:30:00+09:00",
  "user_id": "직원 사번 (해시 처리)",
  "input_message": "원문 메시지 (최대 1500자)",
  "channel_inferred": "SMS | LMS | 알림톡 | 이메일 | 뉴스레터 | VOC",
  "type_inferred": "공지성 | 고지성 | 마케팅 | 안내성 | VOC | VOC_misclaim | VOC_edit",
  "retrieved_cards": [
    {
      "card_id": "cx_goldens2_credit_loan_LN102",
      "label": "MEDIUM",
      "domain": "credit_loan",
      "similarity_score": 0.85
    },
    ...
  ],
  "retrieved_docs": [
    {
      "doc": "cx_principle_05_translation_artifacts",
      "similarity_score": 0.78
    },
    ...
  ],
  "cited_in_output": ["cx_goldens2_credit_loan_LN102"],
  "output": {
    "case_type": "1 (기본 교정) | 2 (광고 경고) | 3 (원문 준수) | 4 (UX 거절) | 5 (인젝션 방어)",
    "corrected_text": "교정 결과 본문",
    "modifications_count": 5,
    "modifications": [
      {
        "tag": "번역투 제거",
        "original": "...",
        "corrected": "...",
        "evidence_page": "가이드 32p"
      }
    ]
  },
  "user_action": {
    "decision": "accept | edit | reject",
    "edit_diff": "사용자가 수정한 부분 (decision=edit일 때)",
    "feedback": "선택. 자유 텍스트"
  },
  "metrics": {
    "g8_chars_dropped": 0,
    "haeyo_ratio_action_request": 0.85,
    "tel_symbol_removed": true,
    "formal_greeting_present": false
  }
}
```

## 📊 로그 활용

### A. v5.20 vs v5.21 비교 분석

- 같은 입력에 대한 v5.20 출력과 v5.21 출력 비교 (A/B 카나리)
- 사용자 채택률 (decision=accept) 차이
- 메트릭별 평균 비교

### B. 사고 원인 분석

- 어떤 입력에서 어떤 카드·docx가 검색됐고 LLM이 무엇을 인용했는지
- 카드 마커(`<v2>` `<v3>`) 해석 정확도
- tie-breaker 룰 작동 여부

### C. 카드 검색 명중률 측정

- 입력의 도메인과 검색된 카드의 도메인 일치 여부
- 카드 인용률 (검색됐는데 인용 안 됨 / 인용 안 됐는데 검색됨)
- LOW·NEGATIVE 카드의 잘못된 활용 케이스

## 🔧 로그 운영 룰

### 보관 기간
- 90일 (사고 분석 충분)
- 보관 후 자동 삭제 또는 익명화

### PII 마스킹
- `user_id`: SHA-256 해시
- `input_message`: 자동 PII 스캔 (`tools/pii_scan.py`) 후 발견 시 [REDACTED]
- `output.corrected_text`: 동일

### 권한
- HTS 개발팀: 전체 접근
- 금융소비자보호팀: 메트릭만 조회 (개별 메시지 X)
- 정보보호부: 보안 사고 시 전체 조회

## 📈 매주 리포트 항목

- 입력 메시지 수 (채널별·도메인별)
- v5.21 출력 채택률 (accept / edit / reject)
- A축 메트릭 (해요체 비율·☎ 제거율·형식적 인사 출현 등)
- 카드 검색 명중률
- G8 발생률 (v5.22 후처리 검증기 도입 후 측정)
- 사고 보고 0건 확인

## ⚙️ 로그 수집 — 운영팀 협조 필요

이 로그 수집은 RAG 운영팀(IT 인프라팀)이 실제 시스템에서 4-tuple 정보를 추출해 저장해야 가능. 사용자가 RAG 시스템을 못 만지므로 운영팀 협조 요청 필수.

**요청 내용**:
> Mi-Tone v5.21 배포 시점부터 4-tuple 로그 (input·retrieved·output·user_action) 수집을 활성화해 주십시오. PII 마스킹 후 90일 보관. 메트릭 항목은 위 스키마 참조.
