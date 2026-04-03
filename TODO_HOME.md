# 집PC 작업 목록 (2026-04-03)

## 오늘 완료한 것

### Grid Search v73 (317,358조합 × 5 Rounds)
- **R1 (Boost 공격형)**: V15Q5G65M15 g_rev=1.0 E3/X4/S3 — Calmar=2.00, CAGR=95%, MDD=47.6%
- **R2b-1 (Core 안정형)**: V20Q20G40M20 g_rev=0.2 E5/X7/S5 corr=0.5 — Calmar=2.53, CAGR=55%, MDD=21.6%
- 최종 결정: **Core 70% + Boost 30%** (투 트랙)
- 채널(부모님): Core만 / 개인봇: Core + Boost

### 핵심 발견
1. Revenue Acceleration(매출 가속도)이 Growth 최강 서브팩터
2. 영업이익 변화(oca)는 쓸모없음
3. 매출총이익 < 매출액
4. MA120 유지 필수 (제거 시 OOS 붕괴)
5. 거래대금 30억 / 시총 2000억~3000억 → 알파 감소, 1000억 유지
6. 상관관계 필터: G집중형에 효과 없음, 균형형에만 유효
7. FWD_BONUS 비활성화

### 생성된 파일
- `state/ranking_boost_*.json` — Boost 프로덕션 ranking (36일)
- `state/ranking_core_*.json` — Core 프로덕션 ranking (36일)
- `state/bt_2b/` — Revenue Acceleration bt 파일 (1,277일)
- `backtest/turbo_simulator.py` — 56x 가속 시뮬레이터
- `backtest/fast_generate_rankings_v2.py` — 27x 가속 bt 생성기
- `backtest/grid_search_final.py` — 3워커 병렬 그리드서치

### 프로덕션 상태
- 스케줄러: 활성화 (v72로 내일 아침 06:00 동작)
- 개인봇 테스트 메시지: Boost/Core 전송 완료

---

## 집에서 해야 할 것

### 1. 프로덕션 적용 (최우선)
- [ ] 기존 `send_telegram_auto.py` 복사 → `send_telegram_boost.py`, `send_telegram_core.py`
- [ ] 각각 ranking 파일 경로 변경 (ranking_boost_*, ranking_core_*)
- [ ] 진입/퇴출 조건 변경:
  - Core: ENTRY_RANK=5, EXIT_RANK=7, MAX_SLOTS=5
  - Boost: ENTRY_RANK=3, EXIT_RANK=4, MAX_SLOTS=3
- [ ] 전송 대상 변경:
  - Core: 채널 + 개인봇
  - Boost: 개인봇만
- [ ] `create_current_portfolio.py` 복사 → Boost용 + Core용
  - Boost: 가중치 V15Q5G65M15, g_rev=1.0, FWD_BONUS 끄기
  - Core: 가중치 V20Q20G40M20, g_rev=0.2, Revenue Acceleration 계산 추가, FWD_BONUS 끄기
- [ ] `run_daily.py` 수정: Boost + Core 순차 실행
- [ ] 스케줄러 업데이트

### 2. Revenue Acceleration 프로덕션 구현
- [ ] `strategy_b_multifactor.py`에 `_calc_rev_acceleration()` 추가
  - rev_accel = 현재 TTM YoY - 이전 TTM YoY
  - 12분기(3년) 데이터 필요
- [ ] Core용 create_current_portfolio에서 oca_z를 rev_accel로 교체
- [ ] 테스트: 오늘자 ranking_core와 비교

### 3. 상관관계 필터 (Core만)
- [ ] send_telegram_core.py에서 매수 후보 선정 시 60일 상관관계 체크
- [ ] 기존 보유 종목 + 같은 날 신규 vs 후보 체크
- [ ] threshold: 0.5

### 4. 시스템 수익률
- [ ] Core/Boost 각각 시스템 수익률 계산
- [ ] 합산 수익률 (70:30 가중)
- [ ] 메시지에 표시

### 5. 페이퍼 트레이드 (1~2주)
- [ ] Core/Boost 병렬 운용
- [ ] 실제 추천 종목 확인
- [ ] 잡주 빈도 모니터링
- [ ] 실전 전환 판단

---

## 참고: 전략 상세

### Core (안정형 70%)
```
V_W, Q_W, G_W, M_W = 0.20, 0.20, 0.40, 0.20
G_REVENUE_WEIGHT = 0.2  (매출성장률20% + Revenue Acceleration80%)
ENTRY_RANK = 5
EXIT_RANK = 7  (weighted_rank > 7이면 매도)
MAX_SLOTS = 5
CORR_FILTER = 0.5
FWD_BONUS = 비활성화
```

### Boost (공격형 30%)
```
V_W, Q_W, G_W, M_W = 0.15, 0.05, 0.65, 0.15
G_REVENUE_WEIGHT = 1.0  (매출성장률100%)
ENTRY_RANK = 3
EXIT_RANK = 4  (weighted_rank > 4이면 매도)
MAX_SLOTS = 3
CORR_FILTER = 없음
FWD_BONUS = 비활성화
```
