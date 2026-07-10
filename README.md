# 한국 주식 퀀트 시스템 (KR Momentum-Growth)

KOSPI/KOSDAQ 전종목 대상 **국면전환 멀티팩터** 퀀트 전략 — 매일 16:00 완전 자동 실행.

> 전략 버전: **v80.35** (2026-07-08) | 라이브: 2026-02-23~ | 채널: [@kr_dailyquant](https://t.me/kr_dailyquant)
>
> 📘 **[현재 시스템 상세 설명](docs/SYSTEM_OVERVIEW.md)** · 📜 **[버전 이력](docs/VERSION_HISTORY.md)** · 🗺️ [전략 교체 체크리스트](SYSTEM_MAP.md)

---

## 핵심 아이디어

1. **성장 리더 추종**: 실적(매출·영업현금흐름·매출총이익)이 가속하는 종목을 12개월 모멘텀과 결합해 순위화. 상위 3종목만 보유.
2. **국면 게이트가 1차 방어**: KOSPI MA20/MA80 골든/데드크로스(5일 확인)로 공격/방어 전환. 방어 = 전량 현금. 약세장을 종목 선택이 아니라 시장 이탈로 피한다.
3. **함정은 회계로 거른다**: 일회성 매출(lumpiness), 비현금 이익(accruals), 최근 무상증자/유상증자 착시 같은 구조적 회계 착시만 필터링. 가격·거래량 기반 함정 필터는 창의 피처 20+종 전수 검증에서 전부 기각 — 승자와 휩쏘는 진입 시점에 구별 불가.
4. **점수가 아니라 순위, 하루가 아니라 3일**: 일별 순위(cr)를 3일 가중(wr = 0.4/0.35/0.25)해 노이즈를 죽이고, 3일 연속 상위권(✅ 검증)만 매수 후보.

## 시스템 한눈에

```
전체 상장 (~2,700종목)
  ↓ 시총 1,000억+ / 거래대금 / 우선주·금융·지주 제외 / MA120 추세 필터
  ↓ 데이터 품질 (DART 분기 8개+, PIT) / -1.5σ 극단값 바닥 필터
4팩터 스코어링 (공격 모드: V15 · Q0 · G55 · M30)
  + mom_10 ×0.05 + vol_low ×0.06   (가격 자연 반영)
  + 과열 캡 ×0.2                    (실적 대비 비싸진 쪽만 감점)
  − 함정 페널티                     (lumpiness / accruals / 최근 CA / QoQ)
  ↓
weighted_rank (3일 가중 0.4/0.35/0.25) → ✅ 3일 연속 검증
  ↓
진입 wr≤3 / 이탈 wr>5 / 3슬롯 / SL −15% / 재진입 쿨다운 10거래일
  ↓
텔레그램 [Signal] [Watchlist] + 신규진입 검문소·확신가중 제안 (개인봇)
```

## 현재 매매 룰 요약 (v80.35, 2026-07 기준)

| 항목 | 값 | 근거 요약 |
|---|---|---|
| 국면 | KOSPI MA20>MA80, 5일 확인 | 75조합 재탐색 — 약세장(2022-23) WF 1위 |
| 팩터 (공격) | V 0.15 / Q 0 / G 0.55 / M 0.30 | 12시나리오 재최적화 압도적 1위 |
| G 서브팩터 | rev 0.4 / oca 0.4 / gp 0.2 | 3팩터, PIT (공시일 기준) |
| 진입/이탈/슬롯 | rank≤3 / rank>5 / 3슬롯 | 섹터 브레드스 도입 후 그리드 재최적 |
| 손절 | −15% (테일 보험) | 비용 0으로 최악 단일거래 −35%→−20% 절단 |
| 재진입 쿨다운 | 이탈 후 10거래일, 빈 슬롯 승격 금지 | 되사기 코호트 승률 29%·평균 −2.05% |
| 방어 모드 | 현금 100% | 신규 매수 없음, 보유만 룰대로 청산 |
| 섹터 브레드스 | 참여폭<35% 3일 → 노출 50% 축소 권고 | "느린 약세" 정밀 보호 (표시 제안, 매매신호 불변) |

상세 근거·수치는 [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) 참조.

## 성과 — 정직 버전

- **백테스트 (7.4년, 2019-01~)**: Calmar ~5.2 / MDD −24%. 단 2025-26 대폭등이 CAGR을 크게 인플레시킨 수치로, **실전 기대 중심은 CAGR ~25%, MDD −26% 수준** (거래통계: 승률 53%, 손익비 3.8, 수익의 75%가 상위 5% 거래에 집중 — 승자 몇 개를 놓치면 평범해지는 구조).
- **라이브 (2026-02-23~)**: 실제 발송된 신호를 그대로 따른 팔로워 원장 기준 **+26% vs KOSPI +25%** (2026-07-09 기준, 7월 크래시 포함, MDD −31%). 아직 5개월 — 벤치마크 수준이며 검증 진행 중. 부풀리지 않는다.
- 모든 신규 룰은 **7.4년 풀BT + Walk-Forward 블록 + Leave-One-Winner-Out + 인접 파라미터 CV(노이즈 ±0.10 초과)** 통과 후에만 배포. 단기 검증만으로 배포했다가 당한 실측 사고들이 이 원칙의 근거다 — [버전 이력의 사고 기록](docs/VERSION_HISTORY.md#주요-사고와-교훈) 참조.

## 프로젝트 구조 (핵심 파일)

```
run_daily.py                        # 매일 16:00 파이프라인 진입점
regime_indicator.py                 # 국면 판단 + 전 파라미터 (코드가 진실)
data_refresher.py                   # 시총/재무/OHLCV/섹터 캐시 갱신
backtest/fast_generate_rankings_v2.py  # 스코어링 엔진 (FG)
ranking_manager.py                  # weighted_rank / 진입·퇴출
send_telegram_auto.py               # Signal/Watchlist 메시지 + 수익률 리플레이
breadth_diagnostic.py               # 섹터 브레드스 진단
entry_sentinel.py                   # 신규진입 검문소 (개인봇 리포트)
conviction_display.py               # 확신가중 비중 제안 (표시 전용)
dart_collector.py                   # DART 수집 (finstate + document 폴백)
backtest/turbo_simulator.py         # 백테스트 엔진 (5ms/run)
state/                              # 일별 랭킹·발송 원장 (라이브 기록, git 추적)
docs/                               # 시스템 문서 + 과거 문서 아카이브
```

## 설치 및 실행

- Python 3.10+ (conda 권장), Windows Task Scheduler 기준

```bash
pip install pykrx pandas numpy requests beautifulsoup4 lxml pyarrow scipy google-genai yfinance opendartreader
```

```bash
# 전체 파이프라인 (개인봇 테스트 모드)
TEST_MODE=1 python run_daily.py
```

- API 키/토큰은 `config.py`(git 미추적)에 보관 — `config.example.py` 참조
- 스케줄: 평일 16:00 일일 파이프라인, 일요일 종목명 캐시 갱신

## 문서 안내

| 문서 | 내용 |
|---|---|
| [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) | **현재 시스템 상세** — 팩터, 함정 필터 스택, 매매룰, 파이프라인, 검증 철학 |
| [docs/VERSION_HISTORY.md](docs/VERSION_HISTORY.md) | **버전별 이력** v70→v80.35 + 주요 사고와 교훈 |
| [CHANGELOG.md](CHANGELOG.md) | 변경별 상세 검증 기록 (원본 — 길고 상세함) |
| [SYSTEM_MAP.md](SYSTEM_MAP.md) | 전략 교체 시 맹점 제로 체크리스트 |
| [CLAUDE.md](CLAUDE.md) | AI 협업용 운영 노트 (내부 작업 문서 — 현재 운영 기준의 원본) |
| docs/archive/ | 과거 핸드오버·조사·TODO 문서 아카이브 |

## 디스클레이머

이 저장소는 개인 연구·기록 목적입니다. 어떤 내용도 투자 권유가 아니며, 백테스트 성과는 미래 수익을 보장하지 않습니다. 시스템은 신호만 제공하고, 매매와 사이징은 각자의 판단과 책임입니다.
