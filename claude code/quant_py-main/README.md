# 한국 주식 퀀트 투자 시스템

데이터 기반 한국 주식 투자 전략 백테스팅 및 포트폴리오 생성 시스템

[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 📊 프로젝트 개요

Joel Greenblatt의 마법공식(Magic Formula)과 멀티팩터 전략을 한국 주식 시장에 적용한 퀀트 투자 시스템입니다.

### 주요 특징

- ✅ **검증된 성과**: 10년 백테스팅 (2015-2025) 완료
- ✅ **높은 수익률**: 연평균 12.7~16.0% (코스피 7.6% 대비 2배)
- ✅ **낮은 리스크**: MDD -23~31% (코스피 -44% 대비 안정적)
- ✅ **자동화**: 분기별 포트폴리오 자동 생성
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
- Momentum (20%): 6개월/12개월 수익률

**특징**:
- 대형주 중심 (평균 시총 95조원, 메가캡 KOSPI)
- CAGR 16.0%, MDD -31.5%

**추천 대상**: 높은 수익 추구, 대형주 선호, 변동성 감내 가능

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
├── PROJECT_REPORT.md               # 프로젝트 결과 리포트
├── INVESTMENT_GUIDE_2026_01.md     # 투자 가이드 (2026년 1월)
├── SESSION_HANDOFF.md              # 개발 작업 로그
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
│   └── compare_strategies_abc.py   # 전략 비교
│
├── 결과 디렉토리
│   ├── output/                     # 포트폴리오 결과
│   ├── backtest_results/           # 백테스팅 결과
│   └── data_cache/                 # 데이터 캐시
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

**작성일**: 2026-01-30
**버전**: 1.0
**Python**: 3.13+

Made with ❤️ by Volume Quant Team
