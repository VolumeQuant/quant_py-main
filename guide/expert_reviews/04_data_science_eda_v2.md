# 04. 데이터 사이언스 / EDA 전문가 검토 v2 (가이드 backing 재정렬)

작성일: 2026-05-05
검토자 페르소나: RAG 학습 데이터 편향·표본 검정·라벨 신뢰도·임베딩 anchor 정량 분석 응용 통계 박사 (NLP retrieval 평가 specialty).
재정렬 원칙 (메모리 feedback_guide_backing 강제):
1. 모든 권고는 「고객중심 언어 가이드」(2026.02 발간) PDF backing 필수
2. 가이드 silent 항목은 권고 X — 백로그 분리 명시
3. § 등 비-한국 표기 금지. 법조항은 「법령명」 제○조 제○항
4. 권고 옆에 가이드 페이지 의무
5. 가이드 PDF 추출본: `C:\dev\guide\04_가이드_원본\_pdf_추출본\`
6. 권고 전 Grep backing 검증 의무

---

## 0. 사전 결론 — EDA 영역 가이드 backing 현황

가이드 PDF 추출본 11개 파일 (`p9-12`, `p26-32`, `p33-50`, `p57-67`, `p63`, `p79-80`, `p82-117`, `p99`, `p119-128`, `p127`, `p128`, `p145-146`) Grep 결과:

| 검색어 | hit | 비고 |
|---|---|---|
| 표본 / 샘플 / 모집단 | 0건 | 가이드 silent |
| 통계 / 신뢰구간 / 분포 | 0건 | 가이드 silent |
| 빈도 / 라벨 / 라벨링 | 0건 | 가이드 silent |
| RAG / 임베딩 / 클러스터 | 0건 | 가이드 silent |
| 편향 | 1건 (p145 Insightful 콘텐츠 원칙 — "특정 자산·상품·지역·기업에 대한 편향 없이 균형 잡힌 시각") |
| 데이터 | 5건 (p33-50 Insightful "구체적 데이터 중시", p82-117 UX 공백 메시지 "데이터가 없을 때") — 모두 EDA 통계 X, 콘텐츠 톤 룰 |
| 재현율·평가 | "평가 & 단정 표현" 1건 (p33-50) — 평가 어휘 톤 룰, EDA 평가 X |

**결론**: 가이드는 **EDA 통계 룰 영역 거의 전체 silent**. v1 권고 9개 중 가이드 backing 가능한 항목은 0개 (모두 자체 발명 통계 권고). 단 "정답데이터 자체 metadata"(가이드 페이지 분포·HIGH/MEDIUM/LOW 라벨 분류)는 가이드 적용 결과 도출물이라 가이드 페이지 인용 가능한 EDA 항목이 일부 존재.

---

## 1. v1 권고 9개 backing 재판정

| 번호 | v1 권고 요지 | 가이드 backing | 분류 | 처리 |
|---|---|---|---|---|
| HC1 | 4계층 라벨 + 빈 슬롯 코드북 칭찬 | silent (코드북 설계는 통계 운영) | 운영 보조 | **유지 가능** — 단 "정석" 언급은 메타 평가, 가이드 외 운영 도구 칭찬으로 명시 |
| HIGH-1 | 50건 표본 95% CI 보정 (margin of error ±13.9%p) | silent (통계 신뢰구간) | 자체 발명 통계 | **백로그 분리** — `guide_check_backlog.md`로 이동 |
| HIGH-2 | RAG retrieval bias (LMS 1.5% prior, NDCG@5·MRR) | silent (RAG·정보검색) | 자체 발명 통계 | **백로그 분리** — 단 "VOC 카드 4 → 16~20 보강"은 데이터 수량 권고로 운영 보조 박스 OK |
| HIGH-3 | Same-format-opposite-meaning 카드 cos sim 측정 | silent (임베딩) | 자체 발명 통계 | **백로그 분리** — 단 "지급 vs 미지급" 의미 negation 구분은 가이드 9p Trustworthy(정확성) 정신과 부합 → 권고 톤 약화 가능 |
| HIGH-4 | HIGH 17 vs EX 12 mismatch + Cohen's kappa | partial (HIGH/MEDIUM/LOW 라벨 분류 자체는 정답데이터 metadata) | 일부 backing | **수정 후 유지** — "EX 12선이 HIGH 라벨 카드 위주로 구성됐는지 검증" 부분만 유지. kappa·classifier·SMOTE는 백로그. |
| MED-1 | 운영 도메인 vs 임베딩 클러스터 silhouette·ARI | silent | 자체 발명 통계 | **백로그 분리** |
| MED-2 | Levenshtein·BLEU·ROUGE·BERTScore 재현율 4축 | silent | 자체 발명 통계 | **백로그 분리** |
| MED-3 | Few-shot K=12/7/7 ablation | silent | 자체 발명 통계 | **백로그 분리** |
| LOW-1 | KL divergence·entropy 정보이론 지표 | silent | 자체 발명 통계 | **백로그 분리** |
| LOW-2 | SYM 100% 분모 명시 + Wilson CI | silent (분모 명시는 EDA 위생) | 자체 발명 통계 | **수정 후 유지** — "분자/분모 둘 다 기록"까지만 운영 위생, Wilson CI는 백로그 |

**결과**: v1 9개 비판 중 가이드 backing 명확하게 살릴 수 있는 비판 1.5개 (HIGH-4 일부, LOW-2 일부). 나머지 8개는 백로그.

---

## 2. v2 권고 — 가이드 backing 가능한 EDA 항목

### 가용 backing 카테고리

EDA 자체는 가이드 silent지만, **EDA 산출물이 가이드 적용 검증 도구**로 쓰이는 영역에선 가이드 페이지 인용 가능:

| 가이드 페이지 | 적용 EDA 항목 | backing 정신 |
|---|---|---|
| p9-12 (브랜드 보이스 4축) | 정답데이터 톤 라벨링 — "Client First / Trustworthy / Contributive / Insightful 4축에 부합하는가" | 가이드 9p verbatim |
| p26 (정중 어미) | 종결 표현 cross-tab (CLS.ANN/DONE/CAN/PLAN/REQ 빈도) — "다양한 어미 권장" 검증 | 가이드 26p verbatim |
| p27-31 (전문용어·중복·축약·긴 문장·강조) | 본문 정정 룰 적용 빈도 cross-tab | 가이드 27-31p verbatim |
| p32-33 (일본어·영어 번역투) | KOR.JAP/ENG 라벨 빈도 → 정답데이터 변환 패턴 검증 | 가이드 32-33p verbatim |
| p36 (호명 첫머리) | OPN.HONOR.A / OPN.NAME.B / OPN.NONE 빈도 | 가이드 36p verbatim |
| p59 (SMS 45자) | SMS.45 / SMS.1BLK 검증 | 가이드 59p verbatim |
| p60-62 (LMS 5단) | ■ 블록 시퀀스 검증 (말머리·요약·블록·꼭확인·문의) | 가이드 60-62p verbatim |
| p63-64 (LMS 마케팅 심의문구) | MAR.SIM3 / MAR.LEAD 검증 | 가이드 63-64p verbatim |
| p65-66 (알림톡 CTA·7일 만료) | KAK.7DAY / KAK.CTA 검증 | 가이드 65-66p verbatim |
| p67 (이메일) | 채널 = 이메일 빈도·형식 검증 | 가이드 67p verbatim |
| p79 (띄어쓰기·기호) | SYM.PHONE/TRI/DOT/SQ 변환 빈도 | 가이드 79p verbatim |
| p82-117 (UI 컴포넌트) | UX 도메인 컴포넌트 라벨 분포 | 가이드 82-117p verbatim |
| p99 (시스템 피동) | 본문 정정 패턴 빈도 | 가이드 99p verbatim |
| p108 (이벤트 카피·컨펌 셰이밍) | NEG.SHOCK 빈도 | 가이드 108p verbatim |
| p121-128 (VOC 톤·호명·변수화 X) | VOC.OPEN/4단/APO1/NO_BLK/NO_HEAD 검증 | 가이드 121-128p verbatim |
| p134 (한자어 순화) | KOR.SINO 빈도 | 가이드 134p verbatim |
| p137 (포용 언어) | 본문 정정 빈도 | 가이드 137p verbatim |

### 권고 (3건만 — backing 명확)

**REC-1 (가이드 backing). 정답데이터 라벨링 사전 cross-tab을 "가이드 페이지별 적용 빈도" 표로 재구성.**

- 파일: `01_pattern_labeling_dictionary.md` 라인 1-262
- 현재: 패턴 코드 카테고리(A~Q)별 정렬
- 패치: 카테고리별 정렬은 유지하되 **각 행의 "비고" 컬럼에 가이드 페이지 명시 의무화**.
  - 이미 일부 행은 명시됨 (예: 라인 28 "가이드 36p verbatim", 라인 41 "가이드 29p")
  - 미명시 행에도 가이드 페이지 보강:
    - 라인 156 ITM.CIRC `※ ~`: "(심의문구·수수료, 가이드 60p)" 명시되어 있으나 ITM.STAR(라인 155)는 페이지 부재 → 가이드 60p (■ 항목명·* 세부 표기) 추가
    - 라인 157 ITM.NUM `① ② ③ 단계별`: 가이드 65-66p 알림톡 단계 backing 추가
- 가이드 backing: 가이드 9-12p, 26-50p, 57-67p, 79p, 82-117p, 99p, 108p, 119-128p, 134p, 137p (전 페이지 verbatim)
- 효과: EDA 산출물이 "가이드 페이지 적용 검증 보고서"로 격상, 가이드 외 통계 권고에서 가이드 정합성 검증 도구로 정렬됨.

**REC-2 (정답데이터 metadata 활용). HIGH/MEDIUM/LOW/NEGATIVE 라벨은 정답데이터 자체 metadata — 라벨 정의 자체에 가이드 페이지 cross-reference 의무.**

- 파일: `02_cross_tab_template.md` 라인 33-46 (Section 2 도메인×라벨)
- 현재: HIGH:MEDIUM:LOW:NEGATIVE = 17:137:275:38 카운트만 표기
- 패치: 라벨 정의 캡션 추가 (가이드 페이지 인용 의무):
  - HIGH = "회사 검수 통과 + 가이드 9-12p 4축 + 60-62p 5단 + 79p 띄어쓰기·기호 모두 부합"
  - MEDIUM = "회사 검수 통과 + 가이드 부분 부합 (2-3축 OK, 1-2 항목 추가 정정 가능)"
  - LOW = "회사 검수 통과 + 가이드 정합성 약함 (관습 어투 잔존)"
  - NEGATIVE = "가이드 적용 미수용 영역 — 원안 가깝게 유지 (가이드 124p VOC 보존 정신 등 도메인 예외)"
- 가이드 backing: 가이드 9-12p (4축), 60-62p (5단), 79p (띄어쓰기·기호), 124p (VOC 보존)
- 효과: 라벨 = 가이드 적용 정합도 등급으로 정의되면 EDA 분석이 가이드 backing 직결.

**REC-3 (운영 위생, 가이드 silent — 운영 보조 박스). 분자/분모 표기 명시.**

- 파일: `01_pattern_labeling_dictionary.md` 라인 185-188 (SYM 카테고리)
- 현재: `100% (해당 27/27)`, `100% (해당)`, `100% (해당)`, `100% (해당)`
- 패치: 4개 모두 분자/분모 표기 (n/N) 의무. Wilson CI는 백로그 분리.
  - 예: `27/27 (100%)`, `(n/N TBD)`, `(n/N TBD)`, `(n/N TBD)`
- 가이드 backing: silent — 가이드 외 EDA 위생 룰. **운영 보조 박스에 분리 명시** ("EDA 위생: 분자/분모 표기 의무 (가이드 silent)").
- 효과: 분모 1건짜리 100%(noise 위험)와 분모 27건짜리 100%(robust)의 구분 가능.

---

## 3. 자체 발명 통계 권고 — 백로그 분리 명시

`guide_check_backlog.md`에 다음 항목 EDA 섹션 신설 및 이동:

| 백로그 ID | v1 출처 | 항목 | 가이드 silent 사유 | 향후 처리 |
|---|---|---|---|---|
| EDA-BL-1 | HIGH-1 | 50건 표본 95% CI margin of error ±13.9%p | 가이드 통계 룰 silent | 521건 라벨링 후 통계 검증 자체 운영 보조로 별도 문서 (가이드 외) |
| EDA-BL-2 | HIGH-2 | RAG retrieval bias (NDCG@5·MRR·channel filter) | 가이드 RAG 운영 silent | RAG 운영 보조 룰 (cf. CX backing audit Section 1 [참고자료 활용 (RAG)] 박스) |
| EDA-BL-3 | HIGH-2 잔여 | VOC 카드 4 → 16~20 보강 | 가이드 데이터 수량 silent | **부분 살림** — 가이드 121-128p VOC 톤 적용 안정성 위해 보강. 운영 보조 박스 ([RAG 카드 보강]) |
| EDA-BL-4 | HIGH-3 | Cos similarity ≥0.85 + negation token 페어 모니터링 | 가이드 임베딩 silent | RAG 운영 보조 |
| EDA-BL-5 | HIGH-4 잔여 | Cohen's kappa·SMOTE·classifier metric | 가이드 ML silent | 가이드 외 통계 검증 (별도 문서) |
| EDA-BL-6 | MED-1 | K-means silhouette·ARI 도메인 vs 클러스터 | 가이드 silent | RAG 운영 보조 |
| EDA-BL-7 | MED-2 | Levenshtein·BLEU·ROUGE·BERTScore 4지표 weighted | 가이드 silent | 시스템 출력 평가 운영 보조 |
| EDA-BL-8 | MED-3 | Few-shot K=3/5/7 ablation | 가이드 silent | 시스템 운영 보조 |
| EDA-BL-9 | LOW-1 | KL divergence·entropy 정보이론 | 가이드 silent | 표본 대표성 검증 운영 보조 |
| EDA-BL-10 | LOW-2 잔여 | Wilson score 95% CI | 가이드 silent | EDA 위생 운영 보조 |

백로그 처리 원칙:
- 가이드 silent ≠ 무가치. 단 가이드 PDF backing 없는 룰은 시스템 프롬프트 본문 또는 EDA framework 본문 권고에 직접 삽입 X.
- 운영 보조 박스 (EDA 운영 위생) 안에서 살림 가능. 박스 헤더 "(가이드 외 EDA·RAG 운영 보조)" 명시.
- backing audit Section 1 (CX) 라인 28 [참고자료 활용 (RAG)] 박스, Section 4 박스 분류 표와 정합.

---

## 4. v1 → v2 차이 요약

| 항목 | v1 | v2 |
|---|---|---|
| 칭찬 | HC1 (코드북 설계 "정석") | HC1 유지 (운영 보조 칭찬으로 정렬) |
| 비판 HIGH | 4건 (모두 통계·RAG·임베딩) | 1건 (HIGH-4 라벨 정의 가이드 backing 부분만, REC-2로 흡수) |
| 비판 MEDIUM | 3건 | 0건 (전부 백로그) |
| 비판 LOW | 2건 | 0건 (LOW-2 분자/분모만 REC-3로 운영 보조 박스로 살림) |
| 새 권고 | - | REC-1 (가이드 페이지 cross-ref 의무화) |
| 백로그 분리 | - | 10건 (EDA-BL-1 ~ EDA-BL-10) |

**결과**: v1 권고 9개 중 가이드 PDF backing 명확하게 시스템 프롬프트·EDA framework 본문에 살릴 수 있는 권고는 1.5개. 나머지는 백로그(가이드 silent — 운영 보조 박스 또는 별도 문서로 분리).

---

## 5. 한 줄 요약 (v2)

EDA 영역은 가이드 PDF 거의 전체 silent — v1 9개 비판 중 시스템 본문 살림 가능 1.5개 (HIGH-4 라벨 정의 + LOW-2 분자/분모), 나머지 7.5개는 `guide_check_backlog.md` EDA 섹션으로 이동. v2 신규 권고 REC-1·2·3는 모두 가이드 페이지 직접 인용 가능 항목 (라벨링 사전 가이드 페이지 cross-ref 의무화 + 라벨 정의 가이드 backing + 분자/분모 표기).
