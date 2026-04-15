# 다음 세션 작업 브리핑 (2026-04-15 → 집PC 이어받기)

## 현재 상태 요약

**v77.1 → v79 전환 완료 + FnGuide PIT 보강 완료.**

2026-04-15 회사PC에서 수행:
1. Phase 3~8 전수 재탐색 → v79 확정
   - 공격: V15Q5G50M30 3f_gp(0.5/0.3/0.2) 12m E3X6S3
   - 방어: V30Q15G15M40 2f_rev_oca(0.7) 6m-1m E3X6S7
   - 국면: KP_MA200_7d (v77.1의 5d → 7d)
   - Crash Cash 제거 (방어 자체로 충분 견고)
2. 코드 수정 커밋 `c34a86390`: regime_indicator.py + send_telegram_auto.py + run_daily.py + SYSTEM_MAP.md + state 재생성 스크립트
3. **FnGuide rcept_dt 역추적** (DART 기반, 약 130만 건 매칭) → PIT 정확도 강화
4. **FnGuide 매일 증분 로직** `run_daily.py` Step 0.1에 추가
5. **state/ + bt_extended/ 전체 재생성** (FnGuide PIT 반영, 4워커 병렬)
6. Phase 8 재측정 + Top 10~15 재검증 + 인접 안정성 + WF 재확인
7. 공지/전환 메시지 금융 컨설팅 리라이트 적용

**프로덕션 상태**: v79 작동 중. 스케줄러 `QuanT_DailyPipeline` 평일 16:00 자동.

## 반드시 먼저 읽을 문서

1. **`C:\dev\SYSTEM_MAP.md`** — 영구 지도. 파일별 하드코딩 위치, 파이프라인, 데이터 경로, 외부 의존성, 체크리스트. **전략 교체 시 반드시 이 문서 기반으로 맹점 제로 확인**.
2. `C:\dev\CLAUDE.md` — v79 전략 + FnGuide PIT 섹션 + (d)(d')(e) 필터 설명
3. `C:\Users\user\.claude\projects\C--dev\memory\project_v79_final.md` — v79 확정 경위
4. `C:\Users\user\.claude\projects\C--dev\memory\feedback_blindspot_elimination.md` — 7라운드 맹점 제거 프로토콜
5. `C:\dev\backtest\PHASE8_REPORT.md` — Phase 8 상세 분석

## 이어서 할 수 있는 작업 (선택)

### A. FnGuide PIT 추가 검증
- 역추적 기본값(연 90일/분기 45일) 적용 비율 확인
- DART 미매칭 종목 리스트 분석

### B. 잔여 이슈 정리 (fc29095d4의 6개 미해결)
- MA120 필터 주석-동작 불일치 (이슈 1)
- 지주사 NaN 대체 로직 (이슈 2)
- 멀티팩터 스코어링 내부 NaN 드롭 (이슈 5)
- final 저장 시 price 조건 탈락 (이슈 6)
- (e) 필터 섹터 의존성 (이슈 7)
- universe_count 메타데이터 MA120 전 값 (이슈 8)

### C. ranking_manager.py wr 재계산 중복 제거 (경미)

### D. kospi_yf 첫 컬럼 NaN fallback (send_telegram line 339, 경미)

## 주의사항

- **채널 전송 금지** — 모든 테스트는 `TEST_MODE=1` 개인봇 (`TELEGRAM_PRIVATE_ID=7580571403`). 채널 전송은 사용자 명시 지시만.
- **base_date 명시 필수** — `run_daily.py` 수동 실행 시 오늘 기준 아닌 당일 종가 확인 후. 장중 실행 금지 (4/15 사고 교훈).
- **push 전 사용자 승인** — 자동 커밋/푸시 이미 발생한 이력 있음 (run_daily.py 말미). 수동 작업 시 확인.
- **스케줄러** — `schtasks /Change /TN "QuanT_DailyPipeline" /DISABLE` 으로 임시 비활성, 작업 후 `/ENABLE` 재활성.
- **7라운드 맹점 제거** — 프로덕션 변경 계획 제시 전 반드시 수행 (feedback_blindspot_elimination.md).

## 환경

- Python: `C:/Users/user/miniconda3/envs/volumequant/python.exe`
- 경로: `C:\dev\` (git root), 백테스트 `C:\dev\backtest\`, 데이터 `C:\dev\data_cache\`, 프로덕션 ranking `C:\dev\state\` + `C:\dev\state\defense\`
- 집PC도 동일 경로 가정. 다르면 확인 (feedback_cross_pc_validation.md).

## 커밋 상태 (집PC 이어받기 직전)

- `c34a86390` feat(v79): v79 코드 전환 커밋
- 추가 일괄 커밋: state 재생성본 + bt_extended 재생성본 + DART/FnGuide 증분 + FnGuide rcept_dt 이식 + 문서
- **집PC에서 git pull 먼저** 하고 작업 시작.
