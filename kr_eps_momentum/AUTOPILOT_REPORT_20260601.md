# KR EPS Momentum 자율주행 보고서 — 2026-06-01

> 사용자가 병원 다녀오는 동안 "kr momentum 시스템 완성해놔" 지시로 진행

## 한 줄 요약
US `eps-momentum-us/daily_runner.py` **5,178줄 통째 KR adapt** 완료, GHA cron 자동화 활성. 첫 manual trigger 결과 확인 단계 (병원에서 돌아오시면 결과 함께 결정 가능).

## ✅ 완료 (자율주행 6/1 진행 12건)

### 인프라
- [x] **GHA workflow permissions** read → write (quant_py-main + eps-momentum-us 둘 다)
- [x] **`.github/workflows/kr_eps_daily.yml`** — minimal version에서 daily_runner.py 호출로 전환
- [x] GHA secrets 활용 (TELEGRAM_BOT_TOKEN/PRIVATE_ID/GEMINI_API_KEY)
- [x] **`yf_eps_workspace/code/run_daily.py` (v1 minimal 200줄) DEPRECATED 마크** — backup으로만 유지

### daily_runner.py 5,178줄 KR adapt 핵심 path
| # | 변경 | 위치 |
|---|---|---|
| 1 | universe NASDAQ/S&P500+400+NQ100 → `universe_kr.fetch_dynamic_tickers` | line 330~344 |
| 2 | `CONFIG_PATH`: `config.json` → `config_kr.json` | line 44 |
| 3 | `SPY` → `KR_INDEX` (^KS11 KOSPI) yfinance 호출 3건 | line 325, 1465, 4036 |
| 4 | `_INDEX_SYMBOLS`: US 4종 → `['^KS11','^KQ11']` | line 350 |
| 5 | `get_last_business_day`: US/Eastern → Asia/Seoul | line 2620 |
| 6 | **yf.download Rate Limit 회피**: 일괄 1415종목 → 50종목 chunk × 1.5s sleep | line 371 |
| 7 | **시장지수 컨텍스트**: US 4종 → KOSPI/KOSDAQ | line 2552 |
| 8 | `info_cache` 변수 미정의 버그 fix (alpha_signals 호출) | line 5128 |

### 데이터/cache
- [x] **`universe_kr.parquet` symbol cache**: 1415 KR 종목 .KS/.KQ 결정 (5/14는 매번 13분 재시도)
- [x] **`ticker_info_cache.json` 한글 종목명 사전 빌드**: production 한글 매핑 활용 (1415 symbol)
- [x] **영문 yfinance .info 한글 cache 덮어쓰기 방어**: 한글 글자 감지 (가~힣)

### 문서
- [x] **`KR_ADAPT_TODO.md`**: 6/1 진행 12건 완료 + 남은 작업 Phase A/B/C 명확화
- [x] **`yf_eps_workspace/README.md`**: v1 (minimal, deprecated) vs v2 (daily_runner, active) 구분

## 🔧 남은 작업 (사용자 확인 후 결정)

### Phase A — 핵심 KR 완성 (~1시간 추가)
- [ ] **^VIX** (line 2267, 2375) — KR엔 대체 없음. 현재 실패 시 default 15.3 사용 중 (동작 OK)
- [ ] **HY Spread** (FRED) — 동일. KR엔 대체 없으니 그대로 (실패 → default)
- [ ] **AI 분석 prompt 한글화** (line 3404~ Gemini API)
- [ ] **`INDUSTRY_MAP`** 한글화 (현재 영문 그대로)

### Phase B — 검증
- [ ] 로컬 full run 성공 (매수 후보 > 0개) — 6/1 첫 시도 시 Rate Limit으로 0개, chunk fix 후 GHA 검증 중
- [ ] **GHA 1회 success + 텔레그램 4종 메시지 정상** (한글)
- [ ] 60일 누적 후 BT 검증 (8월 초)

### Phase C — 정리
- [ ] yf_eps_workspace/code/run_daily.py 폐기 (DEPRECATED 마크 완료, 삭제는 별도)
- [ ] KR 별도 repo 분리 검토 (eps-momentum-us 패턴)

## 📊 첫 로컬 테스트 결과 (10분, exit 0)

```
[2026-06-01 10:23:25] KR universe (시총 1천억+): 1415개
[2026-06-01 10:23:25] 종목 정보 캐시 로드: 1452개  ← 한글 cache 동작 ✓
[2026-06-01 10:24:38] 가격 다운로드 완료              ← 단, Rate Limit 다수
[2026-06-01 10:25:20] MA120 사전 필터: 558개 제외 → 859개
[2026-06-01 10:29:08] 수집 완료: 메인 0, 턴어라운드 0, 에러 857  ← Rate Limit 영향
[2026-06-01 10:33:18] VIX (yfinance fallback): 15.3 → normal       ← 정상 fallback
[2026-06-01 10:33:19~21] 텔레그램 3종 메시지 발송 성공 (Signal/AI Risk/시스템로그)
[2026-06-01 10:33:21] 전체 완료: 597.7초 소요
```

**진단**: yf.download 일괄 호출이 Rate Limit. **이번 commit chunk fix로 GHA에서 재시도 중**.

## 📅 Git Commits (6/1 자율주행 세션)

```
6fd1fb409  docs(yf_eps_workspace): run_daily.py deprecated 마크
aa4567f1a  fix(kr_eps): get_market_context US 4지수 → KR 2지수 (KOSPI/KOSDAQ)
57871cd9b  docs(kr_eps): KR_ADAPT_TODO 6/1 진행 + yf_eps_workspace README v1/v2 구분
70da4d5b4  fix(kr_eps): info_cache 변수 버그 + ^GSPC → KR_INDEX paper trade 누적 비교
db2767f04  feat(kr_eps): daily_runner.py 5,178줄 KR adapt — US 완전 모방
5a47fee8f  data(kr_eps): 5/13 5/14 6/1 누적 데이터 + .gitignore
3559e21c0  feat(kr_eps): GHA cron 자동화 — 5/14 PoC 17일 멈춤 복구
```

origin/main과 동기화됨.

## 🔄 트러블슈팅 진행 (6/1 자율주행)

### GHA 1차 (run 26730674786, 8분, success but empty)
- **로그**: "수집 완료: 메인 0, 턴어라운드 0, 에러 857"
- **원인**: yf.download 일괄 1415종목 호출 → Rate Limit
- **fix**: chunk 50종목 × 1.5s sleep (db2767f04)

### GHA 2차 (run 26730954943, success but 다시 empty)
- **로그**: "KR universe 수집 실패: list index out of range"
- **원인**: universe_kr.py가 UNIVERSE_CACHE 못 찾으면 fallback에서 빈 list[-1] IndexError
- **fix**: 3-candidate path try + IndexError 방어 + 명확한 에러 메시지 (b80087378)

### GHA 3차 (run 26731205605, success but 또 empty)
- **debug 로그**: `shape=(1430, 2) cols=['code', 'mc_krw']` ← **옛 universe parquet!**
- **원인**: 6/1 두 번째 빌드에서 새 universe_kr.parquet (1415, symbol 포함) 만들었는데 git commit 안 함
- **fix**: 강제 commit + push (32aa89864)

### GHA 4차 (run 26731437616, 진행 중)
- 이번엔 새 universe parquet (1415, ['ticker','symbol','market','mc_krw']) 로 GHA가 동작
- 예상: 매수 후보 정상 (>0개), 한글 종목명, 4종 메시지

## 🚀 다음 액션 (사용자 결정)

**GHA 4차 진행 중 결과 보고 결정**:
1. **성공 + 한글 메시지 + 매수 후보 정상** → Phase A 마저 진행 (VIX KR 처리, AI prompt 한글화 등)
2. **여전히 매수 후보 0** → 더 깊은 fix 필요
3. **다른 에러** → 에러별 fix

병원에서 돌아오시면 GHA 결과 함께 보고 결정 가능합니다.
