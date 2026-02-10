# 한국 주식 퀀트 포트폴리오 시스템 - 기술 문서

## 문서 개요

**버전**: 12.0
**최종 업데이트**: 2026-02-10
**작성자**: Claude Opus 4.6

---

## 핵심 변경사항 (v12.0 — 전략 구조 개편 + 유니버스 확대)

### 2026-02-10 거래대금 차등 필터 + 마법공식 사전필터만 + 멀티팩터 100%

**배경**: 삼지전자(시총 3,500억, 거래대금 32억) 같은 우량 중소형주가 일괄 거래대금 50억 필터에 탈락. 하나투어(멀티팩터 1위)가 마법공식 30% 가중에 끌려 통합순위 하락. A와 B의 팩터 중복 문제.

| 항목 | Before (v11.0) | After (v12.0) |
|------|----------------|---------------|
| 거래대금 필터 | 일괄 50억 | **시총 1조+: 50억, 3000억~1조: 20억** |
| 유니버스 규모 | ~454개 | **~617개** (+36%) |
| 사전필터 (A) | 150개, 순위 30% 반영 | **200개, 순위 미반영 (스크리닝만)** |
| 최종순위 | A 30% + B 70% | **B(멀티팩터) 100%** |
| TOP 추천 | TOP 5 | **TOP 10** (섹터 분산 + 위험 플래그 제거) |

**거래대금 차등 필터**:
```python
# 대형주(시총 1조+): 거래대금이 적으면 문제 신호
# 중소형(3000억~1조): 거래대금 낮아도 정상
TRADING_LARGE = 50  # 시총 1조 이상
TRADING_MID = 20    # 시총 3000억 ~ 1조
```

**전략 A→B 분리 근거**:
- 마법공식 이익수익률(EBIT/EV) ≈ 멀티팩터 Value(PER, PBR 등) → 팩터 중복
- 마법공식 ROIC ≈ 멀티팩터 Quality(ROE, GPA, CFO) → 팩터 중복
- A 30% 가중이 하나투어(여행업 선수금→높은 부채→낮은 이익수익률) 같은 업종 특성 종목을 불이익
- 해결: A는 "이익도 못 내는 종목" 걸러내는 사전필터만, 순위는 B가 전담

**검증 결과** (2026-02-09 기준):
- 유니버스: 809 → 거래대금 차등 → 617 → 금융/지주 제외 → 571
- 사전필터: 200개 통과
- 하나투어: **멀티팩터 4위** (이전: 통합 23위에서 밀림 → 이제 상위권)
- 삼지전자: 중소형 20억 기준 통과 → 포트폴리오 포함

**수정 파일**:
1. `create_current_portfolio.py` — 거래대금 차등 필터, 사전필터 200, 통합순위 제거 → 멀티팩터 100%
2. `send_telegram_auto.py` — TOP 10 추천, 전략 설명 업데이트, 10위 아이콘 수정
3. `config_template.py` — PREFILTER_N=200, MIN_TRADING_VALUE 제거
4. `telegram_daily.yml` / `telegram_test.yml` — PREFILTER_N=200, MIN_TRADING_VALUE 제거

---

## 핵심 변경사항 (v11.0 — Forward PER 실적 개선 시그널)

### 2026-02-09 FnGuide 컨센서스 Forward PER → EPS개선도 팩터 추가

**배경**: 기존 시스템은 Trailing PER만 사용 — "과거에 싼 주식"만 찾음. FnGuide Forward PER 데이터(커버리지 ~80%)가 이미 크롤러에 구현되어 있었지만 한 번도 호출되지 않고 있었음.

**핵심 아이디어**: Forward PER < Trailing PER = 실적이 좋아지고 있다는 시그널 → **"싸면서 좋아지고 있는 주식"**을 찾는다.

| 항목 | Before (v10.5) | After (v11.0) |
|------|----------------|---------------|
| Forward PER | 크롤러에만 존재 (미사용) | **파이프라인에 연결, Quality 팩터에 추가** |
| Quality 팩터 | ROE + GPA + CFO (3개) | **ROE + GPA + CFO + EPS개선도 (4개)** |
| EPS개선도 | 없음 | **(Trailing PER - Forward PER) / Trailing PER * 100** |
| 컨센서스 수집 | 없음 | **4.5단계: 150개 종목 FnGuide 컨센서스** |
| 텔레그램 표시 | PER 29.2 | **PER 29.2→5.3** (Forward PER 병기) |
| 소요 시간 | ~35초 | **~120초** (컨센서스 수집 +75초) |

**EPS개선도 계산**:
```python
# 양수 = 실적 개선 (Forward PER이 Trailing보다 낮음)
# 음수 = 실적 악화 (Forward PER이 Trailing보다 높음)
EPS개선도 = (Trailing_PER - Forward_PER) / Trailing_PER * 100

# 예시:
# SK하이닉스: PER 29.2 → Forward 5.3 = +78.6% (대폭 개선)
# 효성: PER 5.67 → Forward 8.0 = -41.1% (실적 악화)
```

**NaN 처리**: Forward PER이 없는 ~20% 종목은 EPS개선도 NaN → `data[quality_factors].mean(axis=1)`이 나머지 3개 팩터(ROE/GPA/CFO) 평균으로 자동 처리 (pandas `skipna=True`).

**파이프라인 변경**:
```
[4단계] OHLCV 로드
[전략 A] 마법공식 사전 필터 → 150종목
[4.5단계] FnGuide 컨센서스 수집 (Forward PER) ← NEW
  → get_consensus_batch(150개, delay=0.5) → forward_per 컬럼
[전략 B] 멀티팩터 스코어링
  → Forward PER 병합 → EPS개선도 계산 → Quality z-score에 추가
[통합순위] A30% + B70% → TOP 30
```

**검증 결과** (2026-02-06 기준):
- Forward PER 확보: 117/150 (78%), 최종 30종목 중 24/30 (80%)
- EPS개선도 계산: 116/150 (Forward PER + Trailing PER 둘 다 양수인 종목)
- TOP 5 실적 개선: SK하이닉스 +78.6%, KT +70.8%, HD한국조선해양 +67.3%
- TOP 3 실적 악화: 효성 -41.1%, 에스엘 -21.1%, 기아 -14.8%

**수정 파일**:
1. `strategy_b_multifactor.py` — `calculate_quality_factors()`에 EPS개선도 추가, 윈저라이징, z-score 계산
2. `create_current_portfolio.py` — 4.5단계 컨센서스 수집, `run_strategy_b_scoring()`에 `consensus_df` 파라미터, forward_per 병합
3. `send_telegram_auto.py` — Forward PER 추출(portfolio_fwd_per), 텔레그램 메시지에 "PER X→Y" 형식 표시

---

## 핵심 변경사항 (v10.5 — AI 브리핑 구분선 안정화)

### 2026-02-09 Gemini [SEP] 의존 제거 → 코드 후처리 구분선

**문제**: Gemini가 `[SEP]` 마커를 불규칙하게 삽입 — 종목 사이 구분선이 랜덤하게 나타나거나 사라짐

| 항목 | Before (v10.4) | After (v10.5) |
|------|----------------|---------------|
| 구분선 생성 | Gemini가 `[SEP]` 마커 삽입 | **코드가 regex로 자동 삽입** |
| 프롬프트 | "종목 사이에 [SEP] 넣어줘" | **"구분선/[SEP] 넣지 마. 코드가 처리"** |
| 감지 방식 | 텍스트에서 `[SEP]` 문자열 치환 | **`<b>종목명(6자리티커)</b>` 패턴 regex** |
| 안정성 | Gemini 응답에 따라 불안정 | **100% 안정 (코드 기반)** |

**구분선 삽입 로직** (`convert_markdown_to_html()`):
```python
# ⚠️ 섹션에서 <b>종목명 (6자리티커)</b> 패턴을 regex로 감지
# 2번째 종목부터 앞에 ───────── 구분선 자동 삽입
idx = result.find('⚠️')
if idx != -1:
    before = result[:idx]
    after = result[idx:]
    count = [0]
    def _sep(m):
        count[0] += 1
        if count[0] <= 1:
            return m.group(0)
        return f'─────────\n{m.group(0)}'
    after = re.sub(r'<b>[^<]+?\(\d{6}\)</b>', _sep, after)
    result = before + after
```

**수정 파일**:
1. `gemini_analysis.py` — 프롬프트에서 [SEP] 지시 제거, `convert_markdown_to_html()` regex 기반 구분선 로직

**교훈**: AI 출력 포맷에 의존하면 불안정 → 가능한 한 코드가 후처리하는 것이 안정적

---

## 핵심 변경사항 (v10.4 — 퀀트 TOP 5 자동 추천)

### 2026-02-09 위험 플래그 연동 + 섹터 분산 자동 선정

**변경**: 퀀트 TOP 30에서 위험 플래그 제외 + 섹터 분산으로 5종목 자동 추천

| 항목 | 내용 |
|------|------|
| 위험 플래그 연동 | AI 브리핑의 `compute_risk_flags()` 재사용 → 위험 종목 자동 제외 |
| 섹터 분산 | `get_broad_sector()` 대분류 (반도체/자동차/바이오/게임/엔터) |
| 진입 전략 | RSI<40 즉시(과매도), <60 즉시, <70 분할, ≥70 대기 |
| 비중 | 25/25/20/15/15% (순위 기반 고정) |
| 전송 | 별도 메시지로 채널+개인봇 전송 |

**선정 로직**:
```
통합순위 1위부터 순회:
  → compute_risk_flags() 있으면 스킵 (SOOP -51% 급락, 제룡전기 -8.7% 급락 등)
  → 같은 대분류 섹터 이미 있으면 스킵 (SK하이닉스 → 반도체 중복)
  → 5종목 채워질 때까지 반복
```

**수정 파일**:
1. `send_telegram_auto.py` — `select_top5()`, `format_recommendation()`, TOP 5 전송 블록 추가

---

## 핵심 변경사항 (v10.3 — AI 브리핑 v3 정량 리스크 스캐너)

### 2026-02-09 해외 프로젝트 구조 적용

**변경**: AI 브리핑을 "정량 리스크 스캐너" 구조로 전면 개편 (eps-momentum-us 참조)

| 항목 | Before (v10.2) | After (v10.3) |
|------|----------------|---------------|
| 위험 감지 | 5개 단순 alert (RSI/52주/전일비) | **6개 정량 플래그** (코드 계산) |
| 프롬프트 | raw 데이터 + alert 전달 | **종목별 인라인 플래그 + 설명 섹션** |
| 출력 포맷 | plain text | **Telegram HTML** (bold, 분리선) |
| 종목 구분 | 없음 | **regex 코드 후처리 구분선** (v10.5에서 [SEP]→regex 전환) |
| ✅ 클린 리스트 | Gemini 생성 (포맷 불안정) | **코드 직접 생성** |
| temperature | 0.3 고정 | **0.2 → 실패시 0.3 재시도** |
| 응답 추출 | response.text 직접 | **extract_text() 헬퍼** |

**6가지 위험 플래그**:
- 🔺 과매수 (RSI≥75) | 📉 52주 급락 (≤-35%) | ⚠️ 전일 급락 (≤-5%)
- 🔺 전일 급등 (≥+8%) | 💰 고평가 (PER>40) | 📊 거래량 폭발 (≥3배)

**수정 파일**:
1. `gemini_analysis.py` — compute_risk_flags(), build_prompt() 재작성, convert_markdown_to_html(), extract_text()
2. `send_telegram_auto.py` — AI 브리핑 parse_mode='HTML', TOP20 종목간 여백 축소

---

## 핵심 변경사항 (v10.2 — 포트폴리오 품질 개선)

### 2026-02-09 유니버스 강화 + 멀티팩터 비중 조정 + AI 브리핑 채널 전송

**문제**: 잡주(제닉 PBR 8.2, 아이티센글로벌 PER 247)가 TOP 10에 진입
**근본 원인**: Quality(ROE) 40%가 Value 40%를 상쇄 → "비싸지만 ROE 높은" 종목이 상위 진입

| 항목 | Before (v3.1) | After (v3.2) |
|------|---------------|--------------|
| 시가총액 하한 | 1000억 | **3000억** |
| 거래대금 하한 | 30억 | **50억** |
| PER 상한 | 없음 | **60** |
| PBR 상한 | 없음 | **10** |
| Value 비중 | 40% | **50%** |
| Quality 비중 | 40% | **30%** |
| Momentum 비중 | 20% | 20% |
| Fallback (V/Q) | 50/50 | **60/40** |
| AI 브리핑 전송 | 개인봇에만 | **채널+개인봇** |

**효과**: 유니버스 ~775개 → ~450개, PER/PBR 필터로 152종목 추가 제거, 잡주 전부 탈락

**수정 파일**:
1. `create_current_portfolio.py` — 유니버스 defaults + 3.6단계 PER/PBR 필터
2. `strategy_b_multifactor.py` — Value 50% / Quality 30% / Momentum 20%
3. `config_template.py` — PER_MAX_LIMIT, PBR_MAX_LIMIT 추가
4. `send_telegram_auto.py` — AI 브리핑 채널+개인봇 전송 + SECTOR_DB 19종목 추가

---

## 핵심 변경사항 (v9.0 — Gemini AI 브리핑)

### 2026-02-08 AI 리스크 스캐너 → AI 브리핑 전환

**교훈: Gemini Search Grounding 한계**

| 시도 | 방식 | 결과 |
|------|------|------|
| 1차 | 30종목 개별 검색 요청 | 5-8개만 실제 검색, 나머지 할루시네이션 |
| 2차 | 5종목씩 배치 | 여전히 일부만 검색 |
| 3차 | temperature 0.2 | 빈 응답 빈번 |
| 4차 | temperature 0.5 | 검색 안 되면 할루시네이션 |
| **최종** | **"검색은 코드가, 분석은 AI가"** | **안정적 작동** |

**근본 원인**: Google Search Grounding은 요청당 5-8개 검색 쿼리만 생성. 30개 종목 개별 검색은 구조적으로 불가능.

**해결 원칙: "검색은 코드가, 분석은 AI가"**

| 역할 | 담당 | 내용 |
|------|------|------|
| 데이터 수집 | 코드 | PER/PBR/ROE/RSI/52주위치/전일비 |
| 주의 신호 감지 | 코드 | RSI ≥80/≤25, 52주 ≤-40%, 전일 ≤-7%/≥10% |
| 시장 동향 | AI (1개 검색) | Google Search 1회 (광범위 쿼리 → 안정적) |
| 데이터 해석 | AI | 섹터 편중, 밸류에이션, 모멘텀 패턴 분석 |

**1. gemini_analysis.py (v2 — 브리핑 모듈)**

| 항목 | Before (리스크 스캐너) | After (AI 브리핑) |
|------|----------------------|-------------------|
| AI 모델 | Gemini 2.5 Flash (temp=0.2) | Gemini 2.5 Flash (**temp=0.3**) |
| 검색 | 30종목 개별 뉴스 검색 | **시장 동향 1회만 검색** |
| 데이터 | AI가 검색으로 수집 | **코드가 구성해서 전달** |
| 주의 감지 | AI 판단 | **코드 기반 (RSI/52주/전일비)** |
| 프롬프트 | 소거법 리스크 스캐너 | **데이터 해석 브리핑** |
| 출력 | 📰시장/🚫주의/📅실적/✅미발견 | **📰시장/⚠️주의/📊특징** |
| 빈 응답 | 미처리 | **재시도 1회 + finish_reason 로그** |
| 전송 대상 | 채널+개인봇 | **채널+개인봇** (v10.2에서 복원) |

**2. 연동 구조**

```
create_current_portfolio.py → portfolio CSV
send_telegram_auto.py → 포트폴리오 메시지 전송 (채널+개인봇)
  → gemini_analysis.run_ai_analysis(None, stock_list)
  → 코드가 데이터 구성 → AI가 해석
  → AI 브리핑 채널+개인봇 전송
```

**3. 종목별 뉴스 제거**

| 항목 | Before | After |
|------|--------|-------|
| Google News RSS | 종목별 크롤링 (30회) | **완전 제거** |
| 센티먼트 분석 | 키워드 기반 (부정확) | **제거** |
| 부분 매칭 문제 | "제닉"→"키토제닉" 오매칭 | **해결 (제거)** |
| 메시지 크기 | 3389자 (분할 필요) | **2838자 (단일)** |

**4. GitHub Actions 연동**

- `GEMINI_API_KEY` GitHub Secret 추가
- `google-genai` pip install 추가
- config.py 생성 시 GEMINI_API_KEY 포함

---

## 핵심 변경사항 (v8.0 — v3.1 전략 아키텍처)

### 2026-02-07 전략 구조 개편 + 가중TTM + 공동순위 제거

**1. A→필터, B→스코어링, A30%+B70% 통합순위**

| 항목 | Before (v3.0) | After (v3.1) |
|------|---------------|--------------|
| Strategy A | 30종목 선정 | **150종목 사전 필터** |
| Strategy B | 30종목 선정 | **150종목 전체 스코어링** |
| 최종 선정 | A∩B 교집합 | **A30%+B70% 통합순위 TOP 30** |
| 출력 | strategy_a/b.csv 분리 | **portfolio_YYYY_MM.csv 통합** |
| TTM | 균등 합산 | **가중TTM (40/30/20/10%)** |
| 텔레그램 | 3개 메시지 (교집합+A+B) | **1~2개 메시지 (TOP 20 상세)** |
| 순위 | `method='average'` (공동순위) | **`method='first'` (고유순위)** |
| pykrx | 미활용 | **PER/PBR/DIV 실시간 우선** |

**2. 가중 TTM (fnguide_crawler.py)**

```python
# 손익계산서/현금흐름표: 최신 분기 가중치 높음
# weights: 1.6(40%), 1.2(30%), 0.8(20%), 0.4(10%) → 합 4.0 (기존 TTM 스케일 유지)
weight_map = {최신: 1.6, 2번째: 1.2, 3번째: 0.8, 4번째: 0.4}
```
→ 브이티 같은 최근 실적 악화 종목이 순위에서 자연스럽게 하락

**3. 뉴스 필터링 + TOP 20 + SECTOR_DB 확장**

- `is_relevant()`: 채용공고, 다종목나열(·×3), 종목명 미포함 뉴스 제외
- TOP 10 → TOP 20 상세 표시, 3800자 초과시 메시지 분할
- SECTOR_DB 40+ 종목 확장 (기타→구체적 업종명)

---

## 핵심 변경사항 (v7.1 코드 정리)

### 2026-02-07 Git 캐시 정리 + DART 제거

**Git 캐시 정리**: 2,261개 제거, fs_fnguide 743개 유지

**DART API 완전 제거**: `dart_api.py` 삭제, config에서 DART_API_KEY 제거

---

## 핵심 변경사항 (v7.0 GitHub Actions 완전 자동화)

### 2026-02-06 GitHub Actions 수정

**문제**: GitHub Actions에서 모듈 누락 및 타임존 문제

| 수정 항목 | 문제 | 해결 |
|----------|------|------|
| 타임존 | UTC로 실행되어 날짜 오류 | **KST 타임존 명시적 처리** |
| 워크플로우 | CSV 생성 단계 누락 | **create_current_portfolio.py 단계 추가** |
| 의존성 | tqdm, scipy 누락 | **pip install에 추가** |
| 파일 누락 | error_handler.py 미커밋 | **GitHub에 추가** |
| 리밸런싱 월 | 3/6/9/12월 (잘못됨) | **4/5/8/11월로 수정** |

**KST 타임존 처리**:
```python
from zoneinfo import ZoneInfo
KST = ZoneInfo('Asia/Seoul')

def get_korea_now():
    return datetime.now(KST)

TODAY = get_korea_now().strftime('%Y%m%d')
BASE_DATE = get_previous_trading_date(TODAY)
```

**GitHub Actions 워크플로우** (telegram_daily.yml):
```yaml
- name: Install dependencies
  run: |
    pip install pykrx pandas numpy requests beautifulsoup4 lxml pyarrow tqdm scipy html5lib google-genai

- name: Generate portfolio (create CSV)
  run: python create_current_portfolio.py

- name: Send Telegram message
  run: python send_telegram_auto.py
```

**데이터 소스**:
- 재무제표: FnGuide 캐시 (Q3 2025 고정)
- 시가총액: pykrx 실시간
- OHLCV: pykrx 실시간

---

## 핵심 변경사항 (v6.5 OHLCV 캐시 로직 개선)

### 2026-02-05 버그 수정

**수정된 파일**: `create_current_portfolio.py`

| 수정 항목 | Before | After |
|----------|--------|-------|
| OHLCV 메서드 | `get_ohlcv_parallel` (없는 메서드) | `get_all_ohlcv` |
| 캐시 검증 | 캐시 있으면 무조건 사용 | **BASE_DATE 데이터 존재 확인** |

**OHLCV 캐시 로직 개선**:
```python
# Before: 캐시 있으면 그냥 사용 (BASE_DATE 데이터 없어도)
if ohlcv_cache_files:
    price_df = pd.read_parquet(ohlcv_cache_file)

# After: BASE_DATE 데이터가 캐시에 있는지 확인
if ohlcv_cache_files:
    price_df = pd.read_parquet(ohlcv_cache_file)
    base_date_dt = pd.Timestamp(datetime.strptime(BASE_DATE, '%Y%m%d'))
    if base_date_dt in price_df.index:
        # 캐시 사용
    else:
        # 새로 수집
```

**효과**:
- 매일 실행 시 BASE_DATE 데이터가 캐시에 없으면 자동으로 새로 수집
- 일관된 결과 보장 (같은 BASE_DATE면 같은 결과)
- GitHub Actions와 로컬 실행 결과 동일

### GitHub Actions 실행 흐름 (v7.0+)

```
1. checkout → 최신 코드 pull
2. create_current_portfolio.py → portfolio_YYYY_MM.csv 생성
3. send_telegram_auto.py → CSV 읽어서 텔레그램 전송
```

**참고**: v7.0부터 GitHub Actions에서 매번 CSV를 새로 생성하므로, CSV 커밋이 불필요.

---

## 핵심 변경사항 (v3.2 진입점수 개선)

### 2026-02-05 텔레그램 메시지 완전 자동화 + 진입점수 개선

**목표**: "좋은 사과를 싸게 사자" - 할인된 종목 우선

| 변경 항목 | Before | After |
|----------|--------|-------|
| 날짜 | 하드코딩 | **자동 감지 (전일 거래일 기준)** |
| 기술지표 | 수동 입력 | **pykrx 실시간 계산** |
| 선정이유 | 수동 작성 | **데이터 기반 자동 생성** |
| 리스크 | 수동 작성 | **지표 기반 자동 생성** |
| 신고가 돌파 | **보너스 +35점** | **중립 (감점 안 함)** |

**신규 모듈**:
- `send_telegram_auto.py` - 완전 자동화 텔레그램 전송

**날짜 로직**:
```
TODAY = 오늘 날짜 (인사용)
BASE_DATE = 전일 거래일 (분석 기준)
→ 장 시작 전 전일 종가 분석하여 당일 매매 전략 수립
```

**뉴스 자동화** (Google News RSS):
```
크롤링 → 필터링 → 정제 → 표시

필터링 규칙 (시세 뉴스 제외):
- "+X% 상승/하락", "VI 발동"
- "상승폭 확대/축소", "하락폭 확대/축소"
- "주가 X월 X일", "X% 상승 마감"
- "주가.*장중", "장중.*주가"

정제 규칙:
- 종목명 + 조사 제거 (도/는/가/이/을/를/의/에)
- 언론사명, [태그] 제거
- 빈 따옴표(''), 연속 특수문자(··) 정리
- 헤드라인 35자 제한

표시 형식:
📰 주요뉴스: 마스크팩 인기에 1년 새 15배 뛴
📰 주요뉴스: ⚠️삼성전자 HBM4 수율 격차 1.5배… (부정적)

자동화 한계:
- 규칙 기반 필터링 (80~90% 정확도)
- 새로운 패턴의 시세 뉴스는 필터 못 함
- 며칠 사용 후 평가 예정
```

**2단계 전략 시스템**:
```
[1단계] 밸류 - 뭘 살까?
• 유니버스: 거래대금 30억↑ (20일 평균)
• 전략A 마법공식 30개 ∩ 전략B 멀티팩터 30개
• 공통종목 선정 (동적으로 변동)

[2단계] 가격 - 언제 살까?
• 진입점수로 정렬 (RSI↓ 52주저점↓ 거래량↑)
```

**진입점수 계산 (100점 만점)** - "싸게 사자" 철학:
```
RSI (40점): 낮을수록 좋음
  - ≤30: 40점 (과매도 - 최고 기회)
  - 31-50: 30점 (양호)
  - 51-70: 20점 (중립)
  - >70 + 신고가돌파: 20점 (감점 안 함)
  - >70 일반: 10점 (과매수 위험)

52주위치 (30점): 할인 클수록 좋음
  - ≤-20%: 30점 (큰 할인)
  - -10~-20%: 25점
  - -5~-10%: 20점
  - 신고가돌파: 15점 (감점 안 함, 보너스도 없음)
  - 기타: 15점

거래량 (20점): 스파이크 확인
  - ≥1.5x: 20점
  - 일반: 10점

기본 (10점): 통과 종목 기본 점수
```

---

## 핵심 변경사항 (v3.0 리팩토링)

### 2026-02-03 대규모 리팩토링

**목표**: 런타임 50분 → 5분 단축

| 변경 항목 | Before | After |
|----------|--------|-------|
| 재무제표 소스 | FnGuide 크롤링 | **FnGuide 캐시** |
| 처리 방식 | 순차 처리 | **ThreadPool 병렬** |
| 에러 처리 | print + 무시 | **Skip & Log 패턴** |
| 거래대금 필터 | 10억원 (당일) | **30억원 (20일 평균)** |
| 총 소요시간 | ~50분 | **~35초 (캐시)** |

**신규 모듈**:
- `error_handler.py` - Skip & Log 에러 처리

**수정 모듈**:
- `fnguide_crawler.py` - 재무제표 캐시 + 가중TTM + 컨센서스
- `data_collector.py` - ThreadPool 병렬 처리 추가
- `create_current_portfolio.py` - 동기 main() 구조

---

## 1. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────────────────┐
│                         데이터 수집 레이어                            │
├─────────────────────────────────────────────────────────────────────┤
│  pykrx API                        │  FnGuide                          │
│  - 시가총액 (병렬)                 │  - 재무제표 (캐시, 가중TTM)       │
│  - OHLCV (병렬)                   │                                   │
│  - PER/PBR/DIV (실시간)           │                                   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         전략 레이어                                   │
├─────────────────────────────────────────────────────────────────────┤
│  Strategy A (마법공식) → 사전 필터 200종목 (순위 미반영)               │
│  - 이익수익률 (EBIT/EV) + 투하자본수익률 (ROC)                       │
│                                                                      │
│  Strategy B (멀티팩터) → 200종목 전체 스코어링 → 순위 100%            │
│  - Value 50% (PER/PBR 실시간, PCR, PSR, DIV 실시간)                  │
│  - Quality 30% (ROE, GPA, CFO, EPS개선도)                             │
│  - Momentum 20% (12M-1M)                                            │
│                                                                      │
│  최종순위 = 멀티팩터 100% → TOP 30 (A는 사전필터만)                    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         출력 레이어                                   │
├─────────────────────────────────────────────────────────────────────┤
│  텔레그램 (1~2개 메시지, TOP20)  │  AI 브리핑 (Gemini, 채널+개인봇)       │
│  퀀트 TOP 5 추천 (별도 메시지)  │  통합 CSV 저장                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 핵심 모듈 상세

### 2.1 error_handler.py (~315줄)

Skip & Log 패턴 에러 처리

#### 에러 카테고리

```python
class ErrorCategory(Enum):
    NETWORK = "network"           # 네트워크/연결 오류
    API_RATE_LIMIT = "rate_limit" # API 호출 제한
    DATA_NOT_FOUND = "not_found"  # 데이터 없음
    PARSE_ERROR = "parse"         # 파싱 실패
    VALIDATION = "validation"     # 데이터 검증 실패
    TIMEOUT = "timeout"           # 타임아웃
    UNKNOWN = "unknown"           # 기타
```

#### ErrorTracker 클래스

```python
class ErrorTracker:
    def log_error(ticker, category, message, exception=None):
        """에러 기록 + 실패 종목 추적"""

    def log_warning(ticker, message):
        """경고 기록 (복구 가능)"""

    def mark_success(ticker):
        """성공 시 실패 목록에서 제거"""

    def get_failed_tickers() -> List[str]:
        """실패 종목 목록"""

    def get_summary() -> Dict:
        """에러 통계 요약"""

    def save_error_log(path=None) -> Path:
        """JSON 로그 저장"""
```

#### 사용 예시

```python
tracker = ErrorTracker(log_dir=Path("logs"), name="portfolio")

for ticker in tickers:
    try:
        data = get_financial_statement(ticker)
        tracker.mark_success(ticker)
    except Exception as e:
        tracker.log_error(ticker, ErrorCategory.NETWORK, "수집 실패", e)
        continue  # Skip & Log

tracker.print_summary()
tracker.save_error_log()
```

---

### 2.2 fnguide_crawler.py (~490줄)

FnGuide 재무제표 캐시 + 가중TTM + 컨센서스

#### 주요 함수

```python
def get_financial_statement(ticker, use_cache=True):
    """재무제표 캐시 로드 (parquet)"""

def get_all_financial_statements(tickers, use_cache=True):
    """전체 종목 재무제표 캐시 일괄 로드"""

def extract_magic_formula_data(fs_dict, base_date=None, use_ttm=True):
    """재무제표에서 마법공식/멀티팩터 지표 추출 (가중TTM 적용)"""

def get_consensus_data(ticker):
    """Forward EPS/PER 컨센서스 수집 (FnGuide)"""

def get_consensus_batch(tickers, delay=1.0):
    """배치 컨센서스 수집 (동기)"""
```

---

### 2.3 data_collector.py (~340줄)

pykrx API 래퍼 + 병렬 처리

#### 주요 메서드 (DataCollector 클래스)

```python
def get_ticker_list(self, date, market='ALL'):
    """종목코드 목록 조회"""

def get_market_cap(self, date, market='ALL'):
    """시가총액 조회 (KOSPI/KOSDAQ)"""

def get_all_ohlcv(self, tickers, start_date=None, end_date=None):
    """OHLCV 병렬 수집 (ThreadPoolExecutor)"""

def get_market_fundamental_batch(self, date, market='ALL'):
    """pykrx PER/PBR/DIV 일괄 조회 (캐시)"""

def get_krx_sector(self, date):
    """KRX 업종 정보 조회"""

def get_index_ohlcv(self, start_date=None, end_date=None, ticker='1001'):
    """지수 OHLCV 조회"""
```

---

### 2.4 create_current_portfolio.py (~400줄)

포트폴리오 생성 메인 스크립트 (동기)

#### 핵심 함수

```python
def main():
    """메인 실행 함수 (동기)"""
    # 1. 시가총액 수집 (pykrx)
    # 2. 유니버스 필터링 (시총/거래대금/금융업)
    # 3. 재무제표 수집 (FnGuide 캐시, 가중TTM)
    # 4. pykrx 실시간 PER/PBR/DIV
    # 5. OHLCV 수집 (ThreadPool 병렬)
    # 6. 전략 A 사전 필터 → 200종목 (순위 미반영)
    # 7. 전략 B 스코어링 → 200종목 전체
    # 8. 멀티팩터 순위 100% → TOP 30
    # 9. 결과 저장 (CSV + 리포트)

def run_strategy_a_prefilter(magic_df, universe_df, n=150):
    """마법공식 사전 필터"""

def run_strategy_b_scoring(magic_df, price_df, universe_df, fund_df, prefiltered, n=30):
    """멀티팩터 스코어링 (pykrx live PER/PBR/DIV 우선)"""
```

---

### 2.5 gemini_analysis.py (~330줄)

Gemini 2.5 Flash AI 브리핑 — v3 정량 리스크 스캐너

#### 주요 함수

```python
def get_gemini_api_key():
    """API 키 로드 (환경변수 → config.py 순)"""

def compute_risk_flags(stock):
    """종목별 6가지 위험 플래그 계산 (코드 팩트 기반)"""
    # 🔺 과매수(RSI≥75), 📉 52주급락(≤-35%), ⚠️ 전일급락(≤-5%)
    # 🔺 전일급등(≥+8%), 💰 고평가(PER>40), 📊 거래량폭발(≥3배)

def build_prompt(stock_list):
    """v3 프롬프트 — 종목별 인라인 플래그 + 위험 신호 설명"""
    # [종목별 데이터 & 위험 신호] + [위험 신호 설명] + [출력 형식]

def convert_markdown_to_html(text):
    """Gemini 마크다운 → 텔레그램 HTML (**→<b>, ⚠️ 섹션 regex 구분선)"""

def extract_text(resp):
    """response.text None일 때 parts에서 직접 추출"""

def run_ai_analysis(portfolio_message, stock_list):
    """Gemini API 호출 → HTML 브리핑 반환 (✅ 클린 리스트 코드 생성)"""
    # 빈 응답 방어: finish_reason 로그 + 1회 재시도
    # temperature=0.3 (0.2=빈응답, 0.5=할루시네이션)
```

#### AI 브리핑 출력 구조
- 📰 이번 주 시장: Google Search 1회 (시장 전반 이벤트)
- ⚠️ 주의 종목: 코드 감지 신호 해석 (없으면 생략)
- 📊 포트폴리오 특징: 섹터 편중, 밸류에이션, 모멘텀 패턴

#### 연동 흐름
```
send_telegram_auto.py → run_ai_analysis(None, stock_list)
  → build_prompt(stock_list)  # 코드가 데이터+주의신호 구성
  → genai.Client → Gemini 2.5 Flash (temperature=0.3)
  → Google Search Grounding (시장 동향 1회만)
  → 마크다운→텍스트 변환 → 채널+개인봇 전송
```

---

## 3. 데이터 흐름

### 포트폴리오 생성 (create_current_portfolio.py)

```
1. pykrx에서 시가총액 조회
   └─ KOSPI + KOSDAQ = ~2,773개

2. 유니버스 필터링
   ├─ 시가총액 >= 3000억원
   ├─ 거래대금 >= 50억원 (20일 평균)
   └─ 금융/지주 제외 → ~450개

3. 재무제표 수집
   └─ FnGuide 캐시 로드 (parquet)

3.5. pykrx 실시간 펀더멘털 (PER/PBR/DIV)
   └─ get_market_fundamental_batch(BASE_DATE)

4. 가중TTM 계산
   ├─ Flow: 최근 4분기 가중 합산 (40/30/20/10%)
   └─ Stock: 최근 분기 값

5. 전략 A 사전 필터 → 150종목
   └─ 이익수익률 + ROC 순위 합산

3.6. PER/PBR 상한 필터 (PER>60, PBR>10 제외)
   └─ 고평가 잡주 제거 → ~290개

5.5. FnGuide 컨센서스 수집 (Forward PER) → 150종목
   └─ get_consensus_batch() → forward_per, EPS개선도

6. 전략 B 스코어링 → 150종목 전체
   └─ Value*0.5 + Quality*0.3 + Momentum*0.2
   └─ Quality: ROE + GPA + CFO + EPS개선도 (Forward PER 기반)
   └─ PER/PBR/DIV: pykrx 실시간 우선

7. 통합순위 → TOP 30
   └─ 멀티팩터 100% (마법공식은 사전필터만)

8. 결과 저장
   └─ output/portfolio_YYYY_MM.csv (통합)
```

---

## 4. 파일 구조

```
quant_py-main/
├── 핵심 모듈
│   ├── error_handler.py          # Skip & Log 에러 처리
│   ├── fnguide_crawler.py        # FnGuide 재무제표 캐시 + 가중TTM
│   ├── data_collector.py         # pykrx API + 병렬 처리 + 펀더멘털 배치
│   ├── strategy_a_magic.py       # 전략 A: 마법공식 (사전 필터)
│   ├── strategy_b_multifactor.py # 전략 B: 멀티팩터 (pykrx live 우선)
│   └── gemini_analysis.py         # Gemini AI 브리핑 ("검색은 코드가, 분석은 AI가")
│
├── 실행 스크립트
│   ├── create_current_portfolio.py  # 포트폴리오 생성 (A→필터, B→스코어, 통합순위)
│   ├── send_telegram_auto.py        # 텔레그램 자동 전송 (TOP20, AI 브리핑, TOP5 추천)
│   ├── full_backtest.py             # 전체 백테스팅
│   └── generate_report_pdf.py       # PDF 리포트 생성
│
├── 설정
│   ├── config.py                    # API키/텔레그램 (gitignore)
│   └── config_template.py           # 설정 템플릿
│
├── 출력
│   ├── output/                      # portfolio_YYYY_MM.csv (통합)
│   └── backtest_results/            # 백테스트 결과
│
├── 캐시
│   └── data_cache/
│       ├── fs_fnguide_{ticker}.parquet      # 재무제표 (git 추적)
│       ├── fundamental_batch_*.parquet      # pykrx 펀더멘털 (gitignore)
│       ├── all_ohlcv_{start}_{end}.parquet  # OHLCV (gitignore)
│       └── market_cap_ALL_{date}.parquet    # 시가총액 (gitignore)
│
└── 문서
    ├── README.md
    └── SESSION_HANDOFF.md (이 파일)
```

---

## 5. 알려진 제한사항

### 데이터 관련
1. **FnGuide 컨센서스**: 대형주 위주 커버리지 (~60%)
3. **선호주/우선주**: 일부 재무제표 누락 가능

### 전략 관련
1. **섹터 분류 없음**: 업종 중립화 미적용
2. **거래비용**: 0.3% 고정 (슬리피지 미반영)

### 백테스팅 관련
1. **생존 편향**: 상장폐지 종목 미포함
2. **Look-ahead bias**: 재무제표 공시 시차 반영 (45일/90일)
3. **배당 미반영**: 배당 재투자 미구현

---

## 6. 작업 로그

| 날짜 | 주요 작업 | 파일 |
|------|-----------|------|
| 2026-01-30 | 포트폴리오 생성 시스템 구현 | create_current_portfolio.py |
| 2026-01-31 | 일별 모니터링 시스템 구현 | daily_monitor.py |
| 2026-02-01 | 텔레그램 메시지 3분할 | daily_monitor.py |
| 2026-02-02 | 모멘텀 팩터 구현 | strategy_b_multifactor.py |
| 2026-02-03 | v6.4 리팩토링 (Quality+Price 2축) | daily_monitor.py |
| **2026-02-03** | **Skip & Log 에러 처리 도입** | **error_handler.py (NEW)** |
| **2026-02-03** | **Skip & Log 에러 처리** | **error_handler.py (NEW)** |
| **2026-02-03** | **병렬 처리 추가** | **data_collector.py** |
| **2026-02-03** | **main() 구조 전환 (동기)** | **create_current_portfolio.py** |
| **2026-02-03** | **거래대금 필터 30억으로 조정** | **config.py** |
| **2026-02-03** | **문서 전면 업데이트** | **README.md** |
| **2026-02-04** | **20일 평균 거래대금 필터 적용** | **create_current_portfolio.py** |
| **2026-02-05** | **텔레그램 완전 자동화 (send_telegram_auto.py)** | **send_telegram_auto.py (NEW)** |
| **2026-02-05** | **분석 기준일 전일 거래일로 변경** | **send_telegram_auto.py** |
| **2026-02-05** | **진입점수 개선: 신고가 보너스 제거 (싸게 사자 철학)** | **send_telegram_auto.py** |
| **2026-02-05** | **핵심추천 섹션 제거 (순위만 표시)** | **send_telegram_auto.py** |
| **2026-02-05** | **뉴스 자동 크롤링 및 센티먼트 분석 추가** | **send_telegram_auto.py** |
| **2026-02-05** | **뉴스 헤드라인 요약 개선 (시세뉴스 필터링)** | **send_telegram_auto.py** |
| **2026-02-05** | **GitHub Actions 자동화 (매일 06:00 KST)** | **.github/workflows/telegram_daily.yml (NEW)** |
| **2026-02-05** | **텔레그램 공개채널 연동 (kr_dailyquant)** | **config.py, send_telegram_auto.py** |
| **2026-02-05** | **채널/봇 이중 전송 로직 구현** | **send_telegram_auto.py** |
| **2026-02-05** | **OHLCV 캐시 검증 로직 추가 (BASE_DATE 확인)** | **create_current_portfolio.py** |
| **2026-02-05** | **CSV 파일 커밋 필수 문서화** | **SESSION_HANDOFF.md** |
| **2026-02-06** | **KST 타임존 명시적 처리 추가** | **create_current_portfolio.py, send_telegram_auto.py** |
| **2026-02-06** | **GitHub Actions에 포트폴리오 생성 단계 추가** | **.github/workflows/telegram_daily.yml** |
| **2026-02-06** | **GitHub Actions 의존성 추가 (tqdm, scipy)** | **.github/workflows/telegram_daily.yml** |
| **2026-02-06** | **error_handler.py 누락 파일 커밋** | **error_handler.py** |
| **2026-02-06** | **리밸런싱 권장 월 수정 (4/5/8/11월)** | **send_telegram_auto.py** |
| **2026-02-07** | **Git 캐시 정리 (2,261개 제거, fs_fnguide 743개 유지)** | **.gitignore** |
| **2026-02-07** | **DART API 완전 제거 (dart_api.py 삭제)** | **dart_api.py, config.py, README.md** |
| **2026-02-07** | **데이터 최신성 문제 분석 (Strategy A 75%, B 85% 정적)** | **분석 결과 문서화** |
| **2026-02-07** | **v3.1: A→필터(150), B→스코어링, A30%+B70% 통합순위** | **create_current_portfolio.py** |
| **2026-02-07** | **pykrx 실시간 PER/PBR/DIV 우선 사용** | **strategy_b_multifactor.py, data_collector.py** |
| **2026-02-07** | **가중TTM 적용 (40/30/20/10%)** | **fnguide_crawler.py** |
| **2026-02-07** | **TOP20 상세 + 뉴스 필터링 + SECTOR_DB 확장** | **send_telegram_auto.py** |
| **2026-02-07** | **공동순위 제거 (method='first')** | **strategy_a/b, create_current_portfolio.py** |
| **2026-02-07** | **msg2(전체30간략) 삭제 → 1~2개 메시지만** | **send_telegram_auto.py** |
| **2026-02-08** | **EBIT 수정: EBT→영업이익 사용** | **strategy_a_magic.py** |
| **2026-02-08** | **IC 수정: 비유동자산만 (이미 순액)** | **strategy_a_magic.py** |
| **2026-02-08** | **가중TTM 정규화: <4분기시 weights scale** | **fnguide_crawler.py** |
| **2026-02-08** | **Z-Score: Winsorizing(1%/99%), std=0 가드** | **strategy_b_multifactor.py** |
| **2026-02-08** | **async/await 완전 제거 (동기화)** | **create_current_portfolio.py** |
| **2026-02-08** | **모듈 구조화: main() 함수화** | **send_telegram_auto.py** |
| **2026-02-08** | **bare except → except Exception: 통일** | **전체 파일** |
| **2026-02-08** | **불필요 파일 삭제 (utils.py, backtest_main.py 등 7개)** | **프로젝트 정리** |
| **2026-02-08** | **dead code 제거 (async decorator, prepare_data 함수)** | **error_handler.py, strategy_a_magic.py** |
| **2026-02-08** | **문서 현행화 (README.md, SESSION_HANDOFF.md)** | **MD 파일** |
| **2026-02-08** | **Gemini AI 리스크 스캐너 구현 (Google Search Grounding)** | **gemini_analysis.py (NEW)** |
| **2026-02-08** | **send_telegram_auto에 AI 분석 통합 (포트폴리오→Gemini→전송)** | **send_telegram_auto.py** |
| **2026-02-08** | **GitHub Actions에 Gemini 연동 (secret + google-genai)** | **telegram_daily.yml, config_template.py** |
| **2026-02-08** | **종목별 뉴스 크롤링 제거 (RSS 30회 → 0, 부분매칭 문제 해결)** | **send_telegram_auto.py** |
| **2026-02-08** | **AI 리스크 스캐너 → AI 브리핑 전환 ("검색은 코드가, 분석은 AI가")** | **gemini_analysis.py** |
| **2026-02-08** | **AI 브리핑 개인봇에만 전송 (채널 제외)** | **send_telegram_auto.py** |
| **2026-02-09** | **v3.2: 유니버스 강화 (시총3000억, 거래50억, PER≤60, PBR≤10)** | **create_current_portfolio.py** |
| **2026-02-09** | **멀티팩터 비중 조정 (Value50/Quality30/Momentum20)** | **strategy_b_multifactor.py** |
| **2026-02-09** | **AI 브리핑 채널+개인봇 전송 복원** | **send_telegram_auto.py** |
| **2026-02-09** | **SECTOR_DB 19종목 추가 (기타→구체적 업종명)** | **send_telegram_auto.py** |
| **2026-02-09** | **AI 브리핑 v3: 6가지 정량 리스크 플래그 + Telegram HTML** | **gemini_analysis.py** |
| **2026-02-09** | **AI 브리핑 parse_mode='HTML' + [SEP] 분리선** | **send_telegram_auto.py** |
| **2026-02-09** | **TOP20 종목간 빈 줄 제거 (여백 축소)** | **send_telegram_auto.py** |
| **2026-02-09** | **퀀트 TOP 5 자동 추천 (위험 플래그 제외 + 섹터 분산)** | **send_telegram_auto.py** |
| **2026-02-09** | **AI 브리핑 구분선 안정화: Gemini [SEP] 의존 제거 → regex 코드 후처리** | **gemini_analysis.py** |
| **2026-02-09** | **Forward PER 실적 개선 시그널: FnGuide 컨센서스 수집 파이프라인 연결** | **create_current_portfolio.py** |
| **2026-02-09** | **EPS개선도 팩터 추가: Quality에 (Trailing-Forward)/Trailing*100** | **strategy_b_multifactor.py** |
| **2026-02-09** | **텔레그램 Forward PER 표시: "PER 29.2→5.3" 형식** | **send_telegram_auto.py** |
| **2026-02-10** | **거래대금 차등 필터: 대형50억/중소형20억 (유니버스 454→617)** | **create_current_portfolio.py** |
| **2026-02-10** | **전략 A 순위 반영 제거 → 사전필터만 (200개)** | **create_current_portfolio.py** |
| **2026-02-10** | **최종순위: 멀티팩터 100% (A30%+B70% 통합 폐지)** | **create_current_portfolio.py** |
| **2026-02-10** | **TOP 5 → TOP 10 추천 (섹터 분산 + 위험 플래그 제거)** | **send_telegram_auto.py** |

---

**문서 버전**: 12.0
**최종 업데이트**: 2026-02-10
