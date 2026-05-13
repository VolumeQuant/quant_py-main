# 04. 데이터 사이언스 / EDA 전문가 검토

작성일: 2026-05-04
검토자 페르소나: RAG 학습 데이터 편향·표본 검정·라벨 신뢰도·임베딩 anchor 정량 분석을 10년 한 응용 통계 박사 (NLP retrieval 평가 specialty).

---

## HIGH 칭찬 1개

**HC1. EDA 사전(`01_pattern_labeling_dictionary.md`)의 4계층 라벨 + 빈 슬롯(Q. NEW.001~) 설계는 데이터 과학 관점에서 정석 중의 정석.**

- 라인 7: `각 패턴 = '[CATEGORY.SUBCATEGORY.CODE]' 식별자. 데이터 도착 시 빈도 채워 넣음.`
- 라인 256-262: `## Q. 신규 슬롯 (정답2 521건에서 새로 발견될 패턴) ... | NEW.001 | TBD | TBD |`
- 코드북(codebook) 형태의 calibration-ready 구조라 inter-annotator 합의 측정(Cohen's kappa)·label drift tracking·새 라벨 발견 시 OOV(out-of-vocabulary) 누적 기록이 한 파일에서 끝남. 실제 521건 라벨링 후 kappa ≥0.75 검증만 추가하면 통계적으로 방어 가능한 EDA가 됨. HANDOFF의 카드 분포 통계와 cross-reference도 깔끔.

---

## 비판 9개

### HIGH-1. 50건 표본 편향 — 미보정 채로 "필수 ≥80%" 등급화에 직접 사용

- 파일: `03_sample_vs_full_comparison.md`
- 라인 14-16 verbatim: `| 채택 기준 | "검토필요 또는 blank 449건 후보 중 도메인 분포 균형 50건" | 전체 |\n| 표본 편향 위험 | "검토필요" = 의견 분기되는 어려운 케이스 → 평이한 케이스 누락 가능 | - |`
- `01_pattern_labeling_dictionary.md` 라인 268: `**필수 (≥80%)**: 모든 시스템 프롬프트 룰 본문 + EX에 verbatim 등장 의무`
- 데이터 사이언스 근거: 50건은 stratified random sample이 아닌 "검토필요 편향 표본". 521건 모집단에 대한 95% 신뢰구간을 정규근사로 계산 시 비율 50%인 패턴의 margin of error는 ±13.9%p (z=1.96, finite population correction 적용 후 ±13.2%p). "■ 꼭 확인해 주세요 34%"는 실제로는 21%~47% 사이 어디든 가능. ≥80% 임계치 기반 "필수" 등급화는 표본 크기 부족으로 type-II 오류(실제 필수 패턴을 조건부로 강등) 위험이 큼. 또한 selection bias가 random하지 않은 의견-분기-편향이라 추정량 자체가 unbiased하지 않음.
- 패치: 라인 268의 등급화 기준에 다음 단서 추가:
  ```
  **필수 (≥80%, 95% CI 하한 ≥70%)**: ...
  **조건부 (30~80%, 또는 50건 표본 95% CI가 30~80% 걸침)**: ...
  ```
  `03_sample_vs_full_comparison.md` Section 3에 "50건 % / 95% CI 하한 / 95% CI 상한 / 551건 %" 4컬럼 구조로 변경. 521건 라벨링 완료 전 시스템 프롬프트 라인 201(`정답 50건 전수 EDA 기반 enumeration`)에서 "50건"을 "잠정 50건 (551건 검증 대기)"로 표기 변경.

---

### HIGH-2. RAG retrieval bias 미해결 — LMS 1.5%(VOC 4건/272건) 편향이 시스템 프롬프트 룰만으로 차단된다는 가정의 무근거

- 파일: `01_CX/PROD/system_prompt_v6.0_cx_flat_LF_escaped.txt`
- 라인 102-103 verbatim: `[★ VOC 우선 anchor — RAG가 LMS 카드 끌어와도 무시 ★]\n채널 = VOC면 [참고자료]에서 "[미래에셋증권]" 말머리·■ 블록·5단 구조 가진 카드는 형식 참조 절대 금지.`
- HANDOFF 라인 127-130: `1. **VOC 답변에서 "안녕하세요 고객님" 인사 첫 줄 누락 가능성** (RAG LMS 편향)` 미해결로 명시.
- 데이터 사이언스 근거: VOC : LMS = 4 : 268 (1.5%). top-k retrieval에서 코사인 유사도가 LMS 카드와 유사하면 prior probability만으로도 LMS가 호출될 base rate가 98.5%. 시스템 프롬프트 텍스트 룰은 in-context guardrail일 뿐 retrieval distribution 자체를 바꾸지 못함. Bayes' rule 관점: P(LMS|query)=P(query|LMS)P(LMS)/P(query). P(LMS)=0.985 prior가 너무 강함. NDCG@5나 MRR로 "VOC query → VOC card" 상위 검색률을 측정하지 않은 채 in-prompt anchor에 의존하는 건 unbounded bias.
- 패치: HANDOFF 라인 419의 "VOC 카드 추가 4 → 16~20" 권고를 우선순위 P0으로 격상. 521건 라벨링 즉시 직후 minimum viable 추가는 16개 (LMS:VOC = 17:1 → 12:1로 prior 완화). 더 정량적으로는 retrieval 단계에서 channel filter(query에 VOC 신호 발견 시 retrieval space에서 LMS 카드 제외 또는 reranker로 channel score 가중)를 적용하라는 retrieval-side patch를 HANDOFF에 명시 추가. 텍스트 prompt만으로는 RAG bias 해결 X.

---

### HIGH-3. Same-format-opposite-meaning 카드 그룹 — embedding cosine similarity 측정값 부재

- 파일: `HANDOFF_TO_COWORK.md`
- 라인 297-307 verbatim: `### 같은 형식·정반대 의미 카드 그룹 (위험)\n\n| 카드 1 | 카드 2 | 위험 |\n|---|---|---|\n| [UW216] 파생결합상품 월수익 **지급** | [UW102] 파생결합상품 월수익 **미지급** | 정반대 |`
- `system_prompt_v6.0_cx_flat_LF_escaped.txt` 라인 430-432: `예외 (입력 우선, 카드 부분 참고):\n- 카드와 의미 정반대 (UW216 지급 vs UW102 미지급, FF201 발주 vs FF202 중단)`
- 데이터 사이언스 근거: "지급" vs "미지급"은 character-level Levenshtein distance 1, 한국어 임베딩 모델(예: ko-sbert-sts)에서 cosine similarity가 통상 0.85~0.95로 매우 높음. UW216·UW102가 같은 도메인 + 같은 키워드 + 부정어 1개 차이라면 retrieval top-3 안에 둘 다 들어올 가능성이 높고, 모델은 의미 negation을 무시하고 "구조 anchor 동일 → 형식 모방 OK"로 처리할 위험. 이를 정량화하려면: (1) 모든 카드 페어의 코사인 유사도 분포 측정 후 ≥0.85인 페어 식별, (2) 그 중 negation token("미·불·안·X")이 한쪽에만 있는 페어 retrieval에서 둘 다 호출되는 빈도(false co-retrieval rate) 측정. 현재 두 측정 모두 부재.
- 패치: `02_cross_tab_template.md` Section 8(NEGATIVE 38건) 다음에 새 Section 9 추가:
  ```
  ## 9. High-similarity opposite-meaning 카드 페어 모니터링
  | 카드 페어 | cos sim | negation token | retrieval co-occurrence rate (top-5) | 조치 |
  | UW216 vs UW102 | (TBD) | "미"지급 | (TBD %) | metadata에 polarity flag |
  | FF201 vs FF202 | (TBD) | "중단" | (TBD %) | ... |
  ```
  cos sim ≥0.85 + co-occur ≥10% 페어는 카드 ID 옆에 polarity 메타데이터(positive/negative)를 붙여서 retrieval 후 LLM input에 plain-text disambiguator 주입.

---

### HIGH-4. 라벨 imbalance + HIGH 17건이 시스템 프롬프트 EX에 안전 채택됐는지 검증 부재

- 파일: `02_cross_tab_template.md`
- 라인 46 verbatim: `| **(합계)** | **17** | **137** | **275** | **38** | (TBD) | **467 카드** |` (HIGH:MEDIUM:LOW:NEGATIVE = 17:137:275:38, 단 HANDOFF 라인 274-280 "16:102:76 / NEGATIVE 38"과 수치 mismatch까지 존재).
- 라인 113-122 Section 7: HIGH 카드 17건 ID·도메인·시퀀스·EX 채택 여부가 모두 (TBD).
- `system_prompt_v6.0_cx_flat_LF_escaped.txt` 라인 920-1072 EX-T1 4건 + EX-T2 8건 = 총 12 EX. 그러나 실제 HIGH 17개 ID와의 cross-reference 부재.
- 데이터 사이언스 근거: 17:137:275:38은 macro-F1 평가 시 HIGH 클래스가 micro-average에 묻혀 보이지 않음. classifier 학습 시 HIGH 같은 minority class에 SMOTE/oversampling 또는 class-weighted loss를 거는 게 표준. 시스템 프롬프트 EX는 모델 anchor → 12 EX 중 HIGH ratio가 몇 %인지 확인 안 한 채 채택하면 LOW (39%)·NEGATIVE 사례를 EX 형식으로 anchor할 위험. 또한 HANDOFF 16 vs cross-tab 17의 1건 mismatch는 dedupe 기준 또는 라벨링 불일치 — Cohen's kappa로 측정 안 됨.
- 패치: (1) HANDOFF 라인 274-279 표와 cross-tab 라인 46 표 정합성 검증 후 일원화. (2) cross-tab Section 7에 즉시 채워야 할 컬럼 추가: `HIGH 카드 ID | 검수 통과일 | 시스템 프롬프트 EX-T1/T2 채택 | inter-annotator kappa`. (3) CX 시스템 프롬프트 라인 911 verbatim: `★ 아래 12건은 회사 금융소비자보호팀·연금업무개발팀·증권운영팀 검수 통과 정답입니다.` — 12건 중 HIGH 라벨 건수와 ID를 명시 (예: "HIGH 8건, MEDIUM 3건, NEGATIVE 1건 — anti-pattern anchor"). HIGH 17 중 EX 미채택 건은 EX-T2 메모로 추가하거나 NEGATIVE label 만큼은 EX에서 제외.

---

### MEDIUM-1. 도메인 8종 분류가 운영 분류 기반 — 의미 공간 클러스터링과 mismatch 가능성 미검증

- 파일: `02_cross_tab_template.md`
- 라인 13: `| 채널 \\ 도메인 | credit_loan | derivatives | product | settlement | pension | marketing | process | misc | exceptions | (합계) |`
- 데이터 사이언스 근거: credit_loan / derivatives / product / settlement / pension / marketing / process / misc는 미래에셋증권 운영 부서 기준 분류로 보임. 그러나 임베딩 공간에서 자연 클러스터링(K-means k=8 또는 HDBSCAN)을 돌리면 "settlement(정산)"과 "process(프로세스)"가 한 클러스터로 묶이거나, "derivatives" 안에 ELS(원금손실)·DLC(해외)·CFD가 분리될 수 있음. 운영 도메인 ≠ 의미 도메인이면 RAG retrieval 정확도가 떨어짐 (silhouette score < 0.3 가능). 521건 라벨링 후 K-means clustering으로 자연 클러스터를 비교하지 않은 채 8종 도메인 라벨로 retrieval reranker를 짜면 misalignment.
- 패치: `02_cross_tab_template.md` Section 1 후에 다음 검증 절차 추가:
  ```
  ## 1.5 도메인 라벨 vs 임베딩 클러스터 일치도
  1. 521건 TOBE 본문 임베딩 (ko-sbert-sts 또는 사용 모델)
  2. K-means k=8 클러스터링 → silhouette score
  3. 운영 도메인 라벨과 클러스터 ID의 adjusted Rand index (ARI) 측정
  4. ARI < 0.5면 도메인 분류 재정의 또는 hierarchical clustering으로 sub-domain 도출
  ```

---

### MEDIUM-2. 재현율 산출 방법론(Section 6)이 정성적 — Levenshtein·BLEU·ROUGE 부재

- 파일: `03_sample_vs_full_comparison.md`
- 라인 135-139 verbatim:
  ```
  재현율 측정 방법:
  1. 521건 ASIS를 시스템 프롬프트로 변환 시뮬레이션
  2. TOBE와 비교 — 핵심 패턴 (■ 블록 명칭·도입·종결·줄 분리) 일치 여부
  3. 재현율 = 일치 건수 / 521 × 100%
  ```
- 데이터 사이언스 근거: "일치 여부"는 binary subjective judgment. 텍스트 생성 평가의 표준 지표는: (1) character-level Levenshtein normalized distance (= 1 - editdist/max_len), (2) BLEU-4 (n-gram overlap), (3) ROUGE-L (longest common subsequence), (4) BERTScore (semantic). "■ 블록 명칭" 같은 structural anchor는 정규식 매칭 + structural F1 (TOBE 안 ■ 블록 set vs 출력 set의 precision/recall) 따로 측정해야 함. 단일 binary "일치" → 모델 fail mode (예: "■ 청약정보" vs "■ 청약 정보" 띄어쓰기 1개 차이)가 모두 균등 카운트됨.
- 패치: 라인 135-139를 다음으로 교체:
  ```
  재현율 측정 방법 (정량 4축):
  1. 텍스트 유사도: char-level normalized Levenshtein (TOBE vs 출력) — 평균·중앙값·≥0.9 비율
  2. n-gram 일치: BLEU-4 (smoothing method 1) — 평균
  3. 구조 일치: ■ 블록 명칭 set의 F1, ■ 블록 시퀀스 순서 Kendall's tau
  4. 사실 무결성: placeholder #{...} 토큰 set의 recall (입력 placeholder 누락률)
  종합 재현율 = 위 4지표 weighted (0.3 / 0.2 / 0.3 / 0.2)
  ```

---

### MEDIUM-3. Few-shot anchor 분열 (CX 12 EX vs UX 7 EX vs 직원용 7 EX) — anchor 학습 비용·일관성 측정 부재

- 파일들:
  - `01_CX/PROD/system_prompt_v6.0_cx_flat_LF_escaped.txt` 라인 909: `【검수 통과 사례 12선 — 학습용】` (TIER1 4 + TIER2 8 = 12)
  - `03_UX/PROD/system_prompt_v6.0_ux_flat_LF_escaped.txt` 라인 469: `【대표 예시 7선 — 학습용】`
  - `02_직원용/PROD/system_prompt_internal_memo_v11.0.txt` 라인 344: `【참고 예시 — 7 케이스 (가이드 본문 변환 사례)】`
- 데이터 사이언스 근거: Few-shot in-context learning 연구(Brown 2020, Min 2022)는 (a) 예시의 형식 일관성이 정확도보다 더 중요, (b) 도메인 간 EX 형식 불일치는 cross-domain transfer를 저해. CX 12개 / UX 7개 / 직원용 7개로 시스템마다 다른 anchor 수는 모델이 "어느 시스템 기준 출력 형식을 채택할지" 분기 학습 비용 증가. 게다가 CX EX는 Full format 4 + 메모 8 hybrid라 같은 시스템 안에서도 형식 mixed. 적절한 K값(few-shot K) 결정은 통상 ablation study (K=3, 5, 8 비교 후 dev set NDCG)로 정하는데 본 프로젝트는 ablation 부재.
- 패치: 3개 시스템 모두 동일한 K=5 또는 K=7로 통일 결정. CX는 TIER2 8개 메모를 TIER1 Full 형식 4개에 흡수 통합하거나, 메모만 별도 cheatsheet 외부화. EDA 산출물(`02_cross_tab_template.md`)에 새 Section 추가:
  ```
  ## 10. Few-shot K ablation (521건 라벨링 후)
  | K | CX 재현율 | UX 재현율 | 직원용 재현율 | byte 평균 |
  | 3 | (TBD) | (TBD) | (TBD) | ... |
  | 5 | (TBD) | ... | ... | ... |
  | 7 | (TBD) | ... | ... | ... |
  ```

---

### LOW-1. Cross-tab 템플릿이 채널×도메인 단순 카운트 위주 — 정보이론 기반 지표(KL divergence·perplexity) 부재

- 파일: `02_cross_tab_template.md`
- 라인 9-24 (Section 1) + Section 2-6 모두 단순 frequency table.
- 데이터 사이언스 근거: 50건 vs 551건의 분포 비교 시 단순 % 차이만 보면 "표본 대표성" 판단이 약함. 정보이론적으로는 KL divergence D(P_50 || P_521)가 표준. KL≥0.1이면 "이 표본은 모집단 대표 X" 결론 가능. 또한 패턴 분포의 entropy(H = -Σp log p)를 측정하면 "도메인이 얼마나 균등한가"(높을수록 균등) 정량 비교 가능. 시스템 프롬프트 EX 분포가 모집단 entropy를 따라가는지도 측정 가능 (cross-entropy).
- 패치: `02_cross_tab_template.md` Section 5 후에 추가:
  ```
  ## 5.5 정보이론 지표
  | 비교 | 값 | 임계치 | 진단 |
  | KL(P_50, P_521) 채널 분포 | (TBD) | <0.1 OK | (TBD) |
  | KL(P_50, P_521) 도메인 분포 | (TBD) | <0.1 OK | (TBD) |
  | H(채널) 50건 | (TBD) | - | - |
  | H(채널) 521건 | (TBD) | - | - |
  | cross-H(EX 분포, P_521) | (TBD) | minimize | EX 채택 가이드 |
  ```

---

### LOW-2. SYM.PHONE/TRI/DOT/SQ "100% (해당)" 표기 — denominator 미명시 분모 모호

- 파일: `01_pattern_labeling_dictionary.md`
- 라인 185-188 verbatim:
  ```
  | SYM.PHONE | ☎ → ■ 문의 | 100% (해당 27/27) | (TBD) |
  | SYM.TRI | ▶ → ■ / - | 100% (해당) | (TBD) |
  | SYM.DOT | ● → ■ / * | 100% (해당) | (TBD) |
  | SYM.SQ | □ → ■ | 100% (해당) | (TBD) |
  ```
- 데이터 사이언스 근거: "100% (해당 27/27)"은 SYM.PHONE만 분자/분모 명시. 나머지 3개는 분모 부재. 분모 1건짜리 100%는 noise일 가능성. recall=27/27=1.0이지만 신뢰구간(Wilson score) 95% 하한은 0.87 → "거의 항상 변환" 정도로만 결론 가능. 다른 3개도 동일 수준 신뢰구간 표기 필요.
- 패치: 라인 185-188을 다음으로 교체:
  ```
  | SYM.PHONE | ☎ → ■ 문의 | 27/27 (100%, 95% CI 0.87~1.00) | (TBD) |
  | SYM.TRI | ▶ → ■ / - | (n/N TBD) | (TBD) |
  | SYM.DOT | ● → ■ / * | (n/N TBD) | (TBD) |
  | SYM.SQ | □ → ■ | (n/N TBD) | (TBD) |
  ```
  `01_pattern_labeling_dictionary.md` 라인 273 라벨링 절차에도 "분자/분모 둘 다 기록 + 95% CI 산출 (Wilson score)" 단계 추가.

---

## 요약 표

| 등급 | 번호 | 항목 | 핵심 위험 |
|---|---|---|---|
| HIGH | 1 | 50건 표본 편향 미보정 | type-II 등급화 오류 ±13.9%p |
| HIGH | 2 | RAG LMS 1.5% prior bias 미해결 | VOC retrieval 실패 base rate 98.5% |
| HIGH | 3 | Opposite-meaning 카드 cos sim 미측정 | UW216/102 false co-retrieval |
| HIGH | 4 | HIGH 17 vs EX 12 매칭 부재 + 16/17 mismatch | LOW/NEGATIVE anchor 오염 위험 |
| MEDIUM | 1 | 운영 도메인 ≠ 의미 클러스터 검증 부재 | retrieval reranker misalignment |
| MEDIUM | 2 | 재현율 정성 binary 판정 | fail mode 균등 가중 |
| MEDIUM | 3 | Few-shot K=12/7/7 분열 | cross-domain anchor 충돌 |
| LOW | 1 | KL/entropy 정보이론 지표 부재 | 표본 대표성 판단 약함 |
| LOW | 2 | SYM 100% 분모 미명시 | 신뢰구간 부재 |

---

한 줄 요약: HIGH 4건, 최위험 항목은 HIGH-2 (RAG LMS 1.5% prior가 시스템 프롬프트 in-context guardrail만으로는 차단 불가 — retrieval 단계 channel filter + VOC 카드 16건 이상 보강이 P0).
