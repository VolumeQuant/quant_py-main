# OHLCV 캐시 문제 — 홈PC 작업 가이드

## 확실한 것

1. **OHLCV 증분 업데이트 버그**: `market='ALL'`로 전 시장 2800+종목을 캐시에 추가하는 버그 존재. 수정 커밋(84ab431)으로 유니버스 종목만 필터링하도록 변경 완료.

2. **회사PC에서 캐시 전부 삭제 후 재수집한 결과** (3/19 낮 실행):
   - universe=710, MA120 통과=562, scored=318
   - 삼성전자 7위
   - OHLCV 695종목, 3/18 가격 반영됨

3. **홈PC 결과** (3/19 06:17 자동 실행, git 원본):
   - universe=715, MA120 통과=246, scored=139
   - 삼성전자 4위
   - 텔레그램 메시지에서 "거래대금 충족 715종목" 확인

4. **같은 3/18 시장인데 결과가 다름**:
   - 회사PC: MA120 통과 562개
   - 홈PC: MA120 통과 246개
   - 차이 316개 → 3/18 코스피 +5.04% 폭등이 반영됐느냐의 차이로 추정

5. **3/18 시장 폭등 사실**: 코스피 +5.04%, 삼성전자/SK하이닉스 7~8% 급등

## 모르는 것 (홈PC에서 확인 필요)

1. **홈PC OHLCV 캐시의 정확한 상태**
   - 캐시 종목 수, 날짜 범위, 3/18 가격 포함 여부
   - `ls data_cache/all_ohlcv_*.parquet` + parquet shape 확인 필요

2. **홈PC에서 3/18 가격이 반영됐는지**
   - 3/18 저녁에 캐시 재구축했을 때 KRX가 3/18 종가를 줬는지
   - OHLCV 캐시의 마지막 날짜가 3/18인지 3/17인지

3. **내일 홈PC 자동 실행 시 어떤 결과가 나올지**
   - 3/18 가격이 반영되면 scored ~318로 증가할 수 있음
   - 이 경우 삼성전자 7위로 하락 + 72점 기준 문제 재발 가능

## 홈PC에서 해야 할 것

### 1. git pull — 다음 자동 실행 전에 반드시
```bash
git pull
```
증분 업데이트 `market='ALL'` 오염 방지 코드(84ab431) 반영.

### 2. OHLCV 캐시 상태 확인
```bash
python -c "
import pandas as pd
from pathlib import Path
for f in sorted(Path('data_cache').glob('all_ohlcv_*.parquet')):
    df = pd.read_parquet(f)
    flag = ' ← 오염!' if df.shape[1] > 1000 else ''
    last_date = df.index[-1].strftime('%Y%m%d')
    print(f'{f.name}: {df.shape[1]}종목 × {df.shape[0]}거래일, 마지막={last_date}{flag}')
"
```

### 3. 확인 포인트
- 캐시 종목 수 1000+ 이면 오염 → 삭제 후 재실행
- 캐시 마지막 날짜가 3/17이면 → 3/18 폭등 미반영 상태
- 캐시 마지막 날짜가 3/18이면 → 3/18 반영됨, scored 증가 가능

### 4. scored 검증
```bash
python -c "
import json
for d in ['20260317','20260318']:
    with open(f'state/ranking_{d}.json') as f:
        data = json.load(f)
    print(f'{d}: scored={len(data[\"rankings\"])} universe={data.get(\"metadata\",{}).get(\"total_universe\")}')
"
```

## 핵심 질문 (홈PC에서 답해야 함)

**3/18 코스피 +5.04% 폭등으로 MA120 통과 종목이 246→562개로 증가하는 게 정상인가?**

- 정상이라면: scored ~318이 맞고, 삼성전자 7위 + 72점 기준 문제가 실제로 발생
- 비정상이라면: 캐시 또는 데이터 문제이고, scored ~139가 맞음

이건 캐시 상태를 확인한 뒤 판단 가능.

## 홈PC 작업 순서

1. `git pull` — 증분 업데이트 수정 코드 + 이 문서 반영
2. OHLCV 캐시 상태 확인 (위 스크립트 실행)
3. 오염됐으면 삭제 (종목 수 1000+ 인 파일)
4. `python create_current_portfolio.py` 실행
5. scored 확인:
   - **~139면**: 3/18 가격 미반영 상태. 기존 시스템 정상 동작.
   - **~318이면**: 3/18 폭등이 반영된 결과. 유니버스 확장 문제가 실제로 발생.
     → 삼성전자 7위 + 72점 기준 문제 재논의 필요.
6. 결과를 이 md파일에 기록 후 커밋
