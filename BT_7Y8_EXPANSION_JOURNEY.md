# BT 7.8년 확장 시도 기록 (2026-04-14 ~ 04-15)

**회사 PC에서 이어가는 Claude에게**: 이 문서는 어제 밤부터 오늘 아침까지 집 PC에서 시도한 모든 작업과 시행착오를 상세히 기록한 것입니다. 현재 상태를 정확히 파악하고 다음 작업을 이어가세요.

---

## 현재 상태 요약 (2026-04-15 아침 기준)

### ✅ 프로덕션 (완료됨, 그대로 유지)
- **전략**: v77.1 (v77 + Crash Cash)
- **프로덕션 랭킹**: `state/ranking_2021*~2026*.json`, `state/defense/ranking_2021*~2026*.json`
  - **(d') + (e) 필터 적용 완료** (FG 전체 재생성 20.1분)
  - capped 종목(솔루스첨단소재, GS피앤엘, 엠디바이스 등) 모두 제거됨
- **4/14 개인봇 메시지**: 정상 전송 완료

### ✅ 코드 변경 (완료됨, 유지)
- `backtest/fast_generate_rankings_v2.py`:
  - **(d') 필터**: 시점별 분기 8개 미만 제외 (rcept_dt <= base_date 기준)
  - **(e) 필터**: G 서브팩터 5개 이상 동일값 → capped 종목 제외
- `send_telegram_auto.py` 최종 표시 시스템:
  - **궤적**: wr 정수순위 (매매 로직 wr과 일치, 오늘 아침 cr→wr 환원 `41f818e34`)
    - 동점 tie-breaker: cr 작은 쪽 우선
  - **점수**: `score_100 = 100 × 0.9^(표시순번 - 1)` (어제 오후 `995422c9e`/`d77168eba` 도입)
    - 1위=100, 2위=90, 3위=81, 10위=39
    - 동점 불가, 선익시스템 매일 100점 문제 해결됨

### ❌ 실패/롤백 (회사 PC에서 재시도 필요)
- **BT 7.8년 확장 (2018-07~2026-04)**: 실패, 롤백됨
- 자세한 원인은 아래 "실패 내역" 참조

---

## 시행착오 타임라인

### [2026-04-14 오후~저녁] 프로덕션 정비
1. `v78` 시도 후 v77 복원 (2026-04-13 완료)
2. 솔루스첨단소재(336370) cr=1 튀어나오는 문제 발견
3. EDA 결과 **(d) 필터** 추가: 분기 8개 미만 제외
4. 2586개 ranking 파일 (d) 필터 적용 (z-score 재사용 방식)
5. 맹점 발견: z-score 재사용과 FG 전체 재생성 간 차이 큼 (cr 일치율 1.5%)
6. FG 전체 재생성으로 정확화 → CAGR 109%, Cal 3.02 (5.25년)

### [2026-04-14 저녁] 추가 필터 발견
7. `(d)` 필터의 허점 발견:
   - 솔루스첨단소재: fs_dart에 24분기 있어서 (d) 통과
   - 하지만 **2021-05-24 시점에는 5분기만 공시됨** → TTM YoY 계산 불가 → capped
   - **(d) 필터는 "현재 분기 개수"만 체크, "시점별"은 안 봄**
8. 해결책 도출:
   - **(d') 필터**: `rcept_dt <= base_date` 기준 시점별 분기 8개 체크
   - **(e) 필터**: 스코어링 후 G 서브팩터 5개 이상 동일 = capped → 2차 필터
9. 두 필터 `fast_generate_rankings_v2.py` 추가 (env `FILTER_NO_NEW_LISTING`, `FILTER_NO_CAPPED`로 끌 수 있음)
10. 2021~2026 프로덕션 FG 전체 재생성 (20.1분) → **Cal 3.02 → 깨끗한 상태**
11. 4/10~4/14 OHLCV 갱신 + 재생성 → 완전 일관

### [2026-04-14 밤 22:00~] 7.8년 BT 확장 시도

**계획**: 2018-07~2026-04 BT 데이터 수집 + 그리드서치 + Top 10 안정성/WF

**Phase 2 수집 (145.8분)**:
- DART 2016-Q1~2017-Q4 (1545 종목): **"성공" 로그 찍혔으나 실제 데이터 저장 실패**
  - **원인**: `scripts/collect_7y8_data.py` 코드 오류
    - `collector.fetch_single(tk, 2016, 2017)` 호출만 하고 반환 DataFrame을 무시
    - `save_cache(ticker, df)` 호출 안 함 → parquet 저장 X
    - **올바른 방법**: `collector.fetch_universe(tickers, 2016, 2017, skip_cached=False)` 사용
      (fetch_universe 내부에서 save_cache 호출)
  - **검증 누락**: 성공 로그만 보고 실제 parquet 내용 확인 안 함
- pykrx OHLCV 2017-06~2019-05 (730일): 정상 수집
- pykrx market_cap 2017-06~2019-12 (942일): 정상 수집
- pykrx fundamental 2018-01~2019-12 (729일): 정상 수집
- KOSPI index 2017-01~2020-05 (835일): 정상 수집

**Phase 3 BT 재생성 (25.1분)**:
- `state/bt_7y8/` 생성 (1485 성공 / 539 실패 / 2024 전체)
- 539일 실패는 2018-07~2019 구간 TTM YoY 계산 불가 (DART 2016-2017 없어서)
- **즉 BT 결과는 사실상 2020년 이후만 유효** → 2018-2019가 빠진 7년 BT

**Phase 4 그리드서치 (5.6분, 실패)**:
- `scripts/grid_search_7y8.py` TurboSimulator API 호환성 오류
- `_ensure_cache` 호출 시 튜플 전달 → dict 기대 불일치
- Attack Top 5 빈 리스트 반환 → Phase 4b에서 IndexError
- baseline 5개만 계산 (`scripts/phase4_baselines_only.py` 대체 실행)

**Baseline 결과 (부실 데이터 기반, 참고용만)**:
| 전략 | Cal | CAGR | MDD |
|---|---:|---:|---:|
| v77 | 0.94 | 51.9% | 55.0% |
| v78 | 1.89 | 79.9% | 42.4% |
| v77 attack-only | 1.05 | 55.6% | 52.9% |
| V20Q0G50M30 attack-only | 1.65 | 77.7% | 47.1% |
| **v78 attack-only** | **2.73** | **95.1%** | **34.8%** |

→ **v78 attack-only Cal 2.73** 매력적이지만 2018-2019 데이터 부실로 **재검증 필수**.

**커밋 bac584104 (실패 상태로 푸시됨)**:
- `feat(7y8 expansion)` 제목
- state/bt_7y8, scripts, pykrx 확장, fs_dart metadata 변경 등 포함
- **잘못된 커밋** — 아래 오늘 아침 롤백 참조

### [2026-04-15 아침] 롤백 + 정리

**사용자 깨어나서 검증 요청**:
- DART 실제 수집 확인 → 삼성전자, SK하이닉스 등 2016-2017 0개 확인
- **"1545종목 성공" 로그는 거짓** — fetch_single이 저장 안 했음

### [2026-04-14 오후] 표시 시스템 변경 (어제 오후 5:30경)

**17:29 커밋 `995422c9e`**: 표시 점수 지수감쇠 도입
- 기존: `score_100 = 100 - (wr - wr_min)/wr_range × 50`
- 신규: `score_100 = 100 × 0.9^(wr - 1)` 지수감쇠
- 매 등수 10% 감소, "선익시스템 매일 100점" 문제 해결
- 점수 기반 매매 BT는 -12% → 매매 로직 불변, 표시만 변경

**17:40 커밋 `d77168eba`**: 궤적 cr + 점수 표시순번
- 궤적: wr 정수순위 → **각 날짜 당일 cr** (강해짐/약해짐 표시)
- 점수: `0.9^(wr-1)` → `0.9^(표시순번-1)` (동점 완전 해결)

**오늘 아침 커밋 `41f818e34`**: 궤적만 wr 환원
- 사용자 결정: wr 기반 표시가 매매 로직과 일치
- 궤적: 당일 cr → **wr 정수순위** (tie-breaker: cr 작은 쪽)
- 점수: `0.9^(표시순번-1)` 그대로 유지

### [2026-04-15 아침] 롤백 + 정리

**롤백 내용 (커밋 41f818e34)**:
- **유지** (bac584104에서 보존):
  - `backtest/fast_generate_rankings_v2.py`: (d')+(e) 필터
  - `state/ranking_2021*~2026*.json`: (d')+(e) 프로덕션 2021~2026
  - `state/defense/ranking_2021*~2026*.json`
- **삭제**:
  - `state/bt_7y8/`: 부실 BT
  - `state/test_de/`, `test_fg_speed/`, `test_filter_d/`
  - `scripts/`: 어제 밤 6개 스크립트 (collect/grid_search/orchestrator/finalize 등)
  - `backtest_results/grid_7y8_final.json`
  - `data_cache/all_ohlcv_20170601_20260414.parquet`
  - `data_cache/market_cap_ALL_2017*.parquet ~ 2019*.parquet`
  - `data_cache/fundamental_batch_ALL_2018*.parquet ~ 2019*.parquet`
- **롤백 (74172650f 상태로)**:
  - `data_cache/fs_dart_*.parquet` 수백 개 (DART 재수집 흔적)
  - `data_cache/kospi_yf.parquet`, `kosdaq_yf.parquet`
- **신규 변경**:
  - `send_telegram_auto.py`: 궤적 cr → wr 환원

---

## 회사 PC에서 이어갈 작업

### 1. `git pull` 받으면 깨끗한 상태로 이어갈 수 있음
- 최신 커밋: `41f818e34`
- 이전 커밋: `bac584104` (엉망, 이미 롤백됨)
- 그 이전: `74172650f` (d 필터)

### 2. BT 7.8년 확장 재시도 (회사 PC DART 전체 활용)

**DART 상태**:
- 집 PC: 2018-Q1부터만 (rcept_dt 2018-05-14~)
- 회사 PC: 사용자 언급에 따르면 **2012년부터 분기보고서 존재 가능** (WHIPSAW_ANALYSIS_2026_04_14.md 참조)
- 회사 PC의 DART가 2016-Q1부터라면 BT 2018-07부터 가능
- 더 확장하려면 `dart_collector.py` 활용해서 2014-2015 수집

**올바른 수집 방법**:
```python
from dart_collector import DartCollector
c = DartCollector()
tickers = [...]  # 종목 리스트
c.fetch_universe(tickers, 2014, 2015, skip_cached=False)  # 반드시 fetch_universe 사용
```
- ❌ `fetch_single(tk, 2016, 2017)` 반환값을 버리면 저장 안 됨
- ✅ `fetch_universe`는 내부에서 `save_cache` 호출함
- **검증 필수**: 수집 후 임의 종목 parquet 열어서 해당 연도 분기 수 확인

**pykrx 수집 필요한 것**:
- OHLCV: 2017-06-01~ (집 PC 2019-06부터라 회사 PC 확인 필요)
- market_cap 일별: 2017-06-01~
- fundamental: 2018-01~2019-12 (집 PC는 2020-01부터만)
- KOSPI index: 2017-01-01~2020-05-31 (집 PC 2020-06부터만)

### 3. 그리드서치 API 호환성 수정

**문제**: `turbo_simulator.py`의 `run_regime()`은 dict 파라미터 요구:
```python
defense_params = {'v':..., 'q':..., 'g':..., 'm':..., 'g_rev':..., 'entry':..., 'exit':..., 'slots':..., 'mom':...}
offense_params = 같음
regime_dict = {date_str: True/False}  # True=boost, False=defense
```

**참고 코드** (이미 scripts 삭제했으므로 재작성):
```python
import os, sys, json
from pathlib import Path
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT / 'backtest'))

from turbo_simulator import TurboSimulator, TurboRunner
import pandas as pd, numpy as np

# BT ranking 로드 (state/bt_7y8/ 생성 후)
def load_ranks(d):
    data = {}
    for f in sorted(d.glob('ranking_*.json')):
        date = f.stem.replace('ranking_', '')
        if len(date) != 8: continue
        with open(f, 'r', encoding='utf-8') as fh:
            rd = json.load(fh)
        data[date] = rd.get('rankings', rd) if isinstance(rd, dict) else rd
    return data

boost = load_ranks(PROJECT / 'state' / 'bt_7y8')
prices = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
dates = sorted(boost.keys())
tsim = TurboSimulator(boost, dates, prices)

# v77.1 baseline (예시)
reg = {d: True for d in dates}  # attack-only
r = tsim.run_regime(
    defense_params={'v': 0.05, 'q': 0.00, 'g': 0.65, 'm': 0.30, 'g_rev': 0.0,
                    'entry': 7, 'exit': 8, 'slots': 3, 'mom': '12m-1m'},
    offense_params={'v': 0.05, 'q': 0.00, 'g': 0.65, 'm': 0.30, 'g_rev': 0.0,
                    'entry': 7, 'exit': 8, 'slots': 3, 'mom': '12m-1m'},
    regime_dict=reg,
    g_sub1_o='rev_z', g_sub2_o='oca_z',
    g_sub3_o='gp_growth_z', g_w1_o=0.5, g_w2_o=0.3, g_w3_o=0.2,
)
print(r['calmar'], r['cagr'], r['mdd'])
```

### 4. 검증해야 할 가설들

- **v78 attack-only Cal 2.73**: 실제인지 재검증 (제대로 된 7.8년 BT에서)
- **V20Q0G50M30 attack-only**: v78 탐색에서 Cal 2.19로 나왔던 것. 현재 필터 추가 후 값은?
- **국면전환의 실제 가치**: 7.8년에서 국면전환 vs attack-only 어느 게 나은가
- **Crash Cash (v77.1)**: 7.8년에 2020-03 COVID 구간 효과 재검증

### 5. 그리드서치 단계 (v78 탐색 패턴 참고)

V78_STRATEGY_SEARCH.md 참고하되 (d')+(e) 필터 효과 반영:
- **Phase 2a**: Attack 그리드 (V 0-30 × Q 0-10 × G 30-70 × M 20-45) × G서브 3종
- **Phase 2b**: Top 15 × E/X/S 규칙 (60)
- **Phase 3**: 국면 규칙 (attack-only, MA200 5/7/10/15d, 버퍼 1/2/3%, Crash Cash 포함)
- **Phase 4 (Top 10 대상)**: 인접 안정성 25 이웃 (Top 1만 망할 때 대비)
- **Phase 5 (Top 10 대상)**: WF 4기간 (2018-19/2020-21/2022-23/2024-26)

### 6. 교훈 (재발 방지)

1. **수집 스크립트는 표본 검증 필수**:
   - 수집 후 반드시 임의 종목 parquet 열어서 실제 데이터 확인
   - "성공 카운트 = 실제 저장 카운트"인지 검증
2. **DART 수집은 fetch_universe 사용**:
   - fetch_single 쓸 거면 반드시 save_cache도 직접 호출
3. **시간 제약 있는 작업은 즉시 검증**:
   - 밤샘 작업 결과도 즉시 샘플 검증 루틴 있어야 함
4. **커밋 전 검증**:
   - 큰 커밋일수록 주요 파일 내용 샘플 확인 필수
   - "성공" 로그 = "검증 완료" 아님
5. **실패 인정은 빠르게**:
   - 사용자 검증 요청 시 변명보다 정직한 원인 분석 우선

---

## 파일 구조 (현재)

```
quant_py-main/
├── backtest/
│   └── fast_generate_rankings_v2.py   # (d')+(e) 필터 포함
├── regime_indicator.py                 # v77.1 (Crash Cash)
├── send_telegram_auto.py               # 궤적 wr 환원
├── state/
│   ├── ranking_2021*~2026*.json       # (d')+(e) 적용, 프로덕션
│   └── defense/ranking_2021*~2026*.json
├── data_cache/
│   ├── fs_dart_*.parquet               # 2018-Q1부터 (집 PC 기준)
│   ├── all_ohlcv_2019060*_2026041*.parquet  # 2019-06부터
│   ├── market_cap_ALL_*.parquet        # 최근 위주
│   └── fundamental_batch_ALL_202*      # 2020-01부터
└── BT_7Y8_EXPANSION_JOURNEY.md        # 이 파일
```

---

## 중요 원칙 (CLAUDE.md 참고)

- **표본 먼저**: 모든 작업 시작 전 표본으로 검증
- **EDA → 인사이트 → 계획**: 이전 단계 데이터 EDA 후 다음 계획
- **맹점 체크**: 각 단계 끝마다 필수
- **한 번에 하나만**: 변경 하나씩
- **재사용 우선**: 기존 캐시/결과 활용
- **pykrx**: 1초 sleep 순차, 집 PC 차단 이력 있음 (회사 PC는 OK)
- **검증 우선**: "성공" 로그보다 실제 파일 내용 확인
