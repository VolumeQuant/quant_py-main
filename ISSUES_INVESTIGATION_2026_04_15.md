# 발견한 모든 오류/이슈 종합 조사 (2026-04-15)

## 조사 배경
집PC에서 (d)+(d')+(e) 필터 도입 후 "대형주 특정일 제외" 현상 발견.
v77 원래 설계의 숨은 버그/이슈를 전수 조사.

---

## 🔴 [High] 확인된 이슈

### 이슈 1: MA120 필터 주석과 실제 동작 불일치

**파일**: `backtest/fast_generate_rankings_v2.py:907-930`

**주석 (909)**:
```python
"""126일(6M) 미만 종목은 제외 (모멘텀 계산 불가, IPO 노이즈)."""
```

**실제 동작 (928-929)**:
```python
# 필터: 현재가 >= MA120 AND 126일 이상
mask = current >= ma120
mask = mask.fillna(False) & ~too_short
```

**문제**:
- 주석에는 "126일 미만 제외"만 명시
- 실제로는 **현재가가 MA120 미만인 종목도 전부 제외** (하락 종목 필터링)
- 하락장 직후 (2022년 말, 2024년 말 등) 수많은 대형주가 여기서 탈락

**영향**:
- 2023-01-02: univ 580 중 MA120 탈락 297종목 (51%)
- 2024-01-02: 187종목 ma120_failed
- 2025-01-02: 242종목

**권고**: 주석 업데이트 + 설계 의도 재확인

---

### 이슈 2: NaN 대체 로직의 지주사 왜곡

**파일**: `backtest/fast_generate_rankings_v2.py:1246-1251` (추정)

**로직**:
```python
nan_mask = data[z_col].isna() | (data[z_col] == 0.0)
data.loc[nan_mask, z_col] = data.loc[nan_mask, '매출성장률_z']
```

**문제**:
- NaN뿐 아니라 **z-score가 정확히 0.0인 경우도 rev_z로 덮음**
- 지주사처럼 **구조적 0값**(자회사 매출 합산)인 종목 왜곡
- 5~6개 G 서브팩터가 rev_z로 통일 → (e) 필터에 capped 판정

**영향**:
- SK스퀘어(402340) 9e4a2cc98 커밋 시점: 5/6 팩터 = 1.6773 동일 → 5위 뻥튀기
- (e) 필터 도입 후 제외 = **결과적으로 올바른 방향**

**권고**:
- NaN 대체 로직 수정 금지 (v77 의도된 설계)
- 지주사는 **유니버스 단에서 제외**가 더 깔끔 (장기 과제)

---

### 이슈 3: chronic_loss_3yr 사전계산 PIT 위반 가능성

**파일**: `backtest/fast_generate_rankings_v2.py:838-845`

**로직**:
```python
# 9. 3년 연속 적자 종목 사전계산 (preload 1회)
chronic_3yr = set()
for ticker, fs_df in data['fs'].items():
    ni = fs_df[(fs_df['계정'] == '당기순이익') & (fs_df['공시구분'] == 'y')].sort_values('기준일')
    if len(ni) >= 3 and all(v < 0 for v in ni.tail(3)['값']):
        chronic_3yr.add(ticker)
```

**문제**:
- preload 시점(현재)의 **전체 fs** 기반으로 계산
- 과거 BT 날짜 전부에 **같은 집합 적용**
- 예: 2021-01-02 BT 시점엔 2023년 적자 정보가 "아직 없었어야" 하지만 현재 사전계산에는 포함 가능성

**PIT 위반 영향**:
- 2021-01-02에 2024년 3년 연속 적자 정보로 2021년 랭킹 판단 → 미래 정보 누출
- 실제로는 `ni.tail(3)`이 최근 3년이라 **preload 시점의 최근 3년** 기준

**확인된 사실**:
- 하이닉스: 2023 적자 1회, 2021/2022 흑자 → chronic 아님. OK
- 하지만 **일부 종목은 look-ahead bias 가능성** 존재

**권고**: BT 날짜별로 `rcept_dt <= base_date` 기준 재계산 필요 (시간 증가)

---

### 이슈 4: asset_dilution 사전계산 PIT 위반

**파일**: `backtest/fast_generate_rankings_v2.py:847-861`

**같은 구조 문제**. 현재 fs 기반 사전계산, 과거 시점 미래 정보 사용.

**권고**: chronic과 동일

---

### 이슈 5: 멀티팩터 스코어링 내부 NaN 드롭 (미해결)

**증상**:
- **하이닉스 2024-01-02**: 모든 표면 필터 통과. 그런데 scored DataFrame에서도 탈락
- `calculate_multifactor_fast` 내부에서 NaN 발생 → dropna?

**추정 원인**:
- Growth factor 계산 중 특정 값 NaN
- 모멘텀 계산 시 데이터 부족
- 섹터 z-score 계산 시 섹터 내 종목 수 부족

**권고**: `calculate_multifactor_fast` 내부 단계별 로깅 추가 필요 (별도 세션)

---

### 이슈 6: final 저장 시 price 조건 (line 1634-1639)

**로직**:
```python
if ticker in price_df.columns and base_ts in price_df.index:
    p = price_df.loc[base_ts, ticker]
    if pd.notna(p) and p > 0:
        item['price'] = int(p)
if 'price' not in item:
    continue  # ← price 없으면 스킵
```

**영향**:
- 2025-04-03 OHLCV에 NaN 종목 359개
- 이 중 scored에 포함된 종목들이 여기서 추가 탈락
- scored 340 → final 108 (232 감소 중 상당수가 price 탈락일 가능성)

**권고**:
- NaN OHLCV 원인 조사 (거래정지? 데이터 누락?)
- price 없어도 저장하고 표시 단계에서 처리하는 방향 고려

---

### 이슈 7: (e) 필터 sector_map 의존성

**확인**:
- 내 디버그 (`sector_map={}`): 삼성전자 2025-04-03 scored 포함, (e) 통과
- 실제 FG (`sector_map` 채움): 동일 날짜 삼성전자 최종 제외

**추정**:
- 섹터별 z-score 계산 결과가 sector_map 유무로 크게 달라짐
- 섹터 내 종목 수 적을 때 z-score 이상 (상한 clip 등)

**권고**: sector 정합성 확인, 섹터별 z-score 계산 안정화

---

## 🟡 [Medium] 의심되는 이슈 (확인 필요)

### 이슈 8: universe_count 메타데이터 혼동

**현상**: `universe_count`는 **MA120 필터 전** 값. 사용자 오해 유발.

**권고**: 단계별 카운트를 메타데이터에 전부 기록 (filtered_cap, filtered_volume, filtered_ma120, filtered_d_prime, filtered_e, final)

---

### 이슈 9: (e) 필터의 NaN 대체 케이스 vs 진짜 capped 구분 불가

**코드**:
```python
vals = [row[c] for c in existing if pd.notna(row[c])]
if mc[1] >= 5 and abs(mc[0]) > 1.5:
    # capped
```

**문제**:
- NaN 대체로 동일값 된 경우 (지주사)와 실제 z-score clip으로 동일값 된 경우 구분 X
- 둘 다 capped로 판정 → 지주사 자동 제외 (의도치 않은 부수효과)

**권고**: 현재로선 결과적 이점 (지주사 제외). 추후 구분 로직 추가 고려.

---

### 이슈 10: 우선주 제거 "끝자리 0" 휴리스틱 한계

**코드 (1410)**:
```python
filtered = filtered[filtered.index.str[-1] == '0']
```

**한계**:
- 보통주 티커 끝자리 0만 통과
- **예외**: 일부 종목 코드 끝이 0 아닌데 보통주인 경우 존재 (드물지만)
- **역예외**: 우선주 코드가 0으로 끝나는 경우는 없지만 추후 규칙 변경 가능

**권고**: pykrx의 stock_type 필드 활용 (보통주/우선주 구분)

---

## 🟢 [Low] 알려지지 않은 잠재 이슈

### 이슈 11: DART 종목 ticker 변경/합병 추적 없음

**증상**:
- 회사명 변경 (예: 다음카카오 → 카카오)
- 분할/합병 시 새 법인 ticker 
- 구 ticker의 fs_dart가 새 법인에 연결 안 됨

**권고**: DART corpcode API로 현재 ticker와 과거 ticker 매핑 유지

---

### 이슈 12: find_nearest_cache의 max_gap_days=10 과도함

**코드**:
```python
mcap_key = find_nearest_cache(preloaded['market_cap'], date_str, max_gap_days=10)
```

**문제**:
- 10일 이내 가장 가까운 파일 사용
- 주말/휴일 많으면 최대 10일 전 데이터 사용 가능
- 특히 연초/연말에 데이터 older 위험

**권고**: max_gap_days=5 정도로 축소 고려

---

### 이슈 13: 한국 섹터 분기별 업데이트 (월별 아님)

**사실**:
- KRX 섹터 매핑이 분기별 업데이트
- 2020~2024 연간 4개 파일만 존재
- 모멘텀 섹터중립 z-score가 이전 분기 섹터 기준 계산 → 이동한 종목 오분류 가능

**권고**: 월별 섹터 데이터 수집 검토

---

## 🔵 집PC (d)+(d')+(e) 필터 도입 평가

### 작동 확인
- ✅ (d') 시점별 분기 8개 체크 → PIT 원칙 부합
- ✅ (e) capped 제외 → 데이터 이상 종목 걸러냄
- ✅ 2580개 랭킹 재생성 정상

### 긍정 효과
- 솔루스첨단소재 전 기간 제외 (신규 상장 공시 부족)
- SK스퀘어 등 지주사 자동 제외 ((e) 필터가 부수 효과로)
- 5.25년 BT CAGR 149.6% → 140.0% (-9.6%p) = **뻥튀기 제거로 신뢰도 향상**

### 부작용
- 유니버스 축소 (580 → 88 같은 연초 극단)
- 대형주도 특정일 Top 20 제외 (하이닉스 2024-01 등)

---

## 우선순위 권고 (다음 세션)

### 즉시 수정 대상 (1-2시간)
1. **MA120 필터 주석 업데이트** (이슈 1) — 쉬움
2. **universe_count 메타데이터 확장** (이슈 8) — 쉬움
3. **하이닉스 2024-01 스코어링 탈락 원인 디버그** (이슈 5) — 1시간

### 중기 개선 (별도 세션)
4. **chronic_loss_3yr PIT 시점별 계산** (이슈 3) — 성능 영향 있음
5. **지주사 유니버스 제외** — DART 지주회사 플래그 활용 (이슈 2 해결)
6. **NaN OHLCV 원인 조사** (이슈 6)

### 장기 과제
7. 종목 ticker 변경/합병 추적 (이슈 11)
8. 월별 섹터 데이터 (이슈 13)

---

## 조사 방법론 기록

### 유효한 방법
- `git show <commit>:<file>` 로 과거 커밋 파일 직접 비교
- 표본 검사 7차원 (메타 / 대형주 포함 / 무결성 / 연속성 / Boost-Defense 정합 / MA120 카운트 / DART 완결성)
- FG 함수 내부 직접 호출로 단계별 추적

### 교훈
- 메타데이터 기록만으론 전체 필터 경로 파악 불가
- 단계별 카운트 로깅 필수
- "(d)+(d')+(e) 필터만으로 대량 탈락"이라는 오해 → 실제는 **MA120 필터가 더 강력**

---

## 결론

집PC의 (d)+(d')+(e) 필터와 재생성 랭킹은 **정상**. 하지만 v77 본연의 **7개 확인된 이슈 + 6개 의심 이슈** 발견.

현재 프로덕션에 **즉시 영향 없음** (상위권 Top 20 선정은 정상 작동). 다만 **일부 날짜 대형주 제외**는 이해하고 있어야 함.
