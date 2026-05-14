# KR EPS Momentum — US 코드 KR adapt TODO

**시작**: 2026-05-14
**Base**: US 프로젝트 (`C:/dev/claude code/eps-momentum-us/`) 코드 복사본
**원칙**: production v80.6 무관, yf 외부 API만 사용

---

## ✅ 완료

- [x] 디렉토리 셋업 (`C:/dev/kr_eps_momentum/`)
- [x] US 코드 통째 복사 (DB/cache 제외, 46 .py)
- [x] `config_kr.json` 작성 (KR 전용)
- [x] `universe_kr.py` 작성 — KRX 시총 1천억+ 보통주 ticker getter
- [x] `daily_probe.py` 워크스페이스 (`C:/dev/yf_eps_workspace/`) 매일 자동 수집 시작

---

## 🔧 KR adapt 작업 (단계적)

### Phase 3a — core 모듈 (1~2일)

- [ ] `eps_momentum_system.py` — core 로직 (NTM 계산, segment score) KR 무관, 거의 그대로
  - `calculate_ntm_eps(stock)`: 종목 무관, 변경 0
  - `calculate_ntm_score(ntm_values)`: 변경 0
  - 단위 (KRW vs USD): yf eps_trend는 자국 통화 → 무관

### Phase 3b — daily_runner.py (3~5일, 5178줄)

큰 변경 점:

#### 1. Universe getter
- 현재: `fetch_dynamic_tickers(min_mcap=5_000_000_000)` — NASDAQ API
- 변경: `from universe_kr import get_kr_universe` 사용

#### 2. 시간대
- 현재: `pytz` US/Eastern
- 변경: `Asia/Seoul`
- 변경 위치: 검색 `pytz` / `Eastern` / `ET` / `NY`

#### 3. 거래일 calendar
- 현재: pandas_market_calendars (NYSE)
- 변경: `from universe_kr import get_kr_trading_dates`

#### 4. 텔레그램
- 현재: US 봇 토큰 + 채널
- 변경: 새 KR 봇 (사용자가 토큰 생성해야 함)
- 메시지 일부 영어 고정 표현 (S&P500 등) → KOSPI/KOSDAQ 교체

#### 5. 벤치마크 지수
- 현재: `^GSPC` (S&P 500), `^IXIC`, `^DJI`, `^RUT`
- 변경: `^KS11` (KOSPI), `^KQ11` (KOSDAQ), `^KS200` (KOSPI200)

#### 6. Commodity 제외 키워드
- 현재: 영어 (`COMMODITY_INDUSTRIES`)
- 변경: 한국어 (`universe_kr.KR_COMMODITY_KEYWORDS` 정의됨)

#### 7. DB 경로
- 현재: `eps_momentum_data.db`
- 변경: `eps_momentum_data_kr.db`

#### 8. ticker 포맷
- 현재: `AAPL`, `BRK-B`
- 변경: `005930.KS`, `091700.KQ`
- yf probe 패턴 (`try_market`)으로 KS/KQ 자동 결정

### Phase 3c — BT 파일들 (60일 누적 후)

- backtest_v6_winner.py 등 BT 파일들은 historical 데이터 필요 → 60일 누적 후
- gridsearch_*.py 들도 동일

### Phase 3d — 추가 인프라

- [ ] HY spread / VIX → KR 대체 (CDS spread? VKOSPI?)
- [ ] AI 분석 (Gemini API) — KR 종목 정보로 prompt 변경
- [ ] git push — KR 별도 repo? 또는 비활성화?

---

## 우선순위

1. ★ **Paper trade 코드** (지금 작성 중) — v80.6 + yf 신호 비교, 즉시 가치
2. core 모듈 KR adapt (1~2일, 종목 무관)
3. daily_runner.py KR adapt (3~5일)
4. BT 시스템 (60일 후)

---

## v80.6 production 무관 보장

- KR EPS 시스템은 `C:/dev/kr_eps_momentum/` 격리
- v80.6 production (`C:/dev/`)은 무변경
- yf data cache는 `C:/dev/yf_eps_workspace/data_cache_yf/` (격리)
- DART/pykrx 호출 0 (yf만)
- production state, code, cache 모두 무관

---

## 다음 결정 시점

| 시점 | 결정 |
|---|---|
| 5/14~7/13 (60일) | daily probe 누적 + paper trade로 신호 비교 |
| 7/13~ | 60일 paper trade 결과 — 패턴 A/B/C alpha 확인 |
| 7월 후 | core 모듈 KR adapt 정식 진행 (alpha 입증된 경우) |
| 가을~ | daily_runner KR adapt 완성 (독립 시스템) |
| 검증 후 | v80.6 통합 검토 (패턴 A/B/C) |
