# KR EPS Momentum — Daily PoC

## ⚠️ 2026-06-01 업데이트 — 두 가지 버전 운영

**v1 (이 폴더, minimal): backup으로 유지, GHA에서는 미사용**
- `code/run_daily.py` 200줄 minimal — 5/14 PoC 시작 시 만들었음
- 5/14~5/31 17일 멈춤 사고 시 복구용으로 사용된 적 있음
- 이후 v2(full 모방)로 GHA 전환

**v2 (`C:/dev/kr_eps_momentum/daily_runner.py`, 5,178줄): US 완전 모방, GHA 활성**
- US `eps-momentum-us/daily_runner.py` 통째 KR adapt
- 4종 정교한 메시지 (Signal/AI Risk/Watchlist/시스템로그)
- SQLite DB 누적 + paper trade portfolio
- GHA cron `.github/workflows/kr_eps_daily.yml` 활성
- 자세히: `C:/dev/kr_eps_momentum/KR_ADAPT_TODO.md`

이 폴더(`yf_eps_workspace/`) 역할:
- `data_cache_yf/`: 일별 누적 데이터 저장소 (v1, v2 둘 다 사용)
- `universe_kr.parquet`: 1415 KR 종목 정적 cache (.KS/.KQ 결정)
- `code/`: v1 minimal version (backup, 폐기 예정)

---

US `eps-momentum-us` 시스템(NTM EPS Revision Momentum)을 KR 종목 풀로 그대로 적용한 paper-trade PoC.

**Production v80.22(quant_py-main)와 무관, 격리 운영.** paper trade만, 자본 X.

## 흐름
```
GHA cron (매일 KST 08:00)
  → run_daily.py
    → 1) yfinance probe (1430종목, KS/KQ)
    → 2) NTM score (US calculate_ntm_score 동일)
    → 3) 개인봇 텔레그램 발송 + parquet 누적
  → git commit & push (자동)
```

## 운영 상태
- **시작**: 2026-05-14
- **현재**: 6/1 GHA 자동화 등록 (이전 17일 멈춤 = Task Scheduler 등록 누락)
- **누적 목표**: 60 거래일 → 8월 초 → BT 검증 → production 운영 판단

## 파일
| 파일 | 역할 |
|---|---|
| `code/run_daily.py` | 통합 entry (probe + score + telegram). GHA가 호출 |
| `code/eps_momentum_system.py` | US core 점수 함수 (calculate_ntm_score, get_trend_lights) — US 코드 복사 |
| `code/daily_probe.py` | (구) 개별 probe 스크립트. run_daily.py로 통합됨 |
| `code/kr_signal.py` | (구) 개별 signal 스크립트. run_daily.py로 통합됨 |
| `code/daily_message.py` | (구) 개별 message 스크립트. run_daily.py로 통합됨 |
| `code/paper_trade.py` | paper trade DB 관리 |
| `universe_kr.parquet` | 시총 1천억+ 보통주 1430종목 (정적 캐시, 월 1회 갱신 권장) |
| `data_cache_yf/kr_yf_YYYYMMDD.parquet` | 일별 yfinance 결과 누적 |
| `logs/daily/run_YYYYMMDD.log` | 실행 로그 |
| `requirements.txt` | pip 의존성 (yfinance, pandas, numpy, pyarrow, requests) |
| `paper_trade.db` | paper trade SQLite |
| `~~SCHEDULER_GUIDE.md~~` | **(폐기됨)** Task Scheduler 로컬 가이드 → GHA cron으로 대체 |

## 의존성
- `requirements.txt`: yfinance, pandas, numpy, pyarrow, requests
- `universe_kr.parquet`: 시총 1천억+ 보통주 (정적). 월 1회 갱신:
  ```bash
  python -c "
  import pandas as pd, glob
  files = sorted(glob.glob('data_cache/market_cap_ALL_*.parquet'))
  df = pd.read_parquet(files[-1])
  df.columns = ['close','mc','vol','val','shares']
  df = df[(df.mc>=1e11) & (df.index.astype(str).str.endswith('0'))]
  out = df.reset_index().rename(columns={'티커':'ticker'})[['ticker','mc']]
  out.columns = ['code','mc_krw']
  out['code'] = out['code'].astype(str).str.zfill(6)
  out.to_parquet('yf_eps_workspace/universe_kr.parquet', index=False)
  "
  ```

## 환경변수 (GHA secrets)
- `TELEGRAM_BOT_TOKEN`: 봇 토큰 (production v80.22와 동일 봇 재사용)
- `TELEGRAM_PRIVATE_ID`: 개인봇 chat_id (채널 X, paper trade라 비공개)

로컬 실행 시 `config.py`(C:/dev/) 자동 fallback.

## GHA workflow
`.github/workflows/kr_eps_daily.yml` (quant_py-main repo)
- cron: `0 23 * * 0-4` (UTC 일~목 23:00 = KST 월~금 08:00)
- workflow_dispatch (수동 실행 가능)
- concurrency: `yfinance-data-fetch` (US workflow와 그룹 공유, rate limit 회피)

## 모니터링
- GHA 실패 시 GitHub 이메일 알림 (계정 설정 의존)
- 데이터 누락 감지: 5거래일 연속 parquet 미증가 시 telegram 알람 (TODO)

## 평가 계획
1. **8월 초 60 거래일 누적 달성**
2. NTM score 변화 추적: 매일 누구 들어오고 누구 빠지나, 변동성 어느 정도?
3. paper trade 가상 수익률 (slot 2개, 90/10 비중 US 동일)
4. 코스피 인덱스 대비 알파 측정
5. 알파 입증 시 production 운영 검토 (별도 자본 배분)

## 다음 액션
- [x] run_daily.py 통합 entry
- [x] GHA workflow 등록
- [ ] eps-momentum-us 별도 repo 패턴으로 이전 (선택)
- [ ] daily_runner.py 5,178줄 KR 풀 adapt (Phase 3b, 며칠 작업)
- [ ] paper trade 가상 portfolio 누적 + 코스피 대비 추적
- [ ] 8월 60일 누적 후 정식 BT
