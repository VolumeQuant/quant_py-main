# v74 프로덕션 적용 계획

## 전략 요약
- **방어(Cal3)**: V20Q20G45M15, g_rev=0.1(매출10%+가속도90%), E4/X10/S5
- **공격(Boost)**: V15Q5G65M15, g_rev=1.0(매출100%), E3/X4/S3
- **국면전환**: KOSPI>MA60 AND KOSDAQ>MA60 → Boost (3일 연속 확인)
- **성과**: CAGR +157%, MDD -29%, Calmar 5.37

## 적용 단계

### 1단계: Revenue Acceleration 구현 (strategy_b_multifactor.py)
**목표**: Cal3 모드의 G팩터에 매출 가속도 사용

**변경**:
- `_calc_revenue_acceleration()` 메서드 추가
  - 현재 TTM YoY - 이전 TTM YoY
  - `_calc_ttm_yoy()`를 2번 호출 (최근 8분기, 이전 8분기)
- `calculate_growth_factors()`에서 `이익변화량` 대신 `매출가속도` 저장
- 환경변수 `USE_REV_ACCEL=1`로 제어

**검증**: 삼성전자(005930) 가속도 계산 → bt_2b ranking과 비교

### 2단계: 국면 판단 모듈 (regime_indicator.py 신규)
**목표**: 매일 KOSPI/KOSDAQ MA60 확인 + 3일 확인 로직

**구현**:
```python
def get_current_regime():
    # pykrx에서 KOSPI/KOSDAQ 종가 + MA60 조회
    # 3일 연속 확인 (state/regime_state.json에 상태 저장)
    # return 'boost' or 'cal3'
```

**저장**: `state/regime_state.json` — 현재 모드, 연속 일수, 전환 이력

### 3단계: 팩터 가중치 동적 설정 (strategy_b_multifactor.py)
**목표**: 국면에 따라 V/Q/G/M 가중치 변경

**변경**:
- 환경변수 또는 config로 가중치 주입
  - Cal3: V_W=0.20, Q_W=0.20, G_W=0.45, M_W=0.15, G_REV=0.1
  - Boost: V_W=0.15, Q_W=0.05, G_W=0.65, M_W=0.15, G_REV=1.0
- `calculate_multifactor_score()`에서 환경변수 읽기

### 4단계: 진입/퇴출 동적 설정 (ranking_manager.py)
**목표**: 국면에 따라 E/X/S 변경

**변경**:
- `get_entry_exit_params(regime)` 함수 추가
  - Cal3: ENTRY=4, EXIT=10, SLOTS=5
  - Boost: ENTRY=3, EXIT=4, SLOTS=3

### 5단계: 파이프라인 통합 (create_current_portfolio.py)
**목표**: 국면 판단 → 해당 모드로 포트폴리오 생성

**흐름**:
```
1. regime = get_current_regime()  # 2단계
2. 환경변수 설정 (V_W, Q_W, ..., G_REV, USE_REV_ACCEL)
3. 기존 파이프라인 실행 (strategy_b가 환경변수 읽음)
4. ranking JSON에 regime 메타데이터 추가
```

### 6단계: 텔레그램 메시지 수정 (send_telegram_auto.py)
**목표**: 현재 모드 표시 + 모드별 매매 조건

**변경**:
- Signal 메시지 상단에 `🛡️ 방어 모드` 또는 `⚔️ 공격 모드` 표시
- 매매 조건: 모드에 따라 E/X/S 다르게 표시
- calc_system_returns: 국면전환 반영 (과거 ranking의 regime 메타데이터 사용)

### 7단계: run_daily.py 수정
**목표**: 국면 판단을 파이프라인 최초에 실행

**흐름**:
```
0. DART 증분
1. 국면 판단 (regime_indicator.py)
2. 포트폴리오 생성 (국면에 맞는 파라미터)
3. 텔레그램 전송
4. git push
```

### 8단계: 테스트 + 검증
- 과거 3일(3/25, 3/26, 3/27) 재생성하여 bt_2b ranking과 비교
- 개인봇으로 테스트 메시지 전송
- 국면 전환 시뮬레이션 (3/4 코스닥 이탈 사례)

## 주의사항
- Revenue Acceleration은 8분기(2년) 데이터 필요 → 신규 상장 종목 제외될 수 있음
- 국면 전환 시 기존 보유 종목은 전면 교체 (3일 확인으로 휘소 방지)
- state/regime_state.json 백업 필수 (국면 상태 유실 방지)
- 첫 배포 시 Cal3 모드로 시작 (안전)

## 검증 체크리스트
- [ ] Revenue Acceleration이 bt_2b와 동일한 값 산출
- [ ] 국면 판단이 2026년 일지와 일치
- [ ] Cal3 모드 ranking이 기존 ranking_core와 유사
- [ ] Boost 모드 ranking이 기존 ranking_boost와 유사
- [ ] 텔레그램 메시지 정상 표시
- [ ] 시스템 수익률 계산 정상
