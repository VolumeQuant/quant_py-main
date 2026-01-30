# 한국 주식 멀티팩터 전략 백테스팅 시스템 - 작업 핸드오프 문서

## 📋 프로젝트 개요

**목표**: 『파이썬을 이용한 퀀트 투자 포트폴리오 만들기』 책의 MySQL 기반 시스템을 API 기반으로 전환하고, 마법공식과 멀티팩터 전략을 구현한 백테스팅 시스템 구축

**데이터 소스**:
- pykrx API: 시가총액, 기본 재무비율, OHLCV
- FnGuide 크롤링: 상세 재무제표 (손익계산서, 재무상태표, 현금흐름표)
- FinanceDataReader: 보조 데이터 (선택적)

**전략**:
- 전략 A: 마법공식 (Magic Formula) - 이익수익률(EBIT/EV) + 투하자본수익률(EBIT/IC)
- 전략 B: 멀티팩터 - 밸류(PER/PBR/PCR/PSR) + 퀄리티(ROE/GPA/CFO) + 모멘텀

---

## ✅ 완료된 작업 (2026-01-30 업데이트)

### 1. 현재 포트폴리오 생성 완료 ✅

**실행 스크립트**: `create_current_portfolio.py`
**기준일**: 2026-01-29
**실행 시간**: 약 50분 (FnGuide 크롤링 1101종목)

**결과**:
- 전략 A (마법공식): 30종목 선정
- 전략 B (멀티팩터): 30종목 선정
- 공통 종목: 1개 (알트 459550)

**출력 파일**:
- `output/portfolio_2026_01_strategy_a.csv`
- `output/portfolio_2026_01_strategy_b.csv`
- `output/portfolio_2026_01_report.txt`

### 2. 전체 백테스팅 완료 ✅

**실행 스크립트**: `full_backtest.py`
**기간**: 2015-01-01 ~ 2025-12-31 (11년)
**리밸런싱**: 분기별 (44회)
**실행 시간**: 약 15분

**결과 요약**:

| 지표 | KOSPI | 전략 A | 전략 B |
|------|-------|--------|--------|
| **총 수익률** | - | 90.77% | 102.36% |
| **CAGR** | 7.58% | 11.98% | 13.15% |
| **MDD** | -43.90% | -24.42% | -33.90% |
| **Sharpe** | 0.27 | 0.53 | 0.53 |

**IS/OOS 비교**:

| 구간 | 전략 A CAGR | 전략 B CAGR |
|------|-------------|-------------|
| In-Sample (2015-2023) | 3.01% | 7.06% |
| Out-of-Sample (2024-2025) | **67.50%** | **47.71%** |

**출력 파일**:
- `backtest_results/backtest_strategy_A_*.csv/json`
- `backtest_results/backtest_strategy_B_*.csv/json`
- `backtest_results/backtest_comparison.csv`
- `backtest_results/backtest_benchmark_returns.csv`

---

## 📁 수정된 주요 파일 목록

### 이번 세션에서 수정/생성된 파일

#### 1. `data_collector.py` (수정)
**변경 사항**: FinanceDataReader 의존성 제거 (선택적 import)
```python
# 수정 전: import FinanceDataReader as fdr (실패 시 에러)
# 수정 후:
try:
    import FinanceDataReader as fdr
    HAS_FDR = True
except ImportError:
    HAS_FDR = False
```
**위치**: 15-19줄

#### 2. `create_current_portfolio.py` (신규)
**기능**: 현재 포트폴리오 생성 (2026년 1월)
**핵심 로직**:
```python
# 최근 거래일 자동 탐지 (미래 날짜 문제 해결)
from pykrx import stock as pykrx_stock
from datetime import datetime as dt, timedelta as td
_today = dt.now()
BASE_DATE = None
for _i in range(10):
    _date = (_today - td(days=_i)).strftime('%Y%m%d')
    try:
        _df = pykrx_stock.get_market_cap(_date, market='KOSPI')
        if not _df.empty:
            BASE_DATE = _date
            break
    except:
        continue
```
**위치**: 23-36줄

#### 3. `full_backtest.py` (신규)
**기능**: 2015-2025 전체 백테스팅
**핵심 로직**:
```python
def run_benchmark():
    """벤치마크 (코스피) 성과 계산 - pykrx 버전 호환"""
    try:
        from pykrx import stock
        kospi = stock.get_index_ohlcv(START_DATE, END_DATE, '1001')
        # 종가 컬럼명 자동 탐지
        close_col = None
        for col in kospi.columns:
            if '종가' in col or 'close' in col.lower():
                close_col = col
                break
        if close_col is None:
            close_col = kospi.columns[3]  # 기본값
        # ...
    except Exception as e:
        print(f"벤치마크 스킵: {e}")
        return pd.Series(dtype=float), {}
```
**위치**: 379-414줄

#### 4. `visualize_backtest.py` (신규)
**기능**: 백테스트 결과 시각화 (개발 중)

#### 5. `PROJECT_REPORT.md` (신규)
**기능**: 프로젝트 최종 결과 리포트

---

## 🐛 이번 세션에서 해결된 기술 이슈

### Issue #1: pykrx 버전 충돌
**증상**: `ModuleNotFoundError: No module named 'FinanceDataReader'`
**원인**: FinanceDataReader 미설치 + data_collector.py 강제 import
**해결**:
```python
try:
    import FinanceDataReader as fdr
    HAS_FDR = True
except ImportError:
    HAS_FDR = False
```
**파일**: data_collector.py:15-19

### Issue #2: pykrx 1.0.51 인코딩 문제
**증상**: `KeyError: "None of [Index(['종가', '시가총액', ...])"`
**원인**: pykrx 1.0.51 버전에서 한글 컬럼명 인코딩 오류
**해결**: pykrx 1.2.3으로 업그레이드
```bash
pip install pykrx --upgrade --no-deps
```

### Issue #3: 캐시 데이터 컬럼명 불일치
**증상**: 기존 캐시 파일이 새 버전과 호환 안됨
**해결**: 캐시 파일 삭제 후 재수집
```python
from pathlib import Path
[f.unlink() for f in Path('data_cache').glob('market_cap_*.parquet')]
```

### Issue #4: 미래 날짜 데이터 조회 실패
**증상**: BASE_DATE='20251231' → 시가총액 0개
**원인**: 2025년 12월 31일은 아직 오지 않음
**해결**: 최근 거래일 자동 탐지 로직 추가
```python
for _i in range(10):
    _date = (_today - td(days=_i)).strftime('%Y%m%d')
    _df = pykrx_stock.get_market_cap(_date, market='KOSPI')
    if not _df.empty:
        BASE_DATE = _date
        break
```
**파일**: create_current_portfolio.py:23-36

### Issue #5: html5lib 누락 경고
**증상**: `Couldn't find a tree builder with the features you requested: html5lib`
**원인**: BeautifulSoup html5lib 파서 미설치
**해결**:
```bash
pip install html5lib
```
**참고**: 경고만 발생하며 작동에는 영향 없음 (lxml 대체 사용)

---

## 🔧 시스템 환경 정보

### Python 환경
```
Python: 3.13 (miniconda3)
경로: C:\Users\jkw88\miniconda3\python.exe
```

### 핵심 패키지 버전
```
pykrx==1.2.3          # 중요: 1.0.51은 인코딩 문제 있음
pandas==2.2.3
numpy==2.1.3
matplotlib==3.10.0
requests==2.32.3
beautifulsoup4>=4.12.0
html5lib>=1.1         # 선택적, FnGuide 파싱용
```

### 패키지 설치 명령어
```bash
pip install pykrx==1.2.3 --upgrade --no-deps
pip install pandas numpy matplotlib requests beautifulsoup4 lxml html5lib pyarrow tqdm
```

---

## 📂 프로젝트 구조

```
quant_py-main/
├── 핵심 모듈
│   ├── fnguide_crawler.py      # FnGuide 재무제표 크롤링
│   ├── data_collector.py       # pykrx API 래퍼 (수정됨)
│   ├── strategy_a_magic.py     # 마법공식 전략
│   └── strategy_b_multifactor.py # 멀티팩터 전략
│
├── 실행 스크립트
│   ├── create_current_portfolio.py  # 현재 포트폴리오 생성 (신규)
│   ├── full_backtest.py            # 전체 백테스팅 (신규)
│   ├── visualize_backtest.py       # 시각화 (신규)
│   └── run_backtest.py             # 샘플 백테스트
│
├── 출력 디렉토리
│   ├── output/                     # 현재 포트폴리오 결과
│   │   ├── portfolio_2026_01_strategy_a.csv
│   │   ├── portfolio_2026_01_strategy_b.csv
│   │   └── portfolio_2026_01_report.txt
│   │
│   └── backtest_results/           # 백테스팅 결과
│       ├── backtest_strategy_A_metrics.json
│       ├── backtest_strategy_A_returns.csv
│       ├── backtest_strategy_A_cumulative.csv
│       ├── backtest_strategy_A_history.csv
│       ├── backtest_strategy_B_*.csv/json
│       ├── backtest_benchmark_returns.csv
│       └── backtest_comparison.csv
│
├── 캐시 디렉토리
│   └── data_cache/                 # 데이터 캐시 (parquet)
│       ├── market_cap_ALL_*.parquet
│       ├── fundamentals_*.parquet
│       └── fs_cache/               # FnGuide 재무제표 캐시 (JSON)
│
├── 문서
│   ├── README_BACKTEST.md          # 프로젝트 문서
│   ├── SESSION_HANDOFF.md          # 작업 핸드오프 (이 파일)
│   └── PROJECT_REPORT.md           # 최종 결과 리포트 (신규)
│
└── 기타
    ├── strategy_a_portfolio.csv    # 샘플 결과
    ├── strategy_b_portfolio.csv    # 샘플 결과
    └── *.png                       # 분석 차트
```

---

## 🎯 다음 작업 단계

### 1. 시각화 완성 (우선순위: 높음)
**파일**: `visualize_backtest.py`
**작업 내용**:
```python
# 구현 필요:
1. 누적 수익률 차트 (전략 A vs B vs KOSPI)
2. 드로우다운 차트
3. 연도별 성과 히트맵
4. 월별 수익률 분포
```

### 2. 리포트 자동화 (우선순위: 중간)
**작업 내용**:
- HTML 리포트 자동 생성
- PDF 내보내기 기능
- 투자 사유 자동 작성

### 3. 실시간 모니터링 (우선순위: 낮음)
**작업 내용**:
- 포트폴리오 일일 성과 추적
- 리밸런싱 알림 시스템
- Streamlit 대시보드

### 4. 전략 개선 (우선순위: 낮음)
**작업 내용**:
- 모멘텀 팩터 추가 (현재 누락)
- 섹터 중립화
- 거래비용 최적화

---

## ⚠️ 알려진 제한사항

### 데이터 관련
1. **FnGuide 크롤링 속도**: 종목당 ~2초 → 1000종목 시 ~30분
2. **일부 날짜 데이터 누락**: 연말(12/31) 등 휴장일 캐시 문제
3. **선호주/우선주 처리**: 일부 종목 재무제표 누락

### 전략 관련
1. **모멘텀 미구현**: 전략 B의 모멘텀 팩터가 price_df=None으로 실행됨
2. **섹터 분류 없음**: 업종 중립화 미적용
3. **거래비용**: 0.3% 고정 (실제 슬리피지 미반영)

### 백테스팅 관련
1. **생존 편향**: 상장폐지 종목 미포함
2. **Look-ahead bias**: 재무제표 공시 시차 미반영 가능성
3. **배당 미반영**: 배당 재투자 미구현

---

## 🚀 빠른 시작 가이드

```bash
# 1. Repository 클론
git clone https://github.com/VolumeQuant/quant_py-main.git
cd quant_py-main

# 2. 패키지 설치
pip install pykrx==1.2.3 --upgrade --no-deps
pip install pandas numpy matplotlib requests beautifulsoup4 lxml html5lib pyarrow tqdm

# 3. 현재 포트폴리오 생성 (~50분 소요)
python create_current_portfolio.py

# 4. 전체 백테스팅 (~15분 소요, 캐시 있을 경우)
python full_backtest.py

# 5. 결과 확인
cat output/portfolio_2026_01_report.txt
cat backtest_results/backtest_comparison.csv
```

---

## 📝 작업 로그

| 날짜 | 작업자 | 주요 작업 | 파일 |
|------|--------|-----------|------|
| 2024-12-31 | Claude | FnGuide 크롤러 구현 | fnguide_crawler.py |
| 2024-12-31 | Claude | 데이터 수집기 구현 | data_collector.py |
| 2024-12-31 | Claude | 마법공식/멀티팩터 전략 구현 | strategy_*.py |
| 2024-12-31 | Claude | 샘플 백테스트 및 시각화 | run_backtest.py, visualize_results.py |
| **2026-01-30** | **Claude** | **data_collector.py FDR 의존성 제거** | **data_collector.py:15-19** |
| **2026-01-30** | **Claude** | **현재 포트폴리오 생성 스크립트** | **create_current_portfolio.py** |
| **2026-01-30** | **Claude** | **전체 백테스팅 시스템 구현** | **full_backtest.py** |
| **2026-01-30** | **Claude** | **pykrx 1.2.3 업그레이드 및 호환성 수정** | **full_backtest.py:379-414** |
| **2026-01-30** | **Claude** | **프로젝트 리포트 및 핸드오프 문서** | **PROJECT_REPORT.md, SESSION_HANDOFF.md** |
| **2026-01-30** | **Claude** | **전략 C 코스닥 성장 전략 구현** | **strategy_c_kosdaq_growth.py** |
| **2026-01-30** | **Claude** | **전략 C 백테스팅 및 실패 (CAGR -5.33%)** | **backtest_strategy_c.py** |
| **2026-01-30** | **Claude** | **전략 C 폐기 및 전략 A 코스닥 분석** | **전략 A 코스닥 18개 확인** |
| **2026-01-30** | **Claude** | **투자 비중 전략 및 코스닥 3000 정책 논의** | **문서 업데이트** |

---

## 🎯 현재 상태 요약

**완료율**: **95%** ✅

**완료된 핵심 기능**:
- ✅ FnGuide 크롤링 (계정과목 매핑 포함)
- ✅ pykrx 데이터 수집 (버전 호환성 처리)
- ✅ 마법공식 전략 구현
- ✅ 멀티팩터 전략 구현
- ✅ **현재 포트폴리오 생성 (2026년 1월)**
- ✅ **전체 백테스팅 (2015-2025, 11년)**
- ✅ **IS/OOS 성과 비교**
- ✅ **벤치마크 대비 분석**

**남은 작업**:
- 🔲 시각화 차트 완성
- 🔲 HTML/PDF 리포트 자동화
- 🔲 모멘텀 팩터 추가

---

**문서 버전**: 2.0
**최종 업데이트**: 2026-01-30
**작성자**: Claude Opus 4.5
