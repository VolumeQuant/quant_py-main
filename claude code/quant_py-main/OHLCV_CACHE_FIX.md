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

## 홈PC에서 해야 할 것

### 1. git pull (수정 코드 반영)
```bash
git pull
```

### 2. 오염된 OHLCV 캐시 삭제
```bash
# data_cache/ 에서 오염된 캐시 확인
# 종목 수가 2000+ 인 파일이 오염된 것
python -c "
import pandas as pd
from pathlib import Path
for f in sorted(Path('data_cache').glob('all_ohlcv_*.parquet')):
    df = pd.read_parquet(f)
    flag = ' ← 오염!' if df.shape[1] > 1000 else ''
    print(f'{f.name}: {df.shape[1]}종목 × {df.shape[0]}거래일{flag}')
"

# 오염된 파일 삭제 (종목 수 1000+ 인 것)
# 정상 캐시(~880종목)만 남겨야 함
```

### 3. ranking JSON 확인
```bash
# 현재 ranking JSON이 정상인지 확인
# scored가 ~140 범위여야 정상
python -c "
import json
for d in ['20260316','20260317','20260318']:
    with open(f'state/ranking_{d}.json') as f:
        data = json.load(f)
    print(f'{d}: scored={len(data[\"rankings\"])}')
"
```

### 4. 재실행 테스트
```bash
# OHLCV 캐시 삭제 후 create_current_portfolio.py 실행
# 전체 재수집 발생 → 유니버스 종목 기준으로 정상 캐시 생성
# scored ~140 나오면 정상
python create_current_portfolio.py
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
