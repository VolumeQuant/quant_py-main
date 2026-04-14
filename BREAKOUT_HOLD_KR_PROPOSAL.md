# 한국 v77에 Breakout Hold 적용 검증 제안서

> 미국 v74의 Breakout Hold (strict) 인사이트를 한국 환경에 적용하기 위한 분석 + 실행 가이드.
> 작성: 2026-04-11 (미국 v75 검증 직후)

---

## 1. 미국 v74 Breakout Hold 요약

### 동기
- TTMI (4/10 +13% 폭등) 같은 케이스: 매도 신호 떴지만 진짜 상승 흐름 → 더 잡을 수 있었음
- 4/10 후 12개월 +476% 갈 종목을 일찍 빠지면 알파 손실

### 미국 조건 (strict)
모두 만족 시 매도 신호에서 **2일 유예**:
1. 최근 20거래일 종가 +25% 이상
2. ntm_90d → ntm_current 순방향 (EPS 동행 상승)
3. rev_up30 / num_analysts >= 0.4 (애널리스트 합의)
4. 현재가 > MA60

### 미국 검증 결과 (33시작일 multistart)
| 항목 | no_hold | strict |
|------|---------|--------|
| 평균 수익 | +25.6% | **+31.1%** |
| MDD 최악 | -18.2% | -18.2% (동일!) |
| 차분 | - | **+5.4%p** |

조건 너무 빡빡(V0)하면 트리거 0회, 조건 너무 관대(V4)하면 false positive로 손실. **strict가 sweet spot**.

---

## 2. 한국 v77 환경 분석

### 데이터 가용성

| 미국 조건 | 한국 가용? | 대체 신호 |
|---------|---------|---------|
| 20일 +25% 가격 | ✅ OHLCV에서 직접 | 동일 |
| ntm_90d → ntm_current 동행 | ❌ forward EPS 부족 | **rev_z > 0** (매출 z-score 양수) |
| rev_up30/N >= 0.4 | ❌ 애널리스트 데이터 부족 | **op_margin_z > 0** (영업이익률 z-score 양수) |
| price > MA60 | ✅ OHLCV에서 계산 | 동일 |

### 한국 ranking JSON 가용 필드
```
value_s, quality_s, momentum_s
rev_z, oca_z, rev_accel_z, gp_growth_z, op_margin_z, cfo_growth_z
mom_6m_s, mom_6m1m_s, mom_12m_s, mom_12m1m_s
price, sector, ticker, name, composite_rank, score
```

### 한국 변형 (strict)
모두 만족 시 매도 신호에서 **2일 유예**:
1. 최근 20거래일 종가 +25% 이상 ← 동일
2. **rev_z > 0** (매출 z-score 양수, 평균 이상 매출 성장)
3. **op_margin_z > 0** (영업이익률 z-score 양수, 평균 이상 수익성)
4. price > MA60 ← 동일

또는 더 까다롭게 (V0_매우엄격):
- 25일 +30%, rev_z > 0.5, op_margin_z > 0.5, MA60

---

## 3. TurboSimulator 통합 방안

### 옵션 A: TurboSimulator 직접 수정 (권장)
`backtest/turbo_simulator.py`의 `_run_loop_regime_hot` 함수에 hold 로직 추가:

```python
def _run_loop_regime_hot(...):
    portfolio = {}
    grace_days = {}  # 신규: hold 유예 일수 추적
    ...

    # === EXIT 부분 수정 ===
    if portfolio:
        to_remove = []
        for col, ep in portfolio.items():
            should_exit = False
            ...
            if not should_exit:
                if wrank_arr[col] > exit_param:
                    should_exit = True

            # 신규: Breakout Hold 체크
            if should_exit and use_breakout_hold:
                if check_breakout_hold(price_arr, cur_row, col, ranking_data, hold_params):
                    grace = grace_days.get(col, 0)
                    if grace < hold_params['max_grace']:
                        grace_days[col] = grace + 1
                        should_exit = False

            if should_exit:
                to_remove.append(col)
                grace_days.pop(col, None)
```

### 옵션 B: 외부 wrapper (간단)
TurboSimulator를 그대로 두고, **post-processing**으로 hold 시뮬:
- Baseline 결과의 trade log를 받아서
- 각 exit를 hold 조건 체크 후 2일 연장
- 가격 배열에서 +2일 후 가격으로 재계산

→ 정확성 떨어지지만 시간 빠름. 첫 검증용.

---

## 4. 검증 단계 (실행 가이드)

### Phase 1: Baseline 확인
```bash
cd C:/dev/claude-code/quant_py-main
python backtest_breakout_hold.py
# 예상: CAGR=186%, Cal=6.62 (v77 spec과 일치)
```

### Phase 2: Hold 변형 4종 비교

| 변형 | rev_z 임계 | op_margin_z 임계 | 가격 +X% | 일수 |
|------|----------|----------------|--------|-----|
| V0_매우엄격 | > 0.5 | > 0.5 | +30% | 25일 |
| **V1_엄격 (한국 strict)** | **> 0** | **> 0** | **+25%** | **20일** |
| V2_중간 | > 0 | > 0 | +20% | 15일 |
| V3_관대 | > -0.5 | > -0.5 | +15% | 10일 |

### Phase 3: 인접 안정성
- V1_엄격 주변 변형 (rev_z > -0.2/0/0.2/0.5) × (가격 20/25/30%)
- 미국에서 발견한 패턴: 너무 관대하면 false positive로 손실

### Phase 4: Walk-Forward (5년 데이터)
- 2021~2023 학습 / 2024~2025 검증
- 2021~2024 학습 / 2025~2026 검증
- 학습 1등이 검증에서도 1등인지 확인

### Phase 5: 다양한 metric 비교
- Calmar (한국 그리드서치 기준)
- MDD, Sharpe, Sortino
- 미국과 달리 5년 데이터라 모두 신뢰 가능

---

## 5. 예상 효과 (정성적)

### 긍정적 가설
- 한국에도 SNDK/TTMI 같은 폭발적 성장주가 존재
- 매도 신호 후에도 추세 지속하는 종목 있음
- z-score 기반 hold는 미국 forward 데이터 대신 합리적 대체

### 리스크
- z-score는 절대값 아닌 상대값 → 시장 전체 약세장에서도 양수 가능
- 한국 시장 특성: 미국보다 회전 빠름, 폭등 종목 적음
- 5년 데이터에서 hold 효과가 작을 수도 (단발 폭등 케이스 부족)

### 예상 결과 범위
- **Calmar 6.62 → 6.5~7.5** (-2% ~ +13%)
- **MDD 28.1% → 25~30%**
- **CAGR 186% → 180~200%**

미국에서 +5.4%p 향상이 났지만, 한국은 다음 이유로 효과 작을 수 있음:
1. 한국은 이미 trailing_stop -15% 적용 중 → 일부 hold 효과 이미 캡처
2. z-score 기반 hold는 forward EPS 기반보다 신호 약함
3. 한국 ranking 기반(국면전환)이 미국보다 정교함

---

## 6. 실행 시 주의사항

### 데이터 손상 복구
2026-04-11 시점에 quant_py-main의 parquet 파일들이 모두 손상 발견:
- `all_ohlcv_20190603_20260409.parquet`
- `bench_proxy.parquet`
- `kospi_yf.parquet`

원인: pyarrow 버전 호환성 추정 (`Repetition level histogram size mismatch`)

복구 방법:
1. pyarrow 버전 확인: `pip show pyarrow`
2. 다운그레이드 또는 fastparquet 시도
3. 또는 데이터 재수집 (pykrx)

### 백테스트 전 확인
- bt_test_A/ranking_*.json 무결성 (5+년 분, 일별)
- regime_dict 생성 (KOSPI > MA200, 5일 연속)
- TurboSimulator 정상 작동

---

## 7. 결론

### 한국 적용 가능성: ✅ 가능
- 데이터 가용 (z-score 기반 변형)
- 인프라 정교 (TurboSimulator)
- 5+년 데이터로 walk-forward 검증 가능

### 권장 적용 우선순위
1. **데이터 손상 복구** (parquet)
2. **Phase 1 baseline 확인** (CAGR=186%)
3. **Phase 2 hold 변형 4종 비교** (Calmar 기준)
4. **결과에 따라 채택/폐기 결정**

### 미국 vs 한국 차이
- **미국**: 41일 한계로 multistart 필수, hold이 명확한 알파
- **한국**: 5+년 데이터로 walk-forward 가능, hold 효과는 trailing_stop과 중복 가능

### 최종 권고
미국 v75 (V9h 매출 보너스)는 즉시 적용 (이미 검증). 한국 Breakout Hold은:
1. 데이터 손상 복구 후
2. 별도 세션에서 직접 검증
3. 효과 +2%p 이상이면 채택, 미만이면 보류 (이미 trailing_stop이 잡고 있음)
