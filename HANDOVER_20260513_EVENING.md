# 2026-05-13 저녁 세션 인계 — v80.6 production 정련

> 회사 PC가 내일 아침 pull 받으면 바로 작업 가능하도록 작성됨.

## TL;DR

집 PC에서 v80.6 production 정련 작업 완료. 5/12·5/13 발송 채널+개인봇 모두 OK. 코드/데이터/문서 모두 commit·push 됨. **회사 PC에선 `git pull` + `config.py` Gemini key 1줄만 동기화하면 끝.**

## 1. 사건 발단

5/13 16시 자동 실행 (회사 PC) 종료 후 집 PC가 19시 자동 실행 → ranking 종목수 **288/320 미달** → B 안전망이 데이터 사고로 오인하여 채널 발송 차단 → 5/12 새벽 발송 1회만 채널 도착, 5/13 자동 발송 미발생.

## 2. 진단 결과 (요약)

| 가설 | 실제 |
|---|---|
| OHLCV 액면분할 복원 영향? | **무관**. 가격은 그대로, MA120 평균이 0→NaN 후 자연 변동 |
| FnGuide stale 영향? | **점수 영향 0**. v80.6 G_SUB는 DART 단독으로 계산 |
| 데이터 사고? | **아님**. 시장 자연 약세 (universe 19개 거래대금 / ma120 16개 / score 11개) |
| Gemini AI 누락? | **API 키 leak**으로 자동 비활성화 (5/12 새벽 발송 이전) |
| HY 지수 누락? | **7650일 캐시가 799일로 손상** (5/13 새벽 작업 부산물) |

## 3. 변경 사항 (집 PC, 5/13 저녁)

### 코드 (모두 commit 포함)
- `run_daily.py`
  - 종목수 임계 **320 → 150** (line 708, 732) — 시장 약세 흡수
  - FnGuide subprocess timeout **900 → 10800** (line 468) — 충분한 보호선
- `refresh_fnguide_incremental.py` — 전면 개편
  - DAYS cutoff 3 → **30** (FnGuide 사이트가 DART보다 며칠~수주 늦음)
  - **mtime 비교 추가**: `fs_fnguide.mtime < fs_dart.mtime`인 종목만 (이미 최신 스킵)
  - **ThreadPool=2** + 종목당 30초 timeout (hang 보호)
  - 환경변수: `FNG_INCR_DAYS`, `FNG_TICKER_TIMEOUT`, `FNG_WORKERS`
- `send_telegram_auto.py` — 매매 조건 문구 정련
  - 매수: `상위 N종목 (최대 M종목 보유)`
  - 매도: `X위 밖 / 손절 -10% / 고점대비 -8%`
  - cold start 안내문도 동일 패턴
- `send_notice_once.py` — v80.6 전체 갱신
  - 170일 → **250일**, 슬롯 3/5 → **5/4**, 트레일링 -15% → **-8%**
  - defense 팩터 비중 M40V30 → **M35V35**

### 데이터 (모두 commit 포함)
- `data_cache/hy_spread.parquet`
  - 7666일 복원 (git d7f198504에서 옛 84KB 추출 + 4/17~5/11 신규 병합)
  - 손상본은 `hy_spread.parquet.bak_799d_corrupt`로 보존 (혹시 모를 검증용)
- `data_cache/fs_fnguide_*.parquet`
  - **1550 종목 일괄 보충** (5/13 22시, 23.4분, 100% 성공)
  - 5/13 오전까지 4/16 mtime이 2329개였던 stale 누적 해소
- `data_cache/fs_dart_*.parquet`
  - 5/13 저녁 추가 증분: **107 수집** (5/15 1Q 마감 폭주 시작)
- `state/ranking_20260512.json`, `state/ranking_20260513.json` 등
  - 새 fnguide 데이터로 재생성 — 5/12 boost 302, defense 294 / 5/13 boost 288, defense 281
  - 종목수는 이전과 동일 (예상대로 fnguide stale은 점수 영향 0)

### 문서 (모두 commit 포함)
- `CLAUDE.md` — v80.6 정련 섹션 추가 (이 인계서와 같은 내용 요약)
- `~/.claude/.../memory/` — 신규 3건
  - `project_20260513_evening_v806_polish.md`
  - `feedback_validation_threshold_static_market.md`
  - `feedback_data_cache_git_backup.md`

### config.py (git push 안 됨, 수동 동기화 필요)
- `GEMINI_API_KEY` 갱신됨 — 회사 PC도 동일 키로 교체 필요
- 키 값은 사용자가 직접 전달 (또는 새로 발급 후 두 PC 동기화)

## 4. 발송 완료

| 날짜 | 채널 | 개인봇 | AI 종목 근거 | AI 시황 | HY 지수 |
|---|---|---|---|---|---|
| 5/12 | ✅ 200 | ✅ 200 | ✅ 포함 | ✅ 포함 | ✅ 표시 |
| 5/13 | ✅ 200 | ✅ 200 | ✅ 포함 | ✅ 포함 | ✅ 표시 |

채널에 5/12자 메시지가 두 번 발송된 상태 (어제 새벽 v80 기준 + 오늘 저녁 v80.6 기준). 필요 시 수동 정리.

## 5. 회사 PC 작업 절차

```bash
git pull origin main
# config.py만 수동 동기화 — Gemini API 키 교체
# (사용자가 별도 전달한 키 또는 새로 발급)
# 그 외에는 그대로 사용 가능
```

다음 자동 실행(평일 16시) 시 새 정책 자동 적용:
- 종목수 임계 150 (약세장 정상 흡수)
- FnGuide refresh 30일 cutoff + mtime 비교 + ThreadPool 보호
- 메시지 문구 v80.6 정련

## 6. 위험 신호 (앞으로 주의)

- 종목수 50개 이하로 폭락 시 = 진짜 캐시 손상 의심. 임계 150도 통과 안 됨
- `data_cache/hy_spread.parquet` 크기 갑자기 줄어들면 = 또 손상. git d7f198504에서 복원
- `[Gemini] AI 분석 실패: 403 PERMISSION_DENIED` 로그 = 키 leak. 즉시 재발급
- FnGuide refresh가 timeout=3시간으로 잡혀도 ThreadPool이 progress 찍어서 hang 즉시 보임

## 7. 변경 안 한 것 (이유)

- v80.6 알파 파라미터 (V/Q/G/M, G_REV, entry/exit/slots, SL/TS) — 회사 PC commit `89e580f42` 그대로
- BT 결과 데이터 (bt_optf_*) — 변경 없음
- regime_indicator.py — 변경 없음
- 옵션 F 미적용 상태 그대로 (가짜 알파 폐기)
