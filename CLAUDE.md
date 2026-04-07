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

## 국면전환 전략 (v76 확정, 2026-04-06)

### 국면 규칙 (KP_MA200_5d)
- **KOSPI > 200일 이동평균** = 공격, 미만 = 방어
- **5일 연속 확인** 후 전환
- 전환 시 기존 포트폴리오 **전량 청산** → 새 전략 재진입
- 전환 빈도: 연 ~3회 (15회/5.25년)

### G팩터 서브팩터
- 공격: 영업이익변화 60% + 이익률변화 40%
- 방어: 매출성장 70% + 이익률변화 30%

### 공격 모드 (Boost) — KOSPI > MA200
- **V15 + Q5 + G60 + M20**
- G 내부: g_rev=0.6 (oca 60% + op_margin 40%)
- 모멘텀: 12M-1M
- 진입: rank ≤ 5, 퇴출: WR > 8, 슬롯 3
- 손절: -10%, 트레일링: -15%

### 방어 모드 (Defense) — KOSPI < MA200
- **V15 + Q10 + G25 + M50**
- G 내부: g_rev=0.7 (rev 70% + op_margin 30%)
- 모멘텀: 6M-1M
- 진입: rank ≤ 5, 퇴출: WR > 8, 슬롯 5
- 손절: -10%, 트레일링: -15%

### 국면전환 성과 (2021-01 ~ 2026-04, 1287일)
- **Calmar=6.92, CAGR=187.3%, MDD=27.1%**
- **Sharpe=2.53, Sortino=3.99**
- 안정성: 100% (이웃 27개 전부 Cal≥3.0)
- WF: avg=7.79, min=2.96

### 데이터 품질 필터 (v76 신규)
- pykrx PER/PBR/EPS/BPS 전부 0 → 제거
- ROE NaN (BPS=0) → 제거
- 금융 키워드 추가: 생명/화재/IB투자/벤처투자/자산운용/신탁
- 국면 비율: Boost 59%, 방어 41%
- WF 검증: WF1=11.33, WF2=12.33, WF3=10.05 (avg=11.23)
- 안정성: 88% (이웃 34개 중 Cal≥3.0: 30개)

### 그리드서치 방법론
- G 서브팩터 최적화: 6C2=15쌍 × 21비율 × 5세팅 + 15세팅 검증
- Phase 2a: 공격/방어 투트랙 (653×4mom = 2,612개 각각)
- Phase 2b: 공격Top15 + 방어Top15 × 1,080규칙 = 32,400개
- 국면전�� 서치: 9규칙 × 공격풀 × 방어풀 = run_regime 직접 (근사값 스킵)
- 규칙 인접 탐구: Top3 임계값±5, 확인일수±1
- WF 3기간 + 안정성 (FDR 삭제 → WF+안정성만)
- 전문가 6인 패널 (국면 규칙 컨설팅)

### 공통
- PER/PBR/ROE: pykrx (KRX 공식)
- 재무제표: DART + FnGuide 보충 (누락 계정 자동 합침)
- FWD_BONUS: 삭제
- MA120 필터: 126일(6M) 미만 제외 (모멘텀 계산 불가, IPO 노이즈)

## 프로덕션 파이프라인 (v76, 2026-04-07)
- **run_daily.py → data_refresher → FG 직접 호출 → weighted_rank 후처리**
- CP 경유 제거, FG가 직접 스코어링
- `USE_NEW_PIPELINE=1`(기본)
- data_refresher.py: 시총/펀더멘털/OHLCV증분/섹터/KOSPI인덱스 갱신
- weighted_rank: FG 출력에 T0×0.5+T1×0.3+T2×0.2 후처리
- per/pbr/roe: 후처리에서 pykrx 캐시로 보충
- 매일 boost + defense 양쪽 ranking 생성 (국면 전환 대비)

### 주의사항 (v76 시행착오)
- send_telegram 단독 실행 금지 — 반드시 data_refresher 먼저 (OHLCV 미갱신 시 수익률 틀림)
- 스케줄러 변경 시 구 스케줄러 `schtasks //Query`로 확인 후 삭제
- 필터 효과 검증은 FG 재생성 기준 (TurboSim 필터링은 z-score 불변이라 낙관적)
- bt 파일의 score/rank는 쓰레기 — z-score만 유효 (TurboSim이 재계산)

## v75 데이터 파이프라인 (2026-04-05)
- DART+FnGuide 합치기, TTM YoY 갭 체크 (450일)
- MA120 필터: 126일 미만 제외 (IPO 시즈닝)
- 4종 모멘텀 BT (6m, 6m-1m, 12m, 12m-1m)
- ma120_failed: FG metadata에 저장 (이탈 사유 판단용)

## 유니버스 필터
- 시총 ≥ 1000억, 거래대금: 대형 ≥ 50억, 중소형 ≥ 20억

## 시장 위험 지표
- RETURN_MATRIX: 코스피 기반 (26년 6,027일)
- 신호등: 🟢≥8% / 🟡<8% / 🔴<5%+extreme
- VIX 비중 조절 안 함

## 메시지
- Signal: 국면 표시 (방어/공격), 전환 시 별도 안내 메시지 먼저 전송
- 날짜: 당일 기준 (19시 실행, d <= today_str)

## 스케줄러
- 일일 파이프라인: 월~금 19:00 (당일 장 마감 후, 휴장일 자동 스킵)
- 종목명 캐시: 매주 일요일 10:00

## 주의사항
- OHLCV: 프로덕션 실행 시 백테스트용도 동기화
- Growth 계산: 계정별 날짜 사용 (0 채우기 금지)

## 백테스트 도구
- TurboSimulator: 5ms/run (56x 가속), turbo_simulator.py
- fast_generate_rankings_v2.py: DART+FnGuide 합침, per-account dates
- grid_search_final.py: 3워커 병렬, Calmar 기준, 안정성 필터
- ProcessPoolExecutor 기반 Windows 호환 병렬
