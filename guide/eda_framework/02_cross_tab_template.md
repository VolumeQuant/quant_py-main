# 채널 × 도메인 × 패턴 Cross-tab 빈 템플릿 (v1)

작성일: 2026-05-04
범위: 정답데이터1 (30) + 정답데이터2 (521) = 551건 전수 EDA용
사용: 데이터 도착 후 셀 빈도 채움. (TBD) → 실제 카운트 또는 %

---

## 1. 채널 × 도메인 (총 케이스 카운트)

행: 채널 / 열: 도메인 / 셀: 케이스 수

| 채널 \ 도메인 | credit_loan | derivatives | product | settlement | pension | marketing | process | misc | exceptions | (합계) |
|---|---|---|---|---|---|---|---|---|---|---|
| LMS 고지/공지/안내 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - | (TBD) | (TBD) | - | (TBD) |
| LMS 마케팅 | - | - | - | - | - | (TBD) | - | - | - | (TBD) |
| SMS | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| 카카오 알림톡 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - | (TBD) | (TBD) | (TBD) | (TBD) |
| 이메일 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - | (TBD) | (TBD) | (TBD) | (TBD) |
| 뉴스레터 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - | (TBD) | (TBD) | (TBD) | (TBD) |
| VOC | - | - | - | - | - | - | - | (TBD) | - | (TBD) |
| Exception | - | - | - | - | - | - | - | - | (TBD) | (TBD) |
| (기타·미분류) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| **(합계)** | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | **551** |

**참고 (메모리 통계 기반 사전 추정):**
- 정답데이터2: 521건 (1차 144 + 2차 132 + 3차 110 + 4차 135)
- 정답데이터1: 30건
- HANDOFF: LMS 194 / VOC 4 / exceptions 18+20 (정답데이터2.xlsx 기준 카드)

---

## 2. 도메인 × 라벨 (HIGH/MEDIUM/LOW/NEGATIVE)

| 도메인 \ 라벨 | HIGH | MEDIUM | LOW | NEGATIVE | EVAL_ONLY | (합계) |
|---|---|---|---|---|---|---|
| credit_loan | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| derivatives | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| product | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| settlement | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| pension | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| marketing | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| process | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| misc | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| exceptions | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| **(합계)** | **17** | **137** | **275** | **38** | (TBD) | **467 카드** |

**참고:** v5.21 카드 = msg_code 중복 제거 후 467건 (메모리 명시)

---

## 3. 채널 × ■ 블록 명칭 빈도

행: 채널 / 열: ■ 블록 코드 (라벨링 사전 D 카테고리 참조)

| 채널 \ 블록 | BLK.AC.* | BLK.NAE.* | BLK.SUB.* | BLK.MV.* | BLK.MAT.* | BLK.URL.* | BLK.DOM.* | BLK.MAR.* | BLK.UI.꼭확인 | BLK.QA.문의 |
|---|---|---|---|---|---|---|---|---|---|---|
| LMS | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - | (TBD) | (TBD) |
| LMS 마케팅 | - | - | - | - | - | (TBD) | - | (TBD) | (TBD) | (TBD) |
| SMS | (TBD) | (TBD) | - | - | - | - | - | - | - | - |
| 알림톡 | (TBD) | (TBD) | (TBD) | - | - | (TBD) | - | - | (TBD) | (TBD) |
| 이메일 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - | (TBD) | (TBD) |
| 뉴스레터 | (TBD) | - | - | - | - | (TBD) | - | - | - | (TBD) |
| VOC | - | - | - | - | - | - | - | - | - | - |

---

## 4. 채널 × 도입·종결·기호 패턴

| 채널 \ 패턴 | OPN.HONOR.A | OPN.NAME.B | CLS.ANN | CLS.DONE | CLS.CAN | CLS.PLAN | CLS.REQ | SYM.PHONE☎변환 |
|---|---|---|---|---|---|---|---|---|
| LMS | (TBD) | - | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| LMS 마케팅 | (TBD) | - | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| SMS | - | - | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| 알림톡 | (TBD) | - | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| 이메일 | (TBD) | - | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| 뉴스레터 | (TBD) | - | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| VOC | - | (TBD) | - | - | - | - | (TBD) | (TBD) |

---

## 5. 채널 × 줄 분리·시간·후미 본문

| 채널 \ 패턴 | LN.PARA | LN.BLK_GAP | LN.AFTER_HONOR | LN.TAIL | TM.HHMM | TM.HOURS | KAK.7DAY |
|---|---|---|---|---|---|---|---|
| LMS | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - |
| LMS 마케팅 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - |
| SMS | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - |
| 알림톡 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) |
| 이메일 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - |
| 뉴스레터 | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - |
| VOC | (TBD) | (TBD) | (TBD) | (TBD) | (TBD) | - | - |

---

## 6. 도메인 × ■ 블록 시퀀스 (대표 패턴)

각 도메인별 등장 빈도 ≥10% ■ 블록 시퀀스 패턴:

| 도메인 | 대표 시퀀스 1 | 대표 시퀀스 2 | 대표 시퀀스 3 |
|---|---|---|---|
| credit_loan | (TBD) | (TBD) | (TBD) |
| derivatives | (TBD) | (TBD) | (TBD) |
| product | (TBD) | (TBD) | (TBD) |
| settlement | (TBD) | (TBD) | (TBD) |
| pension | (TBD) | (TBD) | (TBD) |
| marketing | (TBD) | (TBD) | (TBD) |
| process | (TBD) | (TBD) | (TBD) |
| misc | (TBD) | (TBD) | (TBD) |

---

## 7. 라벨 × 패턴 (HIGH 카드만 = "그대로 복사 안전")

HIGH 라벨 17건은 "정답이 가장 명확한 검수 통과 사례" — 시스템 프롬프트 EX 후보 우선순위 1.

| HIGH 카드 ID | 도메인 | 채널 | ■ 블록 시퀀스 | 시스템 프롬프트 EX 채택? |
|---|---|---|---|---|
| (TBD-1) | (TBD) | (TBD) | (TBD) | (검토) |
| (TBD-2) | (TBD) | (TBD) | (TBD) | (검토) |
| ... | ... | ... | ... | ... |
| (TBD-17) | (TBD) | (TBD) | (TBD) | (검토) |

---

## 8. NEGATIVE 38건 분석 (차단·반례 학습용)

NEGATIVE = 가이드 룰 미수용 영역. 가이드 적용 자제, 원안 가깝게 유지.

| NEGATIVE 카드 ID | 도메인 | 채널 | 미수용 사유 | 시스템 프롬프트 차단 룰 |
|---|---|---|---|---|
| (TBD-1) | (TBD) | (TBD) | (TBD) | (TBD) |
| ... | ... | ... | ... | ... |
| (TBD-38) | (TBD) | (TBD) | (TBD) | (TBD) |

---

## 채움 절차 (데이터 도착 후)

1. **1단계**: 정답데이터_xlsx_dump.txt 통독 → 케이스별 채널·도메인·라벨 분류
2. **2단계**: Section 1 (채널×도메인 카운트) 채움 → 분포 확인
3. **3단계**: Section 2 (도메인×라벨) 채움 → HIGH/MEDIUM/LOW 분포
4. **4단계**: Section 3-5 (채널×패턴) 채움 → 빈도 % 산출
5. **5단계**: Section 6 (도메인 시퀀스) 채움 → ■ 블록 cheat sheet 도출
6. **6단계**: Section 7 (HIGH 카드) → 시스템 프롬프트 EX 후보 결정
7. **7단계**: Section 8 (NEGATIVE) → 차단 룰 도출
