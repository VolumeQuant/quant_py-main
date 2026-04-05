# 작업 원칙

## 사용자 지시 준수
- 사용자 지시와 다른 판단을 하려면 **반드시 먼저 물어볼 것**. 임의로 건너뛰지 마라.
- "대충 맞겠지"로 넘기지 말고, 확인 가능한 건 확인하고 진행
- 효율성을 위한 판단이라도 사용자 승인 없이 지시를 무시하면 안 됨

## 실행 전 검증
- 실행 전에 기본 가정을 확인하라 (날짜, 경로, 데이터 존재 여부 등)
- 같은 실수 2번 이상 반복하지 마라
- 각 단계 끝날 때마다 결과 검증 후 다음 단계 진행

## 병렬 실행 최적화
- 병렬 작업 전: CPU 코어 수, 가용 메모리, 프로세스당 메모리 확인
- 최적 병렬 수 = min(CPU코어, 가용메모리 ÷ 프로세스당 메모리)

## 재사용 우선
- 변수 하나만 바꿔서 비교할 때, 전체 파이프라인을 처음부터 돌리지 마라
- 변하지 않는 부분을 재사용하라 (캐시, 이전 결과 등)

## pykrx
- 1초 sleep, 순차 실행 절대. 집 IP 이미 차단됨

---

# 🇺🇸 US 전략 — eps-momentum-us (v71)

> 경로: `C:\dev\claude code\eps-momentum-us`

- EPS Revision Momentum, conviction z-score 기반, **균등비중**
- conviction: adj_gap × (1 + max(up30/N, min(|eps_chg|/100, 1)))
- 점수: 일별 z-score(30~100) → 3일 가중(T0×0.5+T1×0.3+T2×0.2), 빈 날=30점
- 진입: 3일 가중 Top 3 + ✅(3일 검증) + min_seg ≥ 0%, 슬롯 5
- 퇴출: part2_rank > 15 OR min_seg < -2% OR -10% 손절
- composite_rank=당일 conviction 순위(추이 표시), part2_rank=3일 가중 순위(매매)
- RETURN_MATRIX: S&P500 기반 (26년 6,593일), VIX는 yfinance 최신 보완
- 비중 조절 안 함 (알파가 공포 구간에서 발생)
- 상관관계: 🔗 유사도% + BFS 그룹핑 + 택1/택1~2 권장

---

# 🇰🇷 KR 전략 — quant_py-main (v75, 2026-04-05)

> 경로: `C:\dev\claude code\quant_py-main`

## 국면전환 전략 (v75) — Breadth40 기반

### 국면 규칙
- **Breadth40**: 전종목 40%+ MA120 위 = 공격, 미만 = 방어
- **1일 확인** (즉시 전환)
- 전환 시 기존 포트폴리오 청산 → 새 전략 재진입

### 방어 모드 — Breadth < 40% (Momentum 중심)
- **V15 + Q25 + G10 + M50**
- G 내부: g_rev=1.0 (매출성장률 100%)
- 모멘텀: 6M/Vol
- 진입: rank ≤ 5, 퇴출: WR > 12, 슬롯 5
- 손절: -10%, 트레일링: -20%

### 공격 모드 (Boost) — Breadth ≥ 40% (Growth 중심)
- **V30 + Q0 + G55 + M15**
- G 내부: g_rev=0.7 (매출성장률 70% + 영업이익변화 30%)
- 모멘텀: 12M
- 진입: rank ≤ 5, 퇴출: WR > 12, 슬롯 3
- 손절: -12%, 트레일링: -20%

### 국면전환 성과 (2021-01 ~ 2026-04, 1287일)
- **Calmar=5.78, CAGR=146%, MDD=25%**
- Sharpe=2.21, Sortino=3.51
- 국면 비율: Boost 54%, 방어 46%
- WF 검증: WF1=3.43, WF2=16.01, WF3=15.62

### 그리드서치 방법론
- Phase 2a: 11,132개 가중치 × g_rev × 4종 모멘텀 스크리닝
- Phase 2b: Top 200 × 1,080 규칙 = 216,000 조합
- Phase 2c: Walk-Forward 3기간 교차 검증
- Phase 2d: Benjamini-Hochberg FDR q<0.05 (217/216,000 유의)
- Phase 2e: 인접 안정성 (가중치 ±5, entry/exit/slots ±1~2)
- Phase 3: 국면전환 run_regime (전환 시 청산+재진입 정확 시뮬)
- 전략 선정: Borda Count + Pareto Frontier (자의적 가중치 없음)

### 공통
- PER/PBR/ROE: pykrx (KRX 공식)
- 재무제표: DART + FnGuide 보충 (누락 계정 자동 합침)
- FWD_BONUS: 삭제
- MA120 필터: 126일(6M) 미만 제외 (모멘텀 계산 불가, IPO 노이즈)

## v75 데이터 파이프라인 개선 (2026-04-05)
- DART+FnGuide 데이터 합치기: DART에 빠진 계정을 FnGuide에서 보충
- TTM YoY 갭 체크: 450일 이상 갭 → TTM 거부, 연간 fallback
- MA120 필터: 126일 미만 제외 (IPO 시즈닝)
- DART USD 환율 변환 (두산밥캣 등)
- 4종 모멘텀 BT (6m, 6m-1m, 12m, 12m-1m)
- FG/CP 완전 일치: 20종목 Growth 100% 일치 + z-score 함수 동일

## 유니버스 필터
- 시총 ≥ 1000억, 거래대금: 대형 ≥ 50억, 중소형 ≥ 20억

## 시장 위험 지표
- RETURN_MATRIX: 코스피 기반 (26년 6,027일)
- 신호등: 🟢≥8% / 🟡<8% / 🔴<5%+extreme
- VIX 비중 조절 안 함

## 메시지
- Signal: 국면 표시 (방어/공격)
- 날짜: 항상 전일 기준 (d < today_str)

## 스케줄러
- 일일 파이프라인: 월~금 06:00 (DART 증분 포함)
- 종목명 캐시: 매주 일요일 10:00

## 주의사항
- OHLCV: 프로덕션 실행 시 백테스트용도 동기화
- Growth 계산: 계정별 날짜 사용 (0 채우기 금지)

## 백테스트 도구
- TurboSimulator: 5ms/run (56x 가속), turbo_simulator.py
- fast_generate_rankings_v2.py: DART+FnGuide 합침, per-account dates
- grid_search_final.py: 3워커 병렬, Calmar 기준, 안정성 필터
- ProcessPoolExecutor 기반 Windows 호환 병렬
