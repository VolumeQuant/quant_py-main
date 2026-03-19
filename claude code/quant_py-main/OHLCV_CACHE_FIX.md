# 캐시 문제 정리 및 홈PC 작업 가이드 (2026-03-19)

## 1. 무슨 문제가 있었나

### 버그 2개 (해결 완료)

**OHLCV 증분 업데이트 오염** (커밋 84ab431)
- 하루치 가격 추가할 때 `get_market_ohlcv_by_ticker(date, market='ALL')`이 전 시장 2800+종목을 캐시에 넣음
- 원래 ~880종목이어야 할 캐시가 2800+종목으로 뻥튀기
- MA120 계산 대상이 늘어나서 scored가 ~140 → ~400으로 증가
- **수정**: 유니버스 종목만 필터링하여 저장하도록 변경

**KRX 인증 고장** (2주간)
- 비밀번호 변경 후 config.py 미반영 + 중복 로그인 미처리
- pykrx가 데이터를 못 가져와서 OHLCV 증분 업데이트 실패
- **수정**: 비밀번호 업데이트 + krx_auth.py에 CD011 중복 로그인 처리

### 미해결 이슈: 시장 폭등 시 유니버스 확장

3/18 코스피 +5.04% 폭등 → MA120 위로 올라오는 종목 급증 가능.
회사PC에서 3/18 가격 반영 후 테스트한 결과:
- MA120 통과: 246개 → 562개
- scored: 139 → 318
- 삼성전자: 4위 → 7위

이건 버그가 아니라 시장 현실일 수 있음. **홈PC에서 확인 필요.**

---

## 2. 현재 상태

### 회사PC (3/19 낮 기준)
- 캐시 전부 삭제 후 처음부터 재수집
- OHLCV: 695종목, 3/18 가격 반영됨
- 결과: universe=710, scored=318, 삼성전자 7위
- ranking JSON은 git 원본(scored=139)으로 복원해둠

### 홈PC (3/19 06:17 기준, git 원본)
- ranking_20260318.json: universe=715, scored=139, 삼성전자 4위
- 3/18 폭등이 반영됐는지 불확실 (OHLCV 캐시 상태 미확인)

### 두 PC 결과 차이
| 항목 | 홈PC | 회사PC |
|------|------|--------|
| universe | 715 | 710 |
| MA120 통과 | 246 | 562 |
| scored | 139 | 318 |
| 삼성전자 | 4위 | 7위 |
| 3/18 가격 반영 | 불확실 | 반영됨 |

---

## 3. 매일 유니버스 계산 구조

| 데이터 | 소스 | 갱신 주기 | 비고 |
|--------|------|----------|------|
| 시총/거래대금 | pykrx 실시간 | 매일 | 유니버스 결정 |
| OHLCV(가격) | pykrx → 캐시 증분 | 매일 | MA120/모멘텀 계산, 증분 버그 수정 완료 |
| FnGuide(재무제표) | FnGuide 크롤링 → 캐시 | 주 1회 | 분기 데이터, 매일 갱신 불필요 |

증분 버그 + KRX 인증이 고쳐졌으니, 앞으로는 매일 최신 가격으로 유니버스/MA120이 정확하게 계산됨.

---

## 4. 홈PC 작업 순서

### Step 1: git pull
```bash
git pull
```
증분 업데이트 오염 방지 코드(84ab431) 반영. **다음 자동 실행 전에 반드시.**

### Step 2: OHLCV 캐시 상태 확인
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
- 종목 수 1000+ → 오염. 해당 파일 삭제.
- 마지막 날짜가 3/17이면 → 3/18 폭등 미반영
- 마지막 날짜가 3/18이면 → 반영됨

### Step 3: create_current_portfolio.py 실행
```bash
python create_current_portfolio.py
```

### Step 4: 결과 확인
```bash
python -c "
import json
for d in ['20260317','20260318','20260319']:
    try:
        with open(f'state/ranking_{d}.json') as f:
            data = json.load(f)
        n = len(data['rankings'])
        meta = data.get('metadata', {})
        top4 = [r['name'] for r in data['rankings'][:4]]
        print(f'{d}: scored={n} universe={meta.get(\"total_universe\")} Top4={top4}')
    except: pass
"
```

### Step 5: 판단
- **scored ~140, 삼성전자 4위** → 기존 시스템 정상. 변경 불필요.
- **scored ~318, 삼성전자 7위** → 3/18 폭등이 반영된 결과. 유니버스 확장 문제가 실제로 발생. 72/68 기준 재논의 필요.

### Step 6: 결과 기록
이 파일에 결과 기록 후 커밋.

---

## 5. 참고: 검증 기준표

| 항목 | 정상 범위 | 오염/비정상 |
|------|----------|-----------|
| OHLCV 캐시 종목 수 | ~700~900 | 1000+ |
| universe | ~700~800 | 900+ |
| MA120 통과 | ~230~250 | 500+ |
| scored | ~120~150 | 300+ |
| 삼성전자 순위 | 1~4위 | 7위+ |

※ 시장 폭등 시 MA120 통과/scored가 일시적으로 증가하는 건 정상일 수 있음.
이 경우 위 기준표가 아닌 시장 상황과 함께 판단 필요.
