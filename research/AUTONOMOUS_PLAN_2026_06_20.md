# 자율주행 계획 — 국면 조기위험탐지 리서치 (2026-06-20, 사용자 12h 외출/전권위임)

## 목표
현행 게이트(KOSPI종합 MA20/80/5d)는 데드크로스가 평균 -23% 빠진 뒤 터지는 **후행신호**.
"더 일찍 위험을 피하되 휩쏘로 수익을 안 죽이는" 신호를 **광범위 리서치(논문/GitHub/웹) → 우리 데이터로 백테스트 → 정직 검증**으로 찾는다. 없으면 "왜 다 실패하는가" 철저 문서화.

## baseline (이겨야 할 기준, down-only state)
- 전체 Calmar **4.08**, MDD **25.9%**, CAGR 105.7%, 약세장(22-23) 0.61
- 합격선: MDD↓ & Calmar 비악화(>3.9) — 또는 Calmar 개선. 휩쏘(현금일수/전환횟수) 같이 측정.
- 이미 기각: 빠른MA(휩쏘 Cal→2.0~2.8), 동일가중/ex메가/KOSPI200/KOSDAQ150 게이트, 드로다운서킷(-X%→현금: MDD22%지만 Cal 1.34·절반현금), 변동성타겟팅(독), HY레벨단독(노이즈), 외국인순매수(흡수).

## 단계 (총 ~12h)
- [진행중] **A. 리서치 워크플로우** wf_1075e533-467 (8각도 병렬 → 검증 → 종합 → 비평) → 구현가능 후보 랭킹+스펙.
- **B. 백테스트 R1**: 각 후보 단독으로 down-only BT 적용(`_regime_early_defense.py` 패턴 재사용). baseline 대비 Cal/MDD/약세/휩쏘.
- **C. 합격 후보 정밀검증**: WF 3블록 + OOS train/test + 인접CV + LOWO + 약세장 사고체크 (TTM/down-only 규율).
- **D. 조합**: 살아남은 신호 + 현행 MA를 OR/AND/가중 결합 — 단독보다 나은가.
- **E. 종합·결정**: 강건 개선이면 **deploy-ready 패키지**(코드+검증) 준비. 없으면 음성결과 문서.
- **F. 기록·보고**: 연구파일 커밋, CLAUDE.md/메모리 갱신, 개인봇 중간/최종 보고.

## ★자율 정책 (전권 위임받았으나 안전 우선)
- 리서치·백테스트·검증·**연구파일 커밋/푸쉬**: 자유 진행.
- ★**프로덕션 게이트 변경 / state 재생성 / 채널 발송 = 자동 배포 금지.** deploy-ready로 준비만, 복귀 시 승인. (corpaction 교훈 + 채널=비가역 외부발송. 신규기능 배포 철칙).
- 노이즈 우위·과적합은 기각. best-vs-best 금지(고정config OOS). 모든 판정 수치근거.
- 개인봇 중간보고는 OK(채널 X). 자격증명/비번 등 민감정보 커밋 금지.

## 진행 로그 (자율주행 중 갱신)
- 2026-06-20: 계획 수립, 리서치 워크플로우 기동, 하트비트 스케줄.

### 진행 로그 (자율주행)
- **리서치 회수**: 워크플로우 막판 spend-limit 실패했으나 61후보/44verdict 트랜스크립트서 회수(`research/_ew_recovered.json`). 최대테마=breadth(21), ML-changepoint(10), credit-macro(8). priority5 13개.
- **B1 breadth 게이트 검증** (`backtest/_breadth_gate_bt.py`): 현재 b200=21%(평균39%, 2022최저8%)=광범위약세 확인(직감 맞음). BUT 게이트로는 전부 baseline 열위(Cal 4.05→1.6~2.8). 약세장 MDD는 크게↓(b200>40% AND MA: 약세 MDD 24.7→12.9%, 전체MDD 25.9→24.0%) but 전체 Cal 4.05→2.49(현금 1172일=불참). 드로다운브레이커와 동일함정: 브레드스약세=소형주(미보유)라 게이트시 강세장 불참. → breadth 하드게이트 기각, soft(슬롯축소) overlay 잔여검증 예정.
- **B2 변동성계열** (`_vol_regime_bt.py`): RV term-structure(RV5/RV60)·하방반편차·signed-jump·단면분산 전부 게이트로 baseline 열위(발동시 Cal 2.7~3.7) 또는 무효(SJ>-0.5는 4.13이나 13일만 발동=노이즈). 기각.
- **B3 soft 슬롯축소 overlay** (`_soft_overlay_bt.py`, flagship): ★고정3슬롯=4.077/25.9% baseline 재현 검증 후 — b200약세시 3→2→1 축소하면 Calmar↓ AND **MDD 오히려 악화(29~43%)**. 이유: 슬롯축소=집중도↑=분산효과 상실, 약세장 1종목몰빵이 더 위험. ★3슬롯 분산 자체가 리스크컨트롤. 기각.
- **중간결론**: 모든 조기방어(브레드스 하드/소프트·드로다운·빠른MA·변동성)가 실패. 약세 MDD는 줄여도 강세 수익을 더 잃거나(불참) 집중도로 MDD 악화. MA20/80+3슬롯이 최적점. 유일 작동 레버=현금버퍼(메타).

### ★자율주행 1차 완료 (2026-06-20)
- **최종결론**: 조기방어 신호 전부 기각(baseline MA20/80/5+3슬롯 최적 확정). 유일 레버=현금버퍼(70/30 Cal4.14/MDD19.2%). 브레드스는 진단지표로만.
- **산출물**: `EARLY_WARNING_FINDINGS_2026_06_20.md`(종합), BT 6계열(`_breadth_gate_bt`·`_vol_regime_bt`·`_soft_overlay_bt`·`_regime_early_defense`·`_regime_oos_decide`·`_regime_kospi200_test`), 회수후보(`_ew_recovered.json`), 진단지표 모듈(`breadth_diagnostic.py`, 미배포). CLAUDE.md+메모리 갱신. 전부 커밋·푸쉬. 개인봇 중간보고 발송.
- **미완(외부데이터)**: KR 회사채-국고채 신용스프레드(ECOS 한은 API 필요, KRX probe는 서버타임아웃). 크로스에셋(DXY/KRW). HMM/ruptures(미설치). → 동일 defend-on-weakness 구조라 극복 가능성 낮음, 후속과제.
- **배포 대기(복귀 후 승인)**: breadth_diagnostic 푸터 wire(표시전용). 그 외 프로덕션 무변경.

### 하트비트 (KRX throttle 지속)
- data.krx.co.kr 여전히 ReadTimeout(throttle) — KR 신용스프레드 후보 시도 불가(KRX/ECOS 필요). busywork 안 함.
- ★자율주행 핵심성과: 섹터브레드스 50%스케일 발견·검증·배포 완료(commit b7a15b008~dfe4c8a45). Cal 4.08→4.36, 약세 24.7→19.2%. advisory + 추적수익률 기계반영.
- 신용스프레드는 KRX 쿨다운 후 1회 시도(저우선). 사용자 복귀·재개입 상태.
