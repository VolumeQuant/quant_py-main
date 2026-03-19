# OHLCV 캐시 오염 문제 — 홈PC 작업 가이드

## 문제 요약

OHLCV 증분 업데이트에서 `get_market_ohlcv_by_ticker(date, market='ALL')`이
전 시장 2800+종목 종가를 가져와 캐시에 추가함.
캐시가 882종목 → 2800+종목으로 뻥튀기 → MA120 계산 대상 증가 → scored ~140 → ~400.

**scored ~140이 정상, ~400은 오염 결과.**

## 발생 경위

1. KRX 인증 수정 후 증분 업데이트가 처음으로 성공
2. `market='ALL'`로 전 종목 종가를 가져와 기존 캐시(~882종목)에 concat
3. 캐시에 없던 ~1900종목이 추가됨 (과거 날짜는 NaN)
4. MA120 계산 대상이 882 → 2800+ → 통과 종목 급증 → scored 뻥튀기

## 이미 수정된 것 (커밋 84ab431)

`create_current_portfolio.py` 증분 업데이트 로직 수정:
- 전 시장 종가를 가져오되, **기존 캐시 종목 + 현재 유니버스 종목**만 필터링하여 저장
- 유니버스에 새로 들어온 종목은 과거 데이터를 개별 수집
- 유니버스에서 빠진 종목은 캐시에 남아있어도 MA120 필터에서 자연 제외

## 홈PC 현재 상태 (3/19 기준)

- 3/18 저녁에 캐시 정리 + 재실행 → 정상 캐시(~880종목, 3/18까지) 생성
- 3/19 06:17 자동 실행 시 캐시 히트(3/18 데이터 있음) → 증분 미발생 → **오염 없음**
- ranking_20260318.json: scored=139, 삼성전자 4위 → **정상**

## 언제 오염이 다시 발생하나

다음 거래일(3/19) 데이터로 `create_current_portfolio.py` 실행 시:
- 캐시에 3/19 없음 → 증분 업데이트 발생 → `market='ALL'` → 오염
- **그 전에 git pull로 수정 코드(84ab431) 반영 필요**

## 홈PC에서 해야 할 것

### 1. git pull (수정 코드 반영) — 다음 자동 실행 전에 반드시
```bash
git pull
```

### 2. 오염 여부 확인
```bash
python -c "
import pandas as pd
from pathlib import Path
for f in sorted(Path('data_cache').glob('all_ohlcv_*.parquet')):
    df = pd.read_parquet(f)
    flag = ' ← 오염!' if df.shape[1] > 1000 else ''
    print(f'{f.name}: {df.shape[1]}종목 × {df.shape[0]}거래일{flag}')
"
```
종목 수 1000+ 이면 오염. 현재는 정상(~880)일 것으로 예상.

### 3. 오염됐으면 삭제 후 재실행
```bash
# 오염 파일 삭제 (종목 수 1000+ 인 것만)
# 정상 캐시(~880종목)만 남기고 create_current_portfolio.py 재실행
# scored ~140 나오면 정상
```

## 검증 기준

| 항목 | 정상 | 오염 |
|------|------|------|
| OHLCV 캐시 종목 수 | ~880개 | 2000+개 |
| universe | ~700~800 | 900+개 |
| MA120 통과 (prefilter) | ~230~250 | 600+개 |
| scored | ~120~150 | 300+개 |
| 삼성전자 순위 | 4위 | 7위+ |

## 근본 원인

`get_market_ohlcv_by_ticker(date, market='ALL')`은 해당 날짜의
**전 시장 종목** OHLCV를 한번에 반환하는 함수.
증분 업데이트에서 이 함수를 쓰면 유니버스와 무관한 종목이 캐시에 유입됨.
수정 코드(84ab431)에서 유니버스 종목만 필터링하도록 변경.
