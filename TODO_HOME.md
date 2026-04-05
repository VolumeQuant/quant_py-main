# 집PC → 회사PC 인수인계 (2026-04-06)

## 현재 상태

### v75 확정 전략 적용 완료
- 백테스트: 100% 전종목(시총1000억+) 1,287일 완료 — Cal 5.95, CAGR 155%, MDD 26%
- G서브팩터 최적화: 공격(영업이익변화60%+이익률변화40%), 방어(매출성장60%+이익률변화40%)
- 국면전환: B126_40_3d (시총1000억+ MA120 위 비율 ≥40%, 3일 확인)
- ranking_boost/ranking_core 분리 → **ranking 단일파일로 통합 완료**

### CP → FG subprocess 전환 (완료, 검증됨)
- `create_current_portfolio.py`의 `run_strategy_b_scoring()`을 전면 수정
- 기존: `MultiFactorStrategy` 직접 호출 (CP 자체 로직)
- 변경: `fast_generate_rankings_v2.py`를 subprocess로 호출 → JSON 결과 파싱
- **목적**: CP와 FG(백테스트)의 결과 100% 동일 보장
- **검증 결과 (2026-04-06)**:
  - CP 259종목 vs BT_v75 259종목 — 종목 수 동일
  - **모든 종목 score 100% 일치** (차이 0.00000000)
  - Top 10: 10/10 완벽 일치
  - 11~20위 순서 차이는 가중순위(T0×0.5+T1×0.3+T2×0.2) 적용 때문 (정상)
- Forward PER 수집 단계 완전 제거 (불필요한 FnGuide 크롤링 500종목 절약)
- cp949 인코딩 에러 수정 (subprocess bytes 모드)

---

## 회사PC에서 할 일

### 1. 텔레그램 메시지 동작 확인
- `send_telegram_auto.py`가 통합 ranking 파일 읽는지 확인
- 국면 표시(공격/방어) 정상 출력 확인
- 내일(04/07) 장 종료 후 run_daily.py 실행 → 텔레그램 메시지 수신 확인

### 2. 스케줄러 확인
- 기존 스케줄러(QuanT_DailyPipeline)가 v75 코드 정상 실행하는지 확인

---

## 커밋된 파일 구조 및 용도

### 소스 코드 (수정)
| 파일 | 변경 내용 |
|------|-----------|
| `create_current_portfolio.py` | run_strategy_b_scoring()를 FG subprocess 호출로 전환. MultiFactorStrategy import 제거 |
| `backtest/fast_generate_rankings_v2.py` | check_data_mismatch(), merge_fs_supplement()를 모듈 레벨로 추출 (기존 로컬 함수 중복 제거) |

### 백테스트 연구 스크립트 (신규)
| 파일 | 용도 |
|------|------|
| `backtest/regime_search_v75.py` | v75 국면전환 그리드서치 (9규칙 × 공격풀 × 방어풀) |
| `backtest/regime_top3_detail.py` | Top3 국면 조합 상세 분석 (임계값±5, 확인일수±1) |

### 백테스트 결과 CSV (신규)
| 파일 | 용도 |
|------|------|
| `backtest_results/g_factor_borda.csv` | G 서브팩터 Borda 투표 결과 |
| `backtest_results/g_factor_optimization.csv` | G 서브팩터 6C2×21비율 최적화 |
| `backtest_results/phase2a_screening.csv` | Phase 2a 스크리닝 (공격/방어 각각) |
| `backtest_results/phase2a_공격.csv` / `phase2a_방어.csv` | 공격/방어 모드별 팩터 가중치 탐색 |
| `backtest_results/phase2b_rules.csv` | Phase 2b 진입/퇴출 규칙 탐색 |
| `backtest_results/phase2b_공격.csv` / `phase2b_방어.csv` | 공격/방어 모드별 규칙 최적화 |
| `backtest_results/phase2c_walkforward.csv` | Walk-Forward 검증 3기간 |
| `backtest_results/phase2e_stability.csv` | 안정성 필터 (이웃 34개 중 Cal≥3.0) |
| `backtest_results/v75_final_singles.csv` | v75 단일 전략 성과 |
| `backtest_results/v75_regime_*.csv` | 국면전환 조합 탐색 결과 |

### 백테스트 랭킹 데이터 (신규, 대량)
| 디렉토리 | 파일 수 | 용도 |
|----------|---------|------|
| `backtest/bt_v75/` | 1,287 | v75 확정 전략 100% 전종목 BT 랭킹 (2021-01~2026-04) |
| `backtest/bt_v75_1665/` | 1,287 | v75 1665종목 기준 BT (85% 버전) |
| `backtest/bt_v75_2sub/` | 1,287 | v75 2-서브팩터 변형 BT |

### 데이터 캐시 (신규/수정)
| 파일 | 용도 |
|------|------|
| `data_cache/all_ohlcv_20190603_20260403.parquet` | 전종목 OHLCV (2019-06~2026-04, 주력) |
| `data_cache/all_ohlcv_20190603_20260403_full.parquet` | 전종목 OHLCV full 버전 |
| `data_cache/all_ohlcv_20241223_20260403.parquet` | 최근 OHLCV (프로덕션용) |
| `data_cache/bench_proxy.parquet` | 벤치마크 프록시 |
| `data_cache/regime_daily.parquet` | 일별 국면 데이터 (MA120 비율 등) |
| `data_cache/vix_daily.parquet` | VIX 일별 데이터 |
| `data_cache/kospi_*.parquet` / `kosdaq_*.parquet` | 코스피/코스닥 인덱스 OHLCV |
| `data_cache/hy_spread.parquet` | 하이일드 스프레드 |
| `data_cache/fs_dart_*.parquet` | 개별 종목 DART 재무제표 (신규 수집분) |
| `data_cache/fundamental_batch_ALL_20260403.parquet` | pykrx PER/PBR/ROE 배치 |
| `data_cache/market_cap_ALL_*.parquet` | 시가총액 배치 |
| `data_cache/krx_sector_*.parquet` | KRX 섹터 분류 |
| `docs_cache/opendartreader_corp_codes_20260405.pkl` | DART 기업코드 (갱신) |

### 프로덕션 상태 파일 (수정)
| 파일 | 변경 내용 |
|------|-----------|
| `state/ranking_YYYYMMDD.json` | boost/core 분리 → 단일 파일로 통합 (v75 국면전환) |
| `state/regime_state.json` | v75_final 규칙, 현재 boost 모드 |
| `state/ranking_boost_*.json` | 삭제 (단일 파일로 통합됨) |
| `state/ranking_core_*.json` | 삭제 (단일 파일로 통합됨) |

### 기타
| 파일/디렉토리 | 용도 |
|---------------|------|
| `state/fg_test/` | FG 단독 실행 테스트 결과 (비교 기준) |
| `state/bt_2025/` | 2025년 BT 랭킹 (304파일) |
| `state/v75_pre_rebuild_backup/` | v75 이전 ranking 백업 (112파일) |
| `state/web_data_*.json` | 웹 크롤링 데이터 |
| `data_cache/ticker_names_cache.json` | 종목명 캐시 (갱신) |

---

## 삭제된 파일 (정리)
- `data_cache/all_ohlcv_20190603_20260401.parquet` → 20260403으로 교체
- `data_cache/all_ohlcv_20241223_20260401.parquet` → 20260403으로 교체
- `docs_cache/opendartreader_corp_codes_20260326.pkl` → 20260405로 교체
- `state/ranking_boost_*.json` (38일분) → ranking 단일 파일로 통합
- `state/ranking_core_*.json` (38일분) → ranking 단일 파일로 통합
