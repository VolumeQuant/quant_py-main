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

# 🇰🇷 KR 전략 — quant_py-main (v73, 2026-04-03)

> 경로: `C:\dev\claude code\quant_py-main`

## 투 트랙 전략 (v73)

### Core (70%) — 안정형
- **V20 + Q20 + G40 + M20**
- G 내부: g_rev=0.2 (매출성장률 20% + **Revenue Acceleration 80%**)
- 진입: rank ≤ 5, 퇴출: WR > 7, 슬롯 5
- 상관관계 필터: 0.5 (60일, 기존 보유 + 같은 날 신규 체크)
- Calmar=2.53, CAGR=54.8%, MDD=21.6%

### Boost (30%) — 공격형
- **V15 + Q5 + G65 + M15**
- G 내부: g_rev=1.0 (매출성장률 100%)
- 진입: rank ≤ 3, 퇴출: WR > 4, 슬롯 3
- 상관관계 필터: 없음
- Calmar=2.00, CAGR=95.0%, MDD=47.6%

### 공통
- PER/PBR/ROE: pykrx (KRX 공식)
- 재무제표: DART (매출액, 영업이익, 자산 등)
- 손절: -10% (쿨다운 없음)
- 트레일링 스톱: 최고가 대비 -20% (수동)
- FWD_BONUS: 비활성화
- score_100: (ws + 0.7) / 2.4 × 100

## 핵심 발견 (v73 Grid Search)
- Revenue Acceleration(매출 가속도)이 가장 강력한 Growth 서브팩터
- 영업이익 변화(oca)는 쓸모없음 (g_rev=1.0 항상 최적)
- 매출총이익은 매출액보다 못함
- MA120 필터 유지 필수 (제거 시 OOS 붕괴)
- 거래대금 30억은 알파 감소 (20억 유지)
- 상관관계 필터: G집중형에 효과 없음, 균형형에만 유효

## 유니버스 필터
- 시총 ≥ 1000억, 거래대금: 대형 ≥ 50억, 중소형 ≥ 20억

## 시장 위험 지표
- RETURN_MATRIX: 코스피 기반 (26년 6,027일)
- 신호등: 🟢≥8% / 🟡<8% / 🔴<5%+extreme
- VIX 비중 조절 안 함

## 메시지
- Signal: Core/Boost 분리 표시
- 상관관계: Core에서 🔗 그룹 자동 묶기 (0.5 기준, 자동 필터링)
- 날짜: 항상 전일 기준 (d < today_str)

## 스케줄러
- 일일 파이프라인: 월~금 06:00 (DART 증분 포함)
- 종목명 캐시: 매주 일요일 10:00

## 주의사항
- Core/Boost 각각 별도 ranking 파일 생성
- state/ ranking 재계산: composite_rank/score만 변경 가능 (rev_z/oca_z 활용)
- OHLCV: 프로덕션 실행 시 백테스트용도 동기화

## 백테스트 도구
- TurboSimulator: 5ms/run (56x 가속), turbo_simulator.py
- fast_generate_rankings_v2.py: 0.3초/일 (27x 가속), --rev-accel/--gross-profit/--no-ma120/--strict-filter
- grid_search_final.py: 3워커 병렬, Calmar 기준, 안정성 필터, 연도별 분해
- ProcessPoolExecutor 기반 Windows 호환 병렬
