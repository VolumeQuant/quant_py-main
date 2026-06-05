# 제안: ranking 안전망을 "데이터 사고" vs "시장 급락" 2단계로 분리

> 작성 2026-06-05 (자율). **미적용 — 사용자 승인 후 반영.** 시스템 안전 관련 변경이라 임의 적용 안 함.

## 문제
`run_daily.py` `_validate_ranking(threshold=150)`은 **최종 ranking 종목 수만** 본다.
- 의도: wholesale 수집사고(매핑버그·API 대량실패 등) 감지 → 망가진 신호 채널 발송 차단.
- 한계: **시장 급락으로 MA120 통과 종목이 줄어 자연 감소한 경우**와 구분 못 함.
- 2026-06-05 사고: 데이터 완전 정상인데 시장 -5.5% 급락 → 136종목 → false alarm 발송 보류 (103일 중 첫 미달).

## 핵심 구분 기준
| | 데이터 수집 사고 | 시장 급락(정상) |
|---|---|---|
| 펀더멘털 로드 수 | 급감(<900) | 정상(964) |
| 오늘 가격바 존재 종목 | 급감 | 정상(2827, 전일 2826) |
| pykrx 펀더 vs 전일 | 달라짐 | 동일 |
| 최종 ranking 수 | 낮음 | 낮음 |
→ **최종 수만 같고, 상류 데이터 건강도가 다르다.** 이걸 따로 보면 분리된다.

## 제안 설계 (최소 변경)
`_validate_ranking` 호출부(`run_daily.py:707`) 앞에 데이터 건강도 체크 추가:

```python
def _validate_data_health(base_date, logfile=None):
    """상류 데이터 건강도 — 수집사고 vs 시장현상 구분.
    Returns (healthy: bool, info: dict)"""
    import glob, pandas as pd, numpy as np
    # 1) 오늘 가격바 존재 종목 수
    f = sorted(glob.glob(str(CACHE_DIR/'all_ohlcv_*.parquet')))
    f = [x for x in f if '_full' not in x]; f.sort(key=lambda p: p.split('_')[-1])
    df = pd.read_parquet(f[-1]).replace(0, np.nan)
    ts = pd.Timestamp(base_date)
    today_present = int(df.loc[df.index <= ts].iloc[-1].notna().sum())
    # 2) 펀더멘털(fs_dart) 캐시 파일 수는 FG 로그로 이미 검증됨 — 여기선 가격바로 충분
    healthy = today_present >= 2000          # 정상 ~2800, 사고 시 급감
    return healthy, {'today_price_present': today_present}
```

호출부 분기:
```python
ok_val, n_stocks = _validate_ranking(today, state_dir, threshold=150, logfile=logfile)
if not ok_val:
    healthy, info = _validate_data_health(today, logfile=logfile)
    if healthy:
        # 데이터 정상 → 시장 급락성 저종목. 채널 발송 허용(또는 비경보 보류 — 정책 선택).
        log(f"저종목({n_stocks}) but 데이터 정상(가격바 {info['today_price_present']}) → 시장현상, 정상 발송", logfile)
        _send_personal_warning(f"ℹ️ 종목 수 {n_stocks}개로 적지만 <b>데이터 정상</b> — 시장 급락성 자연감소. 채널 정상 발송.", logfile=logfile)
        # (분기 끝, 아래 정상 발송 흐름으로)
    else:
        # 진짜 수집사고 → 현행 차단+재시도 로직 그대로
        ...현행 코드...
```

## 정책 선택지 (사용자 결정 필요)
- **A) 데이터 정상이면 채널 발송**: 고객이 신호 받음. 단 breadth collapse(천장 신호) 구간에 신규매수 권유가 적절한가 검토 필요.
- **B) 데이터 정상이어도 보류하되 "비경보" 메시지**: 발송은 막되 false alarm 톤 제거, 사고 아님 명시.
- 추천: **B 우선**(보수적, KR 약세장 트라우마 정책과 일관). 멜트업 천장 구간 신규매수는 국면 오버레이/사용자 판단 영역.

## 검증 근거 (diag_health_threshold.py, 최근 40거래일)
- 정상 거래일 가격바 존재수 = **2877~2882** (median 2878). 6/5 = 2877(정상). 임계 2000 마진 +877 → 정상일 절대 안 걸림. ✅
- **휴장일은 0** (예 2026-06-03). → `_validate_data_health`는 **거래일에만 평가** (run_daily base_date는 이미 거래일이라 OK, 단 방어적으로 today_present>0 가드 권장).
- ⚠️ **중요 보강**: 2026-05-28 yfinance 수집사고 의심일도 KR **가격바는 2878 정상**이었음. 즉 펀더멘털/EPS 수집사고는 가격바 수를 안 줄임. → 가격바 체크만으론 펀더 사고 못 잡음. **펀더멘털 로드 수도 반드시 병행 체크.**

## 보강된 health 체크 (2신호 AND)
```python
def _validate_data_health(base_date, fund_loaded, logfile=None):
    # fund_loaded: FG 로그 "재무제표 로드 N종목"의 N (정상 ~964). run_fg_pipeline에서 회수.
    df = ...오늘 가격바...
    today_present = int(...)
    healthy = (today_present >= 2000) and (fund_loaded >= 800)  # 둘 다 정상이어야 '시장현상'
    return healthy, {...}
```
- fund_loaded 회수: FG stdout의 `재무제표 로드 N종목` 파싱 또는 ranking JSON 외 별도 카운트. 정상 964, 임계 800(여유) 권장 — 정상일 분포 추가 확인 후 확정.

## 위험/맹점
- 임계(가격 2000 / 펀더 800)는 표본 적음 — 채택 전 과거 정상일·과거 사고일(5/28 유형) 양쪽 분포 확인 후 확정.
- breadth collapse 자체가 매도/방어 신호일 수 있음 → 별도 트랙(국면·breadth 오버레이)에서 다룰 사안. 이 proposal은 "안전망 오발 제거"에만 한정.
