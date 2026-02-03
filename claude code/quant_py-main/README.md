# 한국 주식 퀀트 투자 시스템

데이터 기반 한국 주식 투자 전략 백테스팅, 포트폴리오 생성 및 **일별 매매 타이밍 분석** 시스템

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Daily Monitor](https://img.shields.io/badge/Daily-Monitor-green.svg)](daily_monitor.py)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://telegram.org/)

## 📊 프로젝트 개요

Joel Greenblatt의 마법공식(Magic Formula)과 멀티팩터 전략을 한국 주식 시장에 적용한 퀀트 투자 시스템입니다.

### 주요 특징

- ✅ **검증된 성과**: 10년 백테스팅 (2015-2025) 완료
- ✅ **높은 수익률**: 연평균 12.7~16.0% (코스피 7.6% 대비 2배)
- ✅ **낮은 리스크**: MDD -23~31% (코스피 -44% 대비 안정적)
- ✅ **자동화**: 분기별 포트폴리오 자동 생성
- ✅ **일별 모니터링**: 진입 타이밍 자동 분석 및 알림
- ✅ **텔레그램 연동**: 실시간 매수 신호 알림
- ✅ **투명성**: 모든 거래비용 반영, 오픈소스

### 백테스팅 성과 (2015-2025)

| 지표 | KOSPI | Strategy A | Strategy B |
|------|-------|-----------|-----------|
| **CAGR** | 7.58% | **12.7%** | **16.0%** |
| **MDD** | -43.9% | **-23.4%** | -31.5% |
| **Sharpe** | 0.27 | **0.56** | 0.50 |

## 🚀 빠른 시작

### 1. 설치

```bash
# 저장소 클론
git clone https://github.com/VolumeQuant/quant_py-main.git
cd quant_py-main

# 필수 패키지 설치
pip install pykrx==1.2.3 pandas numpy matplotlib requests beautifulsoup4 lxml pyarrow tqdm
```

### 2. 현재 포트폴리오 생성

```bash
# 최신 데이터로 포트폴리오 생성 (~50분 소요)
python create_current_portfolio.py
```

**결과**:
- `output/portfolio_2026_01_strategy_a.csv` - 전략 A (마법공식) 30종목
- `output/portfolio_2026_01_strategy_b.csv` - 전략 B (멀티팩터) 30종목
- `output/portfolio_2026_01_report.txt` - 분석 리포트

### 3. 백테스팅 실행

```bash
# 전체 백테스팅 (2015-2025)
python full_backtest.py
```

**결과**:
- `backtest_results/backtest_strategy_A_*.csv` - 전략 A 백테스트 결과
- `backtest_results/backtest_strategy_B_*.csv` - 전략 B 백테스트 결과
- `backtest_results/backtest_comparison.csv` - 전략 비교

### 4. 일별 모니터링 (진입 타이밍)

```bash
# 매일 장 마감 후 실행 (~5분 소요)
python daily_monitor.py
```

**기능**:
- 포트폴리오 종목의 기술적 지표 분석 (RSI, 볼린저밴드, 52주 위치, 이격도)
- 진입 점수(Entry Score) 산출 (0~1)
- 텔레그램 알림 자동 발송 (3개 메시지 분할)
- 종목별 매수/관망/과열 근거 자동 생성
- Git 자동 커밋/푸시

**결과**:
- `daily_reports/daily_analysis_YYYYMMDD.json` - JSON 분석 결과
- `daily_reports/daily_analysis_YYYYMMDD.csv` - CSV 상세 데이터
- `daily_reports/daily_report_YYYYMMDD.txt` - 텍스트 리포트

## 📈 투자 전략

### Strategy A - 마법공식 (안정형)

**팩터**:
- 이익수익률 (Earnings Yield): EBIT / EV
- 투하자본수익률 (ROIC): EBIT / Invested Capital

**특징**:
- 중소형주 중심 (평균 시총 3.7조원)
- 코스닥 60% (18종목) - 정부 코스닥 3000 정책 수혜 예상
- CAGR 12.7%, MDD -23.4%

**추천 대상**: 안정적 수익 추구, 중소형주 투자 가능, 장기 투자 지향

### Strategy B - 멀티팩터 (공격형)

**팩터**:
- Value (40%): PER, PBR, PCR, PSR
- Quality (40%): ROE, GPA, CFO
- Momentum (20%): 12개월 수익률 (최근 1개월 제외)

**특징**:
- 대형주 중심 (평균 시총 95조원, 메가캡 KOSPI)
- CAGR 16.0%, MDD -31.5%

**추천 대상**: 높은 수익 추구, 대형주 선호, 변동성 감내 가능

## 📡 일별 진입 타이밍 분석 v6.4

선정된 포트폴리오 종목의 **매수 적기**를 매일 분석하는 시스템입니다.

### v6.4 점수 체계: Quality(맛) + Price(값)

| 점수 | 구성 요소 | 의미 |
|------|----------|------|
| **맛 (Quality)** | 전략등급 + PER + ROE + 회복여력 + 정배열 | 펀더멘털 매력도 (0~100점) |
| **값 (Price)** | RSI + BB위치 + 거래량 + 이격도 + 52주위치 | 진입 타이밍 점수 (0~100점) |

### 4분류 시스템

| 분류 | 이모지 | 조건 | 매매 방향 |
|------|--------|------|----------|
| **강세 돌파** | 🚀 | 신고가 + 거래량 + RSI 70-80 | 추세 매수 |
| **저점 매수** | 🛡️ | 급락 + 지지선 + RSI 30-50 | 분할 매수 |
| **관망** | 🟡 | 양호하나 타이밍 대기 | 대기 |
| **진입 금지** | 🚫 | 버블/과열/저품질 | 매수 금지 |

### RSI 70-80 = "좋은 과열" 인정

기존에는 RSI 70 이상을 무조건 과열로 분류했지만, v6.4에서는 **모멘텀 플레이**를 인정합니다:
- RSI 70-80 + 거래량 증가 + 신고가 근접 = 🚀 **강세 돌파**
- RSI 85 이상 또는 이격도 +30% 이상 = 🚫 **진입 금지**

### 텔레그램 알림 설정

```python
# config.py 파일 생성
TELEGRAM_BOT_TOKEN = "your-bot-token"
TELEGRAM_CHAT_ID = "your-chat-id"
GIT_AUTO_PUSH = True
```

### 예시 알림 v6.4 (3개 메시지)

**메시지 1: 시장 현황 + TOP 3**
```
📊 퀀트 포트폴리오 v6.4
📅 2026.02.03
━━━━━━━━━━━━━━━━━━━━━━━━━

📈 시장 현황
• KOSPI: 2,850 🔺0.3%
• KOSDAQ: 870 🔻0.5%

🏆 TODAY'S TOP 3

1️⃣ 🛡️ 에스엠 (041510)
   맛: 71점 | 값: 75점
   → PER 8.1 저평가 + 볼린저 하단
   💡 우량주 저점 매수 기회

2️⃣ 🛡️ SAMG엔터 (419530)
   맛: 67점 | 값: 76점
   → PER 10.7 저평가 + 고점대비 -61%
   💡 분할 매수로 평균단가 낮추기 유리
```

**메시지 2: 모멘텀 + 눌림목**
```
🚀 강세 돌파 (2개)
신고가 + 거래량 = 추세 매수
━━━━━━━━━━━━━━━━━━━━━━━━━

• 유바이오로직스: 맛62 값54
  13,760원 | 52주 고점 근접 + 거래량 증가

🛡️ 저점 매수 (11개)
급락 + 지지선 = 분할 매수
━━━━━━━━━━━━━━━━━━━━━━━━━

• 에스엠: 맛71 값75
  PER 8.1 | RSI 44 | PER 저평가 + 볼린저 하단
```

**메시지 3: 관망 + 금지**
```
🟡 관망 (36개)
타이밍 대기
━━━━━━━━━━━━━━━━━━━━━━━━━

• 티앤엘: 맛67 값60 (추가 조정 대기)

🚫 진입 금지 (26개)
버블/과열 경고
━━━━━━━━━━━━━━━━━━━━━━━━━

• 아이티센글로벌: 이격도 과대 (+30%)

💡 맛=펀더멘털 | 값=진입타이밍
📈 Quant Bot v6.4 by Volume
```

## 💰 2026년 1월 추천 종목

### Strategy A TOP 5 (코스닥 특화)

| 순위 | 종목명 | 종목코드 | 시장 | 시가총액 |
|------|--------|----------|------|----------|
| 1 | 브이티 | 018290 | 코스닥 | 6,891억 |
| 2 | 티앤엘 | 340570 | 코스닥 | 4,251억 |
| 3 | 제룡전기 | 033100 | 코스닥 | 7,148억 |
| 4 | 월덱스 | 101160 | 코스닥 | 4,029억 |
| 5 | SOOP | 067160 | 코스닥 | 8,667억 |

### Strategy B TOP 5 (메가캡)

| 순위 | 종목명 | 종목코드 | 시장 | 시가총액 |
|------|--------|----------|------|----------|
| 1 | 삼성전자 | 005930 | 코스피 | 951조 |
| 2 | SK하이닉스 | 000660 | 코스피 | 627조 |
| 3 | 현대차 | 005380 | 코스피 | 108조 |
| 4 | LG에너지솔루션 | 373220 | 코스피 | 98조 |
| 5 | 삼성바이오로직스 | 207940 | 코스피 | 82조 |

**전체 포트폴리오**: [INVESTMENT_GUIDE_2026_01.md](INVESTMENT_GUIDE_2026_01.md) 참고

## 📁 프로젝트 구조

```
quant_py-main/
├── README.md                       # 프로젝트 개요 (이 파일)
├── README_BACKTEST.md              # 백테스팅 상세 가이드
├── BACKTEST_RESULTS.md             # 백테스트 결과 및 TOP 20 종목
├── PROJECT_REPORT.md               # 프로젝트 결과 리포트
├── INVESTMENT_GUIDE_2026_01.md     # 투자 가이드 (2026년 1월)
├── SESSION_HANDOFF.md              # 개발 작업 로그
├── config_template.py              # 설정 템플릿 (복사 후 config.py로 사용)
│
├── 핵심 전략 모듈
│   ├── strategy_a_magic.py         # 전략 A: 마법공식
│   ├── strategy_b_multifactor.py   # 전략 B: 멀티팩터
│   └── strategy_c_forward_eps.py   # 전략 C: Forward EPS 하이브리드 (v6.4)
│
├── 데이터 수집
│   ├── data_collector.py           # pykrx API 래퍼
│   ├── fnguide_crawler.py          # FnGuide 재무제표 크롤링
│   └── utils.py                    # 유틸리티 함수
│
├── 실행 스크립트
│   ├── create_current_portfolio.py # 현재 포트폴리오 생성
│   ├── full_backtest.py            # 전체 백테스팅
│   ├── compare_strategies_abc.py   # 전략 비교
│   └── daily_monitor.py            # 일별 모니터링 (진입 타이밍)
│
├── 결과 디렉토리
│   ├── output/                     # 포트폴리오 결과
│   ├── backtest_results/           # 백테스팅 결과
│   ├── daily_reports/              # 일별 분석 리포트
│   └── data_cache/                 # 데이터 캐시
│
├── 리포트
│   └── Quant_Portfolio_Report_2026Q1.pdf  # PDF 포트폴리오 리포트
│
└── 분석 차트
    ├── strategy_a_analysis.png
    ├── strategy_b_analysis.png
    └── strategy_comparison.png
```

## 🎯 투자 방법

### 포트폴리오 구성 예시 (1,000만원)

#### 보수형 (전략 A 중심)
```
브이티 (018290)      200만원
티앤엘 (340570)      200만원
제룡전기 (033100)    200만원
월덱스 (101160)      200만원
SOOP (067160)        200만원
```

#### 공격형 (전략 B 중심)
```
SK하이닉스 (000660)  300만원
현대차 (005380)      200만원
삼성전자 (005930)    200만원
LG에너지솔루션       200만원
삼성바이오로직스     100만원
```

### 리밸런싱

- **주기**: 분기별 (3월/6월/9월/12월 말)
- **방법**: 기존 종목 매도 → 신규 종목 매수
- **비용**: 거래세/수수료 고려

## 📊 데이터 소스

- **주가/시가총액**: [pykrx](https://github.com/sharebook-kr/pykrx) (한국거래소 공식 API)
- **재무제표**: [FnGuide](https://www.fnguide.com) (웹 크롤링)
- **벤치마크**: 코스피 지수, 코스닥 150

## 🔧 기술 스택

- **Python 3.13**
- **데이터 처리**: pandas, numpy
- **크롤링**: BeautifulSoup4, requests
- **시각화**: matplotlib, seaborn
- **캐싱**: pyarrow (parquet)

## ⚠️ 주의사항

### 투자 원칙

1. **분산투자**: 최소 5개 이상 종목
2. **여유자금**: 생활비 제외한 자금만 투자
3. **장기 관점**: 1년 이상 보유 권장
4. **감정 배제**: 백테스트 결과 신뢰

### 리스크

- 📉 과거 성과가 미래를 보장하지 않음
- 📉 최대 낙폭 -20~30% 가능
- 📉 개별 종목 상장폐지 가능성

## 🧪 실패 사례 연구

### Strategy C (코스닥 성장) - 폐기

**의도**: 정부 코스닥 3000 정책 수혜

**결과**: CAGR -5.33%, MDD -69.85% (참혹한 실패)

**교훈**:
- ❌ 정부 정책에만 의존
- ❌ 성장률 데이터 품질 부족
- ❌ 모멘텀 과열 종목 편입
- ✅ **펀더멘털이 정책보다 중요**

자세한 내용: [README_BACKTEST.md](README_BACKTEST.md#-폐기된-전략)

## 📚 문서

- [README_BACKTEST.md](README_BACKTEST.md) - 백테스팅 상세 가이드
- [PROJECT_REPORT.md](PROJECT_REPORT.md) - 프로젝트 최종 리포트
- [INVESTMENT_GUIDE_2026_01.md](INVESTMENT_GUIDE_2026_01.md) - 투자 실전 가이드
- [SESSION_HANDOFF.md](SESSION_HANDOFF.md) - 개발 작업 로그

## 🤝 기여

이슈 및 풀 리퀘스트 환영합니다!

## 📞 문의

- GitHub Issues: [이슈 등록](https://github.com/VolumeQuant/quant_py-main/issues)
- Email: (추후 추가)

## 📜 라이센스

MIT License

## ⚖️ 면책 조항

본 프로젝트는 교육 및 연구 목적으로 제공됩니다. 투자 권유가 아니며, 투자 결정과 그 결과에 대한 책임은 투자자 본인에게 있습니다.

---

## 📝 최근 업데이트 (2026-02-03)

### v6.4 - 리포트 포맷 대폭 업그레이드 + Forward EPS 전략 C

**일별 모니터링 v6.4**:
- **2축 점수 체계**: Quality(맛) + Price(값) 분리 → 투자 판단 명확화
- **4분류 시스템**: 🚀모멘텀 / 🛡️눌림목 / 🟡관망 / 🚫금지
- **RSI 70-80 모멘텀 인정**: "좋은 과열" 개념 도입 (추세 추종 가능)
- **TOP 3 + 한줄 결론**: "잃기 힘든 자리", "가는 말이 더 간다" 등
- **텔레그램 v6.4 포맷**: 시장현황 헤더 + TOP 3 + 분류별 상세

**전략 C: Forward EPS 하이브리드**:
- 기존 KOSDAQ 성장주 전략 폐기 → Forward EPS 기반 전략으로 교체
- 필터: 부채비율<200%, 이자보상배율>1, Forward PER<20
- 팩터 가중치: 성장 40% + 안전 25% + 가치 20% + 모멘텀 15%
- FnGuide 컨센서스 크롤링 구현

### v1.3 - 모멘텀 팩터 완전 구현
- **모멘텀 계산**: 12개월 수익률 (최근 1개월 제외) 기반
- **자동 제외**: 모멘텀 데이터 없는 종목 자동 필터링
- **가중치 적용**: Value 40% + Quality 40% + Momentum 20%

### v1.2 - 텔레그램 알림 전면 개선
- **메시지 3분할**: 전략설명/매수추천, 관망종목, 과열종목 분리 발송
- **종목별 상세 근거**: 매수/관망/과열 판단 이유 상세 제공

### v1.1 - 일별 모니터링 시스템 추가
- **daily_monitor.py**: 매일 진입 타이밍 분석
- **텔레그램 알림**: 매수 적기 종목 실시간 알림
- **Git 자동화**: 일별 리포트 자동 커밋/푸시

### v1.0 - 초기 릴리스
- 전략 A (마법공식) 구현
- 전략 B (멀티팩터) 구현
- 10년 백테스팅 완료

---

**작성일**: 2026-02-03
**버전**: 6.4.0
**Python**: 3.13+

Made with ❤️ by Volume Quant Team
