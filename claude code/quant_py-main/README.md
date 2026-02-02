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

## 📡 일별 진입 타이밍 분석

선정된 포트폴리오 종목의 **매수 적기**를 매일 분석하는 시스템입니다.

### 진입 점수 (Entry Score) 산출 방식

| 지표 | 가중치 | 산출 방법 | 의미 |
|------|--------|----------|------|
| **RSI** | 25% | RSI ≤ 30 → 1.0점, RSI ≥ 70 → 0점 | 과매도 구간 탐지 |
| **52주 위치** | 25% | 저점 근접 → 1.0점, 고점 근접 → 0점 | 연간 저점 매수 기회 |
| **볼린저밴드** | 20% | 하단 접근 → 1.0점, 상단 → 0점 | 단기 과매도 탐지 |
| **이동평균 이격도** | 20% | 60일선 -20% → 1.0점, +20% → 0점 | 중기 저평가 판단 |
| **거래량 신호** | 10% | 평균 대비 2배 → 1.0점 | 관심 증가 확인 |

### 진입 신호 분류

| 등급 | 진입 점수 | 의미 | 행동 |
|------|----------|------|------|
| 🟢 **매수 적기** | ≥ 0.6 | 기술적 저점, 매수 타이밍 | 즉시 매수 검토 |
| 🟡 **관망** | 0.3 ~ 0.6 | 중립 구간 | 추가 하락 대기 |
| 🔴 **대기** | < 0.3 | 고점 구간 또는 과열 | 매수 보류 |

### 텔레그램 알림 설정

```python
# config.py 파일 생성
TELEGRAM_BOT_TOKEN = "your-bot-token"
TELEGRAM_CHAT_ID = "your-chat-id"
GIT_AUTO_PUSH = True
SCORE_BUY = 0.6      # 매수 적기 기준
SCORE_WATCH = 0.3    # 관망 기준
```

### 예시 알림 (3개 메시지 분할)

**메시지 1: 전략 설명 + 매수 추천**
```
📊 퀀트 포트폴리오 일일 리포트
📅 2026.01.30
━━━━━━━━━━━━━━━━━━━━━━━━━

📋 투자 전략
• 전략A(마법공식): 이익수익률+자본효율 높은 저평가주
• 전략B(멀티팩터): 가치+품질+모멘텀 종합 상위주

📈 포트폴리오 구성 (총 35개)
• 전략A 20개 / 전략B 20개
• 공통선정(A+B) 5개

━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 매수 추천 (1개)
펀더멘털 우수 + 현재 저평가

★ 제닉 (123330) [A+B]
   현재가: 16,360원
   진입점수: 0.78
   근거: PER 7.1 저평가, 52주고점 대비 -62% 급락
```

**메시지 2: 관망 종목 전체**
```
🟡 조정시 매수 (15개)
우량주이나 추가 하락 대기
━━━━━━━━━━━━━━━━━━━━━━━━━

• 브이티 (018290) [A]
  41,500원 | 점수 0.52
  → RSI 58, 추가 조정 대기
```

**메시지 3: 과열 종목 전체**
```
🔴 과열 주의 (19개)
우량주이나 고점권, 추격매수 금지
━━━━━━━━━━━━━━━━━━━━━━━━━

• SK하이닉스 (000660) [B]
  210,000원
  → RSI 72 과매수, 고점 근접

💡 매일 장마감 후 자동 분석
📈 Quant Bot by Volume
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
│   └── strategy_c_kosdaq_growth.py # 전략 C: 코스닥 성장 (폐기)
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

## 📝 최근 업데이트 (2026-02-02)

### v1.3 - 모멘텀 팩터 완전 구현
- **모멘텀 계산**: 12개월 수익률 (최근 1개월 제외) 기반
- **자동 제외**: 모멘텀 데이터 없는 종목 자동 필터링
- **가중치 적용**: Value 40% + Quality 40% + Momentum 20%
- **신규 TOP 종목**: 동양고속(모멘텀 6.96), 로보티즈(7.80), 삼현(4.28) 등 극강 모멘텀 종목 진입

### v1.2 - 텔레그램 알림 전면 개선
- **메시지 3분할**: 전략설명/매수추천, 관망종목, 과열종목 분리 발송
- **전체 종목 표시**: 모든 35개 종목 분석 결과 표시 (생략 없음)
- **종목별 상세 근거**: 매수/관망/과열 판단 이유 상세 제공
  - 🟢 매수: PER 저평가, 52주고점 대비 급락%, RSI 과매도
  - 🟡 관망: RSI 수치, 고점 근접, 단기 과열
  - 🔴 과열: RSI 극과열, 52주 신고가, 60일선 괴리율
- **전략 설명 추가**: 전략A(마법공식)/전략B(멀티팩터) 설명 포함
- **포트폴리오 현황**: 전략별 종목 수 및 공통 종목 표시

### v1.1 - 일별 모니터링 시스템 추가
- **daily_monitor.py**: 매일 진입 타이밍 분석
- **진입 점수 시스템**: RSI, 볼린저밴드, 52주 위치, 이격도, 거래량 종합 분석
- **텔레그램 알림**: 매수 적기 종목 실시간 알림
- **Git 자동화**: 일별 리포트 자동 커밋/푸시
- **PDF 리포트**: 프로젝트 및 포트폴리오 설명 문서 생성

### v1.0 - 초기 릴리스
- 전략 A (마법공식) 구현
- 전략 B (멀티팩터) 구현
- 10년 백테스팅 완료
- 포트폴리오 자동 생성

---

**작성일**: 2026-02-02
**버전**: 1.3.0
**Python**: 3.13+

Made with ❤️ by Volume Quant Team
