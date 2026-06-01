# KR EPS Research — 검증 도구 + 성능 향상 후보

## ⚠️ 중요: KR EPS는 production v80.22와 다른 시스템

| 시스템 | 신호 | 필터 이유 |
|---|---|---|
| **production v80.22** | Multifactor V/Q/G/M (DART) | 금융주는 V/Q/G/M 안 맞음, 계절성/QoQ는 G_score 왜곡 차단 |
| **KR EPS (this)** | NTM EPS revision (forward, yfinance) | NTM이 이미 계절성/QoQ 다 반영 + yfinance 커버리지가 자연 selection |

→ **production 필터를 KR EPS에 카피하면 알파 손해.**

### 자연 selection EDA 입증 (2026-06-01)

```
1430 universe (시총 1천억+) → fy_complete 282종목 (20%)
  10조+ (대형주): 75 (27%)
  3~10조: 83
  1~3조 (중형주): 124
  <1조 (소형주): 0  ← yfinance가 자동 컷
  → fy_complete 100%가 시총 1조+
  
시총 ↔ 분석가수(na) 상관: +0.34
na≥3:  230종목, 시총 중앙 5.2조
na≥5:  195종목, 시총 중앙 6.2조
na≥10: 147종목, 시총 중앙 8.0조
na≥15:  90종목, 시총 중앙 16.2조
```

**결론: 추가 필터 불필요. yfinance + na≥3이 이미 대형주만 자연 selection.**

## 진짜 성능 향상 후보 (60일 누적 후 BT 필요)

### A. fwd_pe_chg 가중치 KR 재최적화
- 현재: US v80.10 (7d 0.30 / 30d 0.10 / 60d 0.10 / 90d 0.50)
- US에서 90일 누적 PE 압축 강조한 가중치. KR도 같은 패턴?
- 60일 누적 → 5x5 grid + 인접 안정성 CV 검증

### B. na 임계 KR-specific 재학습
- 현재: na≥3 (US 디폴트). KR에선 230 → 195(na≥5) → 147(na≥10)
- na 임계 ↑ = 정확한 컨센서스 but universe 좁아짐
- 60일 누적 후 na≥3/5/10 BT 비교

### C. rev_up30 임계 KR 재학습
- 현재: rev_up30 ≥ 3 (US v80.8 WELL 사례 차단)
- KR 분포: rev_up30 5+ 강한 신호 68종목
- 3 vs 5 vs 10 KR BT 비교

### D. KR-specific 신호 추가 (yfinance 외)
- **외국인 보유율** (pykrx 가용) — KR 대형주에 강한 신호
- **FnGuide 컨센서스 (DART rcept_dt 기반 PIT)** — 이미 production에 인프라
- **신용잔고/공매도 잔고** — KR-specific
- 위험: 데이터 수집 인프라 추가 작업 큼 → KR EPS 60일 안정화 후 검토

## 거부된 후보 (production v80.22 카피 = 부적합)

### ❌ KRX 금융 섹터 필터
**production**: 산업지주사 (SK스퀘어/LG 등) NAV 디스카운트가 V/Q/G/M 신호 오염 → 제외 필요
**KR EPS**: NTM EPS revision은 산업지주사도 의미. 필터 = 알파 손해

### ❌ 계절성 패널티 (Q2+Q4 편향)
**production**: G_score = 분기 매출 단순 합. Q2+Q4 일회성 폭증 종목 함정 → 패널티
**KR EPS**: NTM EPS = forward 12개월 컨센서스. 이미 계절성 반영. 패널티 = 알파 손해

### ❌ QoQ 패널티 (base 효과)
**production**: G_score = 직전 분기 base 작으면 YoY +200%여도 실제 모멘텀 X
**KR EPS**: NTM EPS = 미래 컨센서스. base 효과 자동 차단 (분석가가 base 알고 forecast)

## 도구

### `leave_one_out.py` — Dominant winner 제외 robustness 검증
US v83.2 교훈: 71일 단일 표본에서 C2 boost edge가 전부 MU 한 종목 → MU 제외 시 동전던지기 → "변경 평가 시 반드시 dominant winner 제외 robustness 확인" 원칙 강제.

### `multistart_bt.py` — 6시작일 표준화
US v80.6 교훈: 33시작일 평균이 짧은 기간 시작일로 흐려져 잘못된 결론 → 6시작일 (50거래일+ 보장) multistart로 +18%p 알파 일관 확인.

### `data_monitor.py` — 데이터 누락 감지
KR EPS 5/14 PoC 17일 멈춤 사고 재발 방지: Task Scheduler 등록 누락 → 17일 데이터 0건. GHA cron + 이 monitor + 개인봇 알림으로 자동 감지.

## 60일 누적 후 변경 검증 절차

1. `multistart_bt.py` 6시작일 BT
2. `leave_one_out.py` dominant winner 제외 robust 확인
3. 인접 안정성 CV < 0.10 plateau 확인
4. WF 4구간 약세장 사고 패턴 X 확인
5. 모두 통과 → 채택. 하나라도 fail → reject

## 공통 검증 원칙 (US/KR EDA 결과)

- **변경 폭 작게** (롤백 용이)
- **DB backup 필수** (`bak_pre_<change>`)
- **단독 변경** (효과 분리)
- **Cal noise ±0.10** 인지
- **OOS > IS** (cherry-pick 방지)
- **롤백 트리거** 명시 (5거래일 KOSPI 알파 -3%p 또는 MDD -10%)
- **표본 먼저** — 1조 컷 사고 같은 검증 없는 적용 금지
