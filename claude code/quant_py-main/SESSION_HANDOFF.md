# 한국 주식 퀀트 포트폴리오 시스템 - 기술 문서

## 문서 개요

**버전**: 5.0
**최종 업데이트**: 2026-02-03
**작성자**: Claude Opus 4.5

---

## 1. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                         데이터 수집 레이어                            │
├─────────────────────────────────────────────────────────────────────┤
│  pykrx API              │  FnGuide Crawler                           │
│  - 시가총액              │  - 재무제표 (연간/분기)                     │
│  - OHLCV                │  - 컨센서스 (Forward EPS/PER)              │
│  - 지수 데이터           │  - TTM 계산                                │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         전략 레이어                                   │
├─────────────────────────────────────────────────────────────────────┤
│  Strategy A (마법공식)     │  Strategy B (멀티팩터)    │  Strategy C  │
│  - 이익수익률 (EBIT/EV)   │  - Value 40%             │  - Growth 40%│
│  - 투하자본수익률 (ROC)   │  - Quality 40%           │  - Safety 25%│
│                          │  - Momentum 20%          │  - Value 20% │
│                          │                          │  - Mom. 15%  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         모니터링 레이어 (v6.4)                        │
├─────────────────────────────────────────────────────────────────────┤
│  Quality Score (맛)        │  Price Score (값)                       │
│  - 전략등급 25%            │  - RSI 30% (70-80 = "좋은 과열")         │
│  - PER 25%                │  - 볼린저 20%                            │
│  - ROE 20%                │  - 거래량 20%                            │
│  - 회복여력 15%            │  - 이격도 15%                            │
│  - 정배열 15%              │  - 52주위치 15%                          │
│                                                                      │
│  4분류: 🚀모멘텀 | 🛡️눌림목 | 🟡관망 | 🚫금지                         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         출력 레이어                                   │
├─────────────────────────────────────────────────────────────────────┤
│  텔레그램 알림 (3개 메시지)  │  JSON/CSV 저장  │  Git 자동 푸시        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 핵심 모듈 상세

### 2.1 fnguide_crawler.py (529줄)

FnGuide 웹사이트에서 재무제표와 컨센서스 데이터를 크롤링하는 모듈.

#### 주요 함수

**`get_financial_statement(ticker, use_cache=True)`** (71-152줄)
```python
# FnGuide에서 재무제표 크롤링
# URL: http://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?pGB=1&gicode=A{ticker}
#
# 반환 테이블:
# - data[0]: 포괄손익계산서 (연간)
# - data[1]: 포괄손익계산서 (분기)
# - data[2]: 재무상태표 (연간)
# - data[3]: 재무상태표 (분기)
# - data[4]: 현금흐름표 (연간)
# - data[5]: 현금흐름표 (분기)
```

**`extract_magic_formula_data(fs_dict, base_date, use_ttm=True)`** (188-365줄)
```python
# TTM (Trailing Twelve Months) 계산 로직
#
# 손익계산서/현금흐름표 항목: 최근 4분기 합산
flow_accounts = ['당기순이익', '법인세비용', '매출액', '영업이익', ...]

# 재무상태표 항목: 최근 분기 스냅샷
stock_accounts = ['자산', '부채', '유동부채', '유동자산', '자본', ...]

# 공시 시차 반영
cutoff_date_quarterly = base_dt - timedelta(days=45)   # 분기: 45일
cutoff_date_annual = base_dt - timedelta(days=90)      # 연간: 90일
```

**`get_consensus_data(ticker)`** (372-445줄)
```python
# FnGuide 메인 페이지에서 컨센서스 추출
# URL: http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{ticker}
#
# 추출 항목:
# - forward_eps: Forward EPS 컨센서스
# - forward_per: Forward PER
# - target_price: 목표주가
# - analyst_count: 애널리스트 수
```

#### 계정 매핑 (330-346줄)
```python
account_mapping = {
    '당기순이익': '당기순이익',
    '세전계속사업이익': '세전계속사업이익',  # EBIT 대안
    '부채': '총부채',
    '현금및현금성자산': '현금',
    '영업활동으로인한현금흐름': '영업현금흐름',
}
```

---

### 2.2 strategy_a_magic.py (225줄)

조엘 그린블라트의 마법공식 구현.

#### 핵심 공식

**이익수익률 (Earnings Yield)** (16-47줄)
```python
def calculate_earnings_yield(self, data):
    # EBIT = 법인세차감전순이익 또는 (당기순이익 + 법인세비용)
    if '법인세차감전순이익' in data.columns:
        ebit = data['법인세차감전순이익']
    else:
        ebit = data['당기순이익'] + data['법인세비용']

    # 여유자금 = 현금 - max(0, 유동부채 - 유동자산 + 현금)
    excess_cash = data['현금'] - np.maximum(0,
                   data['유동부채'] - data['유동자산'] + data['현금'])

    # EV = 시가총액 + 총부채 - 여유자금
    ev = data['시가총액'] + data['총부채'] - excess_cash

    # 이익수익률 = EBIT / EV
    return ebit / ev
```

**투하자본수익률 (Return on Capital)** (49-75줄)
```python
def calculate_roc(self, data):
    # 투하자본(IC) = 순운전자본 + 순고정자산
    # = (유동자산 - 유동부채) + (비유동자산 - 감가상각비)
    ic = (data['유동자산'] - data['유동부채']) + \
         (data['비유동자산'] - data['감가상각비'])

    return ebit / ic
```

**순위 계산** (77-112줄)
```python
def calculate_magic_formula_score(self, data):
    # 1. 이익수익률 순위 (높을수록 좋음)
    ey_rank = data['이익수익률'].rank(ascending=False)

    # 2. 투하자본수익률 순위 (높을수록 좋음)
    roc_rank = data['투하자본수익률'].rank(ascending=False)

    # 3. 순위 합산 → 최종 순위
    combined_rank = ey_rank + roc_rank
    data['마법공식_순위'] = combined_rank.rank(ascending=True)
```

---

### 2.3 strategy_b_multifactor.py (341줄)

밸류 + 퀄리티 + 모멘텀 멀티팩터 전략.

#### 팩터 구성

**밸류 팩터** (17-60줄)
```python
# 낮을수록 좋음 → Z-Score에 음수 부호
PER = 시가총액 / 당기순이익       # -Z-Score
PBR = 시가총액 / 자본            # -Z-Score
PCR = 시가총액 / 영업현금흐름     # -Z-Score
PSR = 시가총액 / 매출액          # -Z-Score
```

**퀄리티 팩터** (62-91줄)
```python
# 높을수록 좋음
ROE = 당기순이익 / 자본 * 100
GPA = 매출총이익 / 자산 * 100
CFO = 영업현금흐름 / 자산 * 100
```

**모멘텀 팩터** (93-146줄)
```python
def calculate_momentum(self, data, price_df):
    lookback_days = 12 * 21  # 12개월 (252 거래일)
    skip_days = 1 * 21       # 최근 1개월 제외 (21 거래일)

    # 12개월 전 가격 대비 수익률 (최근 1개월 제외)
    end_price = prices.iloc[-(skip_days + 1)]
    start_price = prices.iloc[-min_required]
    momentum = (end_price / start_price - 1) * 100
```

**종합 점수 계산** (243-264줄)
```python
# 가중치: Value 40% + Quality 40% + Momentum 20%
data['멀티팩터_점수'] = (
    data['밸류_점수'] * 0.4 +
    data['퀄리티_점수'] * 0.4 +
    data['모멘텀_점수'] * 0.2
)

# 모멘텀 데이터 없는 종목은 자동 제외 (245-250줄)
data = data[data['모멘텀_점수'].notna()].copy()
```

---

### 2.4 strategy_c_forward_eps.py (672줄)

Forward EPS 기반 하이브리드 전략.

#### 필터 조건 (32-42줄)
```python
DEBT_RATIO_MAX = 200          # 부채비율 < 200%
INTEREST_COVERAGE_MIN = 1.0   # 이자보상배율 > 1
FORWARD_PER_MAX = 20          # Forward PER < 20
MIN_ANALYST_COUNT = 2         # 최소 애널리스트 수
```

#### 팩터 가중치 (39-43줄)
```python
GROWTH_WEIGHT = 0.40   # 성장성 (EPS 수정률)
SAFETY_WEIGHT = 0.25   # 안전성 (부채비율, 이자보상배율)
VALUE_WEIGHT = 0.20    # 가치 (Forward PER)
MOMENTUM_WEIGHT = 0.15 # 모멘텀 (가격 추세)
```

#### 점수 계산 함수들

**성장점수** (306-326줄)
```python
def calculate_growth_score(df):
    # Forward EPS의 Z-Score (높을수록 좋음)
    eps_zscore = calculate_zscore(df['forward_eps'])
    return eps_zscore
```

**안전점수** (329-354줄)
```python
def calculate_safety_score(df):
    # 부채비율 역수 (낮을수록 좋음) * 0.5
    debt_inv = 1 / (df['debt_ratio'] / 100 + 0.1)

    # 이자보상배율 (높을수록 좋음, 상한 20) * 0.5
    ic_clipped = df['interest_coverage'].clip(upper=20)
```

**가치점수** (357-372줄)
```python
def calculate_value_score(df):
    # Forward PER 역수 (낮을수록 좋음)
    per_inv = 1 / df['forward_per']
    return calculate_zscore(per_inv)
```

---

### 2.5 daily_monitor.py (1289줄)

일별 포트폴리오 모니터링 시스템 v6.4.

#### Quality Score (맛) 계산 (279-363줄)

| 항목 | 가중치 | 점수 기준 |
|------|--------|-----------|
| 전략등급 | 25% | A+B=100, 단일전략=70 |
| PER | 25% | ≤5=100, ≤8=90, ≤12=75 |
| ROE proxy | 20% | ≥30%=100, ≥20%=85 |
| 회복여력 | 15% | 52주고점 대비 하락폭 |
| 정배열 | 15% | MA5>20>60>120 점수 |

```python
def calculate_quality_score(stock_info, indicators):
    weights = {
        'strategy': 0.25,
        'per': 0.25,
        'roe': 0.20,
        'recovery': 0.15,
        'alignment': 0.15,
    }
    return sum(scores[k] * weights[k] for k in weights)
```

#### Price Score (값) 계산 (366-463줄)

| 항목 | 가중치 | 점수 기준 |
|------|--------|-----------|
| RSI | 30% | 30-45=100, **70-80=85** (모멘텀) |
| 볼린저 | 20% | 하단=100, 상단+거래량=75 |
| 거래량 | 20% | 3배=100, 2배=85 |
| 이격도 | 15% | -20%=100, +30%=0 |
| 52주위치 | 15% | 급락=100, 신고가+거래량=90 |

```python
def calculate_price_score(indicators):
    # RSI 70-80 = "좋은 과열" (모멘텀 플레이 인정)
    if 70 <= rsi <= 80:
        scores['rsi'] = 85   # ★ v6.4 핵심 변경점
```

#### 4분류 시스템 (470-533줄)

```python
def classify_stock_v64(quality_score, price_score, indicators):
    # 1. NO_ENTRY (먼저 체크)
    if ma_div >= 30:  return 'NO_ENTRY', '🚫', '이격도 과대'
    if rsi >= 85:     return 'NO_ENTRY', '🚫', 'RSI 극과열'
    if quality < 35:  return 'NO_ENTRY', '🚫', '펀더멘털 부족'

    # 2. STRONG_MOMENTUM 조건
    conditions = [
        from_high >= -10,      # 52주 고점 근처
        volume_signal >= 1.5,  # 거래량 증가
        70 <= rsi <= 85,       # "좋은 과열"
        quality >= 55,         # 기본 펀더멘털
    ]
    if sum(conditions) >= 3:
        return 'STRONG_MOMENTUM', '🚀', '강세 돌파'

    # 3. DIP_BUYING 조건
    if from_high <= -25 and rsi <= 50 and quality >= 50:
        return 'DIP_BUYING', '🛡️', '저점 매수'

    # 4. WAIT_OBSERVE (기본)
    return 'WAIT_OBSERVE', '🟡', '관망'
```

#### 결론 자동 생성 (620-657줄)

```python
def generate_conclusion(r):
    if category == 'STRONG_MOMENTUM':
        return "가는 말이 더 간다. 눌림 없는 강력한 모멘텀"

    elif category == 'DIP_BUYING':
        if per <= 8 and from_high <= -40:
            return "잃기 힘든 자리. 가격 메리트 극대화 구간"
        elif rsi <= 35:
            return "악재 해소 국면, 기술적 반등 기대"
```

#### 텔레그램 메시지 구조 (1078-1182줄)

| 메시지 | 내용 |
|--------|------|
| 1 | 시장현황 + TOP 3 상세 (맛/값 점수, 결론) |
| 2 | 🚀 강세돌파 + 🛡️ 저점매수 종목 |
| 3 | 🟡 관망 + 🚫 금지 종목 + 시스템 정보 |

---

## 3. 데이터 흐름

### 3.1 포트폴리오 생성 (create_current_portfolio.py)

```
1. pykrx에서 전체 종목 시가총액 조회
   └─ KOSPI + KOSDAQ 약 2,700개

2. 시가총액 필터 (500억 이상)
   └─ 약 1,100개 종목

3. FnGuide 재무제표 크롤링 (~50분)
   └─ TTM 데이터 추출 (손익: 4분기합산, 재무상태: 최근분기)

4. 전략 A 실행
   └─ 이익수익률 + ROC 순위 합산 → 상위 30개

5. 전략 B 실행
   └─ Value*0.4 + Quality*0.4 + Momentum*0.2 → 상위 30개

6. 전략 C 실행
   └─ Growth*0.4 + Safety*0.25 + Value*0.2 + Mom*0.15 → 상위 30개

7. 결과 저장
   └─ output/portfolio_YYYY_MM_strategy_a/b/c.csv
```

### 3.2 일별 모니터링 (daily_monitor.py)

```
1. 포트폴리오 종목 로드 (A+B+C 합집합 ~75개)

2. 각 종목별 기술적 지표 계산
   ├─ RSI (14일)
   ├─ 볼린저밴드 위치
   ├─ 이동평균 이격도 (20일, 60일)
   ├─ 52주 고저점 위치
   ├─ 거래량 신호 (20일 평균 대비)
   └─ MA 정배열 체크 (5>20>60>120)

3. 실시간 밸류에이션
   └─ 현재가 기준 PER, PBR 재계산

4. Quality(맛) + Price(값) 2축 점수 계산

5. 4분류 시스템 적용
   ├─ STRONG_MOMENTUM: 신고가+거래량+RSI70-80
   ├─ DIP_BUYING: 급락+지지선+RSI<50
   ├─ WAIT_OBSERVE: 양호하나 타이밍 대기
   └─ NO_ENTRY: 버블/과열/저품질

6. TOP 3 선정 및 결론 생성

7. 텔레그램 발송 (3개 메시지)

8. Git 자동 커밋 & 푸시
```

---

## 4. 파일 구조

```
quant_py-main/
├── 핵심 모듈
│   ├── fnguide_crawler.py      # 재무제표/컨센서스 크롤링 (529줄)
│   ├── data_collector.py       # pykrx API 래퍼
│   ├── strategy_a_magic.py     # 마법공식 (225줄)
│   ├── strategy_b_multifactor.py # 멀티팩터 (341줄)
│   └── strategy_c_forward_eps.py # Forward EPS 하이브리드 (672줄)
│
├── 실행 스크립트
│   ├── create_current_portfolio.py  # 포트폴리오 생성 (~50분)
│   ├── create_portfolio_strategy_c.py # 전략 C 단독 실행
│   ├── full_backtest.py             # 백테스트 (2015-2025)
│   └── daily_monitor.py             # 일별 모니터링 v6.4 (1289줄)
│
├── 출력 디렉토리
│   ├── output/                      # 포트폴리오 CSV
│   ├── backtest_results/            # 백테스트 결과
│   └── daily_reports/               # 일별 분석 JSON/CSV
│
├── 설정
│   ├── config.py                    # 텔레그램 설정 (gitignore)
│   └── config_template.py           # 설정 템플릿
│
└── 문서
    ├── README.md                    # 프로젝트 개요
    ├── SESSION_HANDOFF.md           # 기술 상세 문서 (이 파일)
    └── PROJECT_REPORT.md            # 결과 리포트
```

---

## 5. 환경 설정

### Python 환경
```
Python: 3.13+ (miniconda3)
```

### 필수 패키지
```bash
pip install pykrx==1.2.3 pandas numpy scipy matplotlib requests beautifulsoup4 lxml pyarrow tqdm
```

### 설정 파일 (config.py)
```python
# config.py (gitignore)
TELEGRAM_BOT_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"
GIT_AUTO_PUSH = True
```

---

## 6. 알려진 제한사항

### 데이터 관련
1. FnGuide 크롤링 속도: 종목당 ~2초 → 1,000종목 시 ~30분
2. 컨센서스 커버리지: 대형주 위주 (중소형주 커버리지 낮음)
3. 선호주/우선주: 일부 종목 재무제표 누락

### 전략 관련
1. 섹터 분류 없음: 업종 중립화 미적용
2. 거래비용: 0.3% 고정 (실제 슬리피지 미반영)

### 백테스팅 관련
1. 생존 편향: 상장폐지 종목 미포함
2. Look-ahead bias: 재무제표 공시 시차 반영 (45일/90일)
3. 배당 미반영: 배당 재투자 미구현

---

## 7. 작업 로그

| 날짜 | 주요 작업 | 파일 |
|------|-----------|------|
| 2026-01-30 | 현재 포트폴리오 생성 시스템 구현 | create_current_portfolio.py |
| 2026-01-31 | 일별 모니터링 시스템 구현 | daily_monitor.py |
| 2026-02-01 | 텔레그램 메시지 3분할 | daily_monitor.py |
| 2026-02-02 | 모멘텀 팩터 완전 구현 | strategy_b_multifactor.py |
| 2026-02-03 | v6.4 전면 리팩토링 (Quality+Price 2축) | daily_monitor.py |
| 2026-02-03 | Strategy C: Forward EPS Hybrid 구현 | strategy_c_forward_eps.py |
| 2026-02-03 | FnGuide 컨센서스 크롤러 추가 | fnguide_crawler.py |
| 2026-02-03 | 문서 정리 및 최신화 | README.md, SESSION_HANDOFF.md |

---

## 8. 빠른 시작 가이드

```bash
# 1. 패키지 설치
pip install pykrx==1.2.3 pandas numpy scipy matplotlib requests beautifulsoup4 lxml pyarrow tqdm

# 2. 설정 파일 생성
cp config_template.py config.py
# config.py에 텔레그램 토큰 입력

# 3. 포트폴리오 생성 (~50분 소요)
python create_current_portfolio.py

# 4. 일별 모니터링 (~3분 소요)
python daily_monitor.py

# 5. 백테스트 (~15분 소요)
python full_backtest.py
```

---

**문서 버전**: 5.0
**최종 업데이트**: 2026-02-03
