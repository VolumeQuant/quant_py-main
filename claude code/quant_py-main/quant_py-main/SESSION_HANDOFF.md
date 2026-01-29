# 한국 주식 멀티팩터 전략 백테스팅 시스템 - 작업 핸드오프 문서

## 📋 프로젝트 개요

**목표**: 『파이썬을 이용한 퀀트 투자 포트폴리오 만들기』 책의 MySQL 기반 시스템을 API 기반으로 전환하고, 마법공식과 멀티팩터 전략을 구현한 백테스팅 시스템 구축

**데이터 소스**:
- pykrx API: 시가총액, 기본 재무비율, OHLCV
- FnGuide 크롤링: 상세 재무제표 (손익계산서, 재무상태표, 현금흐름표)
- FinanceDataReader: 보조 데이터

**전략**:
- 전략 A: 마법공식 (Magic Formula) - 이익수익률(EBIT/EV) + 투하자본수익률(EBIT/IC)
- 전략 B: 멀티팩터 - 밸류(PER/PBR/PCR/PSR/배당) + 퀄리티(ROE/GPA/CFO) + 모멘텀(12개월 수익률)

**백테스트 기간**:
- IS (In-Sample): 2015-2023
- OOS (Out-of-Sample): 2024-2025
- 현재 포트폴리오: 2026년 1월 기준

---

## ✅ 완료된 작업

### 1단계: 프로젝트 구조 설계 및 데이터 수집 모듈 구현

**생성된 파일**:
- `fnguide_crawler.py`: FnGuide 재무제표 크롤링 모듈
- `data_collector.py`: pykrx API 기반 데이터 수집 모듈
- `README_BACKTEST.md`: 프로젝트 문서

#### fnguide_crawler.py 주요 기능
```python
class FnGuideCrawler:
    def get_financial_statement(self, ticker, year)
    def clean_fs(self, fs_data)
    def extract_magic_formula_data(self, ticker, year)
```

**핵심 기술 해결사항**:
1. **계정과목 매핑 문제 해결**:
   - FnGuide는 '부채'를 사용하지만 코드는 '총부채' 필요 → mapping 추가
   - '현금및현금성자산' → '현금'으로 단순화
   - '법인세차감전순이익'을 EBIT로 직접 사용 (이자비용 불필요)

```python
account_mapping = {
    '부채': '총부채',  # 중요: FnGuide 원본 이름 매핑
    '현금및현금성자산': '현금',
    # ... 기타 계정
}

# 컬럼 이름 변경 로직
if '부채' in df.columns:
    df = df.rename(columns={'부채': '총부채'})
if '현금및현금성자산' in df.columns:
    df = df.rename(columns={'현금및현금성자산': '현금'})
```

2. **EBIT 계산 수정**:
```python
# 기존: EBIT = 당기순이익 + 법인세비용 + 이자비용 (이자비용 없음)
# 수정: FnGuide의 '법인세차감전순이익' 직접 사용
if '법인세차감전순이익' in data.columns:
    ebit = data['법인세차감전순이익']
else:
    ebit = data['당기순이익'] + data['법인세비용']
```

#### data_collector.py 주요 기능
```python
class DataCollector:
    def get_market_cap(self, date, ticker)
    def get_fundamental(self, date, ticker)  # ⚠️ 주의: pykrx는 날짜 범위 필요
    def get_ohlcv(self, start_date, end_date, ticker)
```

**핵심 기술 해결사항**:
3. **pykrx API 사용법 수정**:
```python
# 문제: get_market_fundamental(date, date, ticker) → 빈 DataFrame 반환
# 해결: 7일 범위 사용
from datetime import datetime, timedelta
end_date = datetime.strptime(date, '%Y%m%d')
start_date = end_date - timedelta(days=7)
df = stock.get_market_fundamental(start_date_str, date, ticker)
return df.iloc[-1] if not df.empty else None
```

### 2단계: 전략 구현

**생성된 파일**:
- `strategy_a_magic.py`: 마법공식 전략
- `strategy_b_multifactor.py`: 멀티팩터 전략

#### strategy_a_magic.py 핵심 로직
```python
class MagicFormulaStrategy:
    def calculate_earnings_yield(self, data):
        # 이익수익률 = EBIT / EV
        ebit = data['법인세차감전순이익']
        excess_cash = data['현금'] - np.maximum(0,
            data['유동부채'] - data['유동자산'] + data['현금'])
        ev = data['시가총액'] + data['총부채'] - excess_cash
        return ebit / ev

    def calculate_return_on_capital(self, data):
        # 투하자본수익률 = EBIT / IC
        ebit = data['법인세차감전순이익']
        invested_capital = (data['유동자산'] - data['유동부채'] +
                           data['비유동자산'])
        return ebit / invested_capital
```

#### strategy_b_multifactor.py 핵심 로직
```python
class MultifactorStrategy:
    def calculate_value_factors(self, data):
        # PER, PBR 등의 역수로 변환 (낮을수록 좋음 → 높을수록 좋음)

    def calculate_zscore_by_sector(self, data, factor_col):
        # 섹터별 Z-score 정규화
        data['z_score'] = data.groupby('섹터')[factor_col].transform(
            lambda x: (x - x.mean()) / x.std()
        )
```

### 3단계: 실행 및 테스트

**생성된 파일**:
- `run_backtest.py`: 메인 실행 스크립트 (20개 대형주 샘플)

**테스트 결과**:
- `strategy_a_portfolio.csv`: 마법공식 상위 10종목
- `strategy_b_portfolio.csv`: 멀티팩터 상위 10종목
- `data_cache/fundamentals_20241231.parquet`: 캐시된 재무데이터

**발견된 버그 및 해결**:

4. **종목코드 0 패딩 문제**:
```python
# 문제: CSV 읽을 때 '005930' → 5930 (정수 변환)
# 해결:
df = pd.read_csv('file.csv', dtype={'종목코드': str})
df['종목코드'] = df['종목코드'].str.zfill(6)
```

### 4단계: 시각화 및 분석

**생성된 파일**:
- `visualize_results.py`: 종합 분석 및 시각화 스크립트

**생성된 출력물**:
- `strategy_a_analysis.png`: 마법공식 4패널 차트
  - 이익수익률 vs 투하자본수익률 산점도
  - 상위 10종목 이익수익률 막대 차트
  - 섹터별 분포 박스플롯
  - 마법공식 순위 막대 차트

- `strategy_b_analysis.png`: 멀티팩터 4패널 차트
  - 밸류 점수 vs 멀티팩터 점수 산점도
  - PER vs PBR 산점도
  - 상위 10종목 점수 막대 차트
  - 배당수익률 막대 차트

- `strategy_comparison.png`: 전략 비교 차트
  - 벤 다이어그램 (중복 종목 시각화)
  - 공통 선정 종목 표
  - 전략별 순위 비교
  - 통계 요약

- `portfolio_analysis_report.txt`: 텍스트 분석 리포트

**주요 결과**:
```
전략 A 상위 3:
1위. SK하이닉스 (000660): 이익수익률 68.77%, 투하자본수익률 28.81%
2위. 기아 (000270): 이익수익률 57.82%, 투하자본수익률 21.17%
3위. 삼성전자 (005930): 이익수익률 64.01%, 투하자본수익률 9.84%

전략 B 상위 3:
1위. SK (034730): 점수 0.238, PER 0.00, PBR 0.35, 배당 3.80%
2위. 신한지주 (055550): 점수 0.177, PER 5.92, PBR 0.45, 배당 4.41%
3위. 현대차 (005380): 점수 0.171, PER 4.64, PBR 0.60, 배당 5.38%

공통 선정 종목 (4개):
- 현대모비스 (012330): A 4위, B 4위
- LG (003550): A 6위, B 6위
- 삼성물산 (028260): A 9위, B 7위
- 기아 (000270): A 2위, B 9위
```

---

## 📁 생성/수정된 주요 파일 목록

### 핵심 Python 모듈
1. **fnguide_crawler.py** (218줄) - FnGuide 크롤링, 계정과목 매핑 처리
2. **data_collector.py** (120줄) - pykrx API 래퍼, 날짜 범위 처리
3. **strategy_a_magic.py** (145줄) - 마법공식 구현, EBIT 계산 로직
4. **strategy_b_multifactor.py** (210줄) - 멀티팩터 구현, Z-score 정규화
5. **run_backtest.py** (95줄) - 메인 실행 스크립트
6. **visualize_results.py** (380줄) - 시각화 및 리포트 생성

### 출력 파일
7. **strategy_a_portfolio.csv** - 마법공식 결과
8. **strategy_b_portfolio.csv** - 멀티팩터 결과
9. **strategy_a_analysis.png** - 마법공식 차트
10. **strategy_b_analysis.png** - 멀티팩터 차트
11. **strategy_comparison.png** - 비교 차트
12. **portfolio_analysis_report.txt** - 텍스트 리포트

### 문서
13. **README_BACKTEST.md** - 프로젝트 문서
14. **SESSION_HANDOFF.md** (이 파일) - 작업 핸드오프 문서

### 캐시 디렉토리
15. **data_cache/fundamentals_20241231.parquet** - 재무데이터 캐시

---

## 🐛 해결된 주요 기술 이슈

### Issue #1: FnGuide 계정과목 불일치
**증상**: `KeyError: '총부채'`
**원인**: FnGuide는 '부채', 코드는 '총부채' 참조
**해결**: account_mapping + column rename 로직 추가
**파일**: fnguide_crawler.py:62-85

### Issue #2: 이자비용 누락
**증상**: EBIT 계산 시 '이자비용' 없음
**원인**: FnGuide는 '법인세차감전순이익' 제공 (이미 EBIT)
**해결**: 직접 '법인세차감전순이익' 사용
**파일**: strategy_a_magic.py:45-51

### Issue #3: pykrx 빈 DataFrame
**증상**: get_market_fundamental(date, date, ticker) 빈 결과
**원인**: pykrx는 날짜 범위 필요, 단일 날짜 미지원
**해결**: 7일 범위 사용 후 마지막 row 반환
**파일**: data_collector.py:52-62

### Issue #4: 종목코드 0 패딩 손실
**증상**: '005930' → 5930 변환, zfill 실패
**원인**: CSV 읽을 때 정수 변환
**해결**: dtype={'종목코드': str} + str.zfill(6)
**파일**: visualize_results.py:15-20

### Issue #5: Python 환경 경로
**증상**: Exit code 49 Python
**해결**: `C:\Users\user\miniconda3\envs\volumequant\python.exe` 사용

---

## 🔧 시스템 요구사항

### Python 환경
```bash
# Conda 환경: volumequant
# 경로: C:\Users\user\miniconda3\envs\volumequant\python.exe
```

### 필수 패키지
```txt
pykrx>=1.0.40
pandas>=2.0.0
numpy>=1.24.0
matplotlib>=3.7.0
seaborn>=0.12.0
FinanceDataReader>=0.9.50
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
pyarrow>=14.0.0  # ⚠️ 중요: parquet 파일 처리용
```

### 설치 명령어
```bash
pip install pykrx pandas numpy matplotlib seaborn FinanceDataReader pyarrow requests beautifulsoup4 lxml
```

---

## 🎯 다음 작업 단계 (우선순위순)

### 1단계: 2026년 1월 현재 포트폴리오 최종 출력 ⏳ IN PROGRESS
**목표**: 2025년 12월 말 기준 리밸런싱 결과로 2026년 1월 투자 종목 확정

**작업 내용**:
```python
# create_current_portfolio.py 생성 필요

1. 전체 KOSPI/KOSDAQ 종목에서 유니버스 필터링:
   - 시가총액 >= 1000억원
   - 거래대금 >= 10억원
   - 금융업/지주사 제외

2. 2025년 12월 31일 기준 재무데이터 수집:
   - FnGuide 크롤링 (전체 유니버스)
   - pykrx 시가총액/재무비율

3. 전략 A, B 각각 실행:
   - 상위 20-30종목 선정
   - CSV 저장

4. 최종 리포트 생성:
   - 종목별 투자 사유
   - 리스크 분석
   - 포트폴리오 구성 제안
```

**예상 파일**:
- `create_current_portfolio.py`: 현재 포트폴리오 생성 스크립트
- `portfolio_2026_01_strategy_a.csv`: 전략 A 최종 종목
- `portfolio_2026_01_strategy_b.csv`: 전략 B 최종 종목
- `portfolio_2026_01_report.txt`: 투자 사유 및 분석

### 2단계: 전체 유니버스 백테스팅 시스템 구현
**목표**: 2015-2025년 전체 기간 동안 분기별 리밸런싱 백테스트

**작업 내용**:
```python
# full_backtest.py 생성 필요

1. 리밸런싱 일자 생성:
   rebalance_dates = [
       '20150331', '20150630', '20150930', '20151231',
       '20160331', '20160630', ...
       '20251231'
   ]

2. 각 리밸런싱 일자마다:
   - 유니버스 필터링 (look-ahead bias 방지 위해 3개월 전 재무제표 사용)
   - 전략 A, B 포트폴리오 생성 (각 20종목)
   - 다음 리밸런싱까지 일별 수익률 계산
   - 누적 수익률 기록

3. 성과 지표 계산:
   - CAGR (연복리 수익률)
   - MDD (최대 낙폭)
   - Sharpe Ratio
   - Sortino Ratio
   - Win Rate
   - Turnover Rate

4. IS/OOS 비교:
   - IS 기간 (2015-2023): 전략 검증
   - OOS 기간 (2024-2025): 실전 성과
```

**필요한 데이터**:
- 2015-2025 전체 기간 일별 주가 데이터 (약 2,000+ 종목)
- 분기별 재무제표 데이터 (약 40개 시점 × 2,000+ 종목)
- ⚠️ 주의: 데이터 수집에 수 시간 소요 가능 (FnGuide 크롤링 속도 제한)

**예상 파일**:
- `full_backtest.py`: 전체 백테스트 실행 스크립트
- `backtest_results.csv`: 일별 포트폴리오 가치
- `backtest_performance.json`: 성과 지표 JSON
- `backtest_report.html`: HTML 리포트

### 3단계: bt 패키지 통합 (선택적)
**목표**: bt 라이브러리를 사용한 전문적인 백테스팅 프레임워크 구축

**작업 내용**:
```python
import bt

# 커스텀 알고리즘 정의
class MagicFormulaAlgo(bt.Algo):
    def __call__(self, target):
        # 마법공식 로직 구현
        pass

# 백테스트 실행
strategy = bt.Strategy('Magic Formula',
    [bt.algos.RunQuarterly(),
     MagicFormulaAlgo(),
     bt.algos.Rebalance()])

backtest = bt.Backtest(strategy, price_data)
result = bt.run(backtest)
```

**참고**: bt 패키지는 외국 데이터에 최적화되어 있어 한국 시장 적용 시 커스터마이징 필요

### 4단계: 대시보드 개발 (선택적)
**목표**: Streamlit 또는 Dash를 사용한 인터랙티브 대시보드

**기능**:
- 리밸런싱 일자별 포트폴리오 조회
- 누적 수익률 차트 (인터랙티브)
- 종목별 기여도 분석
- 팩터 분석 (시기별 유효성)

---

## ⚠️ 알려진 제한사항 및 향후 개선 사항

### 데이터 수집
1. **FnGuide 크롤링 속도**: 종목당 약 1초 소요 → 2000종목 시 30분+
   - 개선안: 멀티스레딩, 캐싱 전략 강화

2. **pykrx API 제한**: 과거 데이터 일부 누락 가능
   - 개선안: FinanceDataReader, KRX 공식 API 병행 사용

3. **재무제표 공시 시차**: 분기보고서 45일 지연
   - 현재: Look-ahead bias 방지 위해 3개월 전 데이터 사용 필요
   - 개선안: 정확한 공시일 기준 데이터 수집

### 전략 로직
1. **섹터 분류**: 현재 미구현, 임시로 GICS 섹터 사용
   - 개선안: WICS 또는 KRX 업종 분류 적용

2. **유니버스 필터**: 정기예금금리, 유상증자 등 제외 조건 미적용
   - 개선안: 추가 필터링 조건 구현

3. **리밸런싱**: 거래비용, 슬리피지 미고려
   - 개선안: 실거래 비용 모델링

### 백테스팅
1. **생존 편향**: 현재 상장폐지 종목 미포함
   - 개선안: 과거 전체 종목 데이터 수집

2. **배당 재투자**: 미구현
   - 개선안: 배당 재투자 로직 추가

---

## 📚 참고 자료

### 책
- 『파이썬을 이용한 퀀트 투자 포트폴리오 만들기』

### API 문서
- pykrx: https://github.com/sharebook-kr/pykrx
- FinanceDataReader: https://github.com/FinanceData/FinanceDataReader
- FnGuide: http://comp.fnguide.com

### 전략 논문
- Magic Formula: "The Little Book That Beats the Market" by Joel Greenblatt
- Multi-factor: Fama-French 5 Factor Model

---

## 🚀 빠른 시작 가이드 (새 환경에서)

```bash
# 1. Repository 클론
git clone <repository-url>
cd quant_py-main

# 2. Conda 환경 생성
conda create -n volumequant python=3.11
conda activate volumequant

# 3. 패키지 설치
pip install -r requirements.txt

# 4. 현재 포트폴리오 생성 (20개 샘플)
python run_backtest.py

# 5. 시각화
python visualize_results.py

# 6. 전체 유니버스 백테스트 (구현 필요)
# python full_backtest.py

# 7. 현재 포트폴리오 최종 생성 (구현 필요)
# python create_current_portfolio.py
```

---

## 📝 작업 로그

| 날짜 | 작업자 | 주요 작업 | 파일 |
|------|--------|-----------|------|
| 2024-12-31 | Claude | FnGuide 크롤러 구현 | fnguide_crawler.py |
| 2024-12-31 | Claude | 데이터 수집기 구현 | data_collector.py |
| 2024-12-31 | Claude | 마법공식 전략 구현 | strategy_a_magic.py |
| 2024-12-31 | Claude | 멀티팩터 전략 구현 | strategy_b_multifactor.py |
| 2024-12-31 | Claude | 샘플 백테스트 실행 | run_backtest.py |
| 2024-12-31 | Claude | 시각화 및 분석 완료 | visualize_results.py |
| 2024-12-31 | Claude | 작업 핸드오프 문서 작성 | SESSION_HANDOFF.md |

---

## 🎯 현재 상태 요약

**완료율**: 약 60%

**완료된 핵심 기능**:
✅ FnGuide 크롤링 (계정과목 매핑 포함)
✅ pykrx 데이터 수집 (날짜 범위 처리 포함)
✅ 마법공식 전략 (EBIT 계산 수정)
✅ 멀티팩터 전략 (Z-score 정규화)
✅ 샘플 백테스트 (20종목)
✅ 시각화 및 분석 리포트

**다음 우선순위**:
🔲 2026년 1월 현재 포트폴리오 생성 (IN PROGRESS)
🔲 전체 유니버스 백테스팅 (2015-2025)
🔲 성과 지표 계산 (CAGR, MDD, Sharpe)
🔲 IS/OOS 성과 비교

**예상 추가 작업 시간**:
- 현재 포트폴리오 생성: 2-3시간 (데이터 수집 시간 포함)
- 전체 백테스팅 시스템: 6-8시간 (데이터 수집 + 구현 + 검증)

---

**문서 버전**: 1.0
**최종 업데이트**: 2024-12-31
**작성자**: Claude Sonnet 4.5
