# v75 남은 작업 (2026-04-05)

## 현재 상태
- 국면전환 후보1 프로덕션 적용 완료 (텔레그램 +14.3%, 3메시지 OK)
- OHLCV 전종목 수집 완료 (3,221종목, 1,287거래일)
- CP=FG: Growth Top 10 100% 일치 확인. 풀 파이프라인 미완.

## OHLCV 완료 후 순서

### Step 1: 데이터 검증 (2분)
- [ ] 신규 OHLCV 파일 저장 확인 (all_ohlcv_*_full.parquet)
- [ ] 표본 3일치 시총 1000억+ 커버리지 100% 확인
- [ ] 기존 종목 가격 일치 확인 (수정주가)

### Step 2: DART 14개 수집 (~2분)
- [ ] dart_collector로 14개 핀셋 수집
- [ ] 수집 후 fs_dart 존재 확인

### Step 3: BT 재생성 (~12분)
- [ ] 기존 bt_v75/ 삭제 → 신규 OHLCV로 재생성
- [ ] 표본 1일 먼저 → 종목 수 확인 (예상 260+)
- [ ] 4종 모멘텀 + 126일 필터

### Step 4: 그리드서치 (~65분)
- [ ] take_profit 추가: [+0.20, +0.30, +0.50, None]
- [ ] 2a-coarse(6m+12m) → 2a-fine(top50×4mom) → 2b(규칙+take_profit)
- [ ] 2c WF → 2d FDR → 2e 안정성
- [ ] Borda+Pareto 최종 선정

### Step 5: 국면전환 서치 (~5분)
- [ ] 2단계: Quick screen → Top 200 run_regime
- [ ] 방어 15+ × 공격 12+ × 규칙 58+

### Step 6: 결과 비교
- [ ] 기존(1665종목) vs 신규(3221종목) 결과 차이
- [ ] 전략이 바뀌었는지 확인

### Step 7: CP=FG 풀 파이프라인 검증
- [ ] 방어/공격 각각 CP main 실행 → FG ranking 비교
- [ ] 유니버스 수 + Top 20 종목 + 팩터 점수

### Step 8: 프로덕션 최종 반영
- [ ] regime_indicator.py 파라미터 확정
- [ ] state/ ranking 재생성 (재표준화 포함)
- [ ] 텔레그램 테스트 (TEST_MODE, 개인봇)
- [ ] 트레일링 경고 메시지 구현

### Step 9: 커밋

## 현재 프로덕션 파라미터 (후보1)
- 규칙: B126_40_7d (시총1000억+ 126일+ MA120 위 40%, 7일 확인)
- 방어: V15Q25G15M45 g=0.5 6m E7X12S5 sl=-10%
- 공격: V30Q0G55M15 g=0.7 12m E5X12S3 sl=-12% trail=-20%
- 현재 국면: boost (브레스 59.5%)

## 완료된 코드 수정
- regime_indicator.py: 후보1 파라미터, B126_40 규칙, 7일 확인
- send_telegram_auto.py: 국면별 ENTRY/EXIT/SLOTS/SL 동적 적용, 시스템 수익률 수정
- run_daily.py: OHLCV 증분 수집 Step 0.3, 브레스 기반 국면 판단
- turbo_simulator.py: run_regime(), take_profit, 4종 모멘텀
- fast_generate_rankings_v2.py: 4종 모멘텀 저장, 126일 필터, FWD_PER 삭제
- create_current_portfolio.py: 126일 필터, FWD_PER 삭제
- strategy_b_multifactor.py: FWD_PER 삭제
