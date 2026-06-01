# KR EPS Momentum — US v84 이식 계획 (2026-06-02 자율세션)

> KR EPS는 pre-v84 base(3슬롯 균등). US v84 검증 로직을 KR에 이식하는 작업.
> ⚠️ KR은 cold start(BT 0일)라 어느 변경도 KR BT 검증 불가 → "US 검증된 로직 이식"만 하고 전부 **provisional**.
> 검증된 알파 mechanism 이식 ≠ 새 미검증 튜닝. KR forward 데이터 1~2개월 누적 후 정식 재검증.

## ✅ 완료 (이번 세션)
- **(D) US 잔재 제거**: 섹터 EPS 모멘텀 US ETF 라벨(XLP/SMH) 제거, 신용·변동성(US VIX/HY/S&P) → KR 국면(KOSPI MA20>MA80 표시). commit 68c89c3c3
- **(b) 저마진 필터 완화**: GM<30%(US)→15% (KR 하드웨어 GM 15~25% 정상 오인 방지). 후보 15→17. commit 7ac49ae36
- **dd_30_25 급락 진입필터**: 30거래일 고점 -25%↓ 종목 제외. high30 계산 + get_part2_candidates 필터. 검증 통과(급락 2종목 제외, 후보 18 정상). commit d0aca26cc

## 📋 검토 후 적용 (사용자 승인 필요 — behavioral 변경)

### 1. defense 게이팅 (★ real-capital 병행 전 필수)
- **현재**: KR 국면은 메시지 표시만, 매매 gate 안 함. → 약세장에도 계속 매수.
- **문제**: production은 약세장 defense=cash인데 KR EPS는 계속 매수 → 병행 시 약세장 이중 노출.
- **US v84 방식**: S&P500<MA200(15일확인) OR VIX>36 → defense(주식 매수중단 + 채권ETF IEF). KR 대응: KOSPI<MA200(또는 MA20<MA80) → 매수중단 + 현금/채권(예: KODEX 국고채).
- **이식 위치**: `select_display_top5`/진입 로직(line ~2935 get_part2_candidates 호출부 또는 main 발송부)에서 regime=defense면 신규 진입 0(보유만 청산).
- **위험**: 현재 공격국면이라 즉시 효과 0. 약세장 전환 시에만 발동. opt-in env 플래그(`KR_EPS_DEFENSE_GATE=1`) 기본 off로 시작 권장.

### 2. dynamic weight 2step_t15 (US v84 비중)
- **현재**: 3슬롯 균등(33/33/33).
- **US v84**: 2슬롯 + 1·2위 score(adj_gap) gap ≥15 → 1위 100%/2위 0%, gap<15 → 50:50.
- **이식**: MAX_SLOTS 3→2, 발송부 비중 계산에 2step_t15 추가(`_get_system_performance`/portfolio 비중).
- **위험**: 슬롯 3→2 = 집중도↑(MDD↑ 가능). leave-one-superwinner-out 검증을 KR 데이터로 해야 하나 cold start라 불가 → **데이터 누적 후 적용 강력 권장**(US조차 v83.3 simulator 결함으로 90/10 폐기한 전례).

### 3. fnguide 증분 인프라 (집PC 풀재크롤 방지 + 가시성)
- **현재**: `refresh_fnguide_incremental.py` stdout flush 없음 → progress 안 보여 hang처럼 보임. 또 git pull이 mtime을 now로 리셋 → 집PC에선 거의 전 종목 재크롤(회사PC는 정상).
- **개선**: ① print flush=True(또는 `sys.stdout.reconfigure(line_buffering=True)`) ② 증분 기준을 mtime 대신 "마지막 성공 발송 이후 신규 DART rcept_dt"로(pull mtime 리셋 영향 제거).
- **위험**: 낮음(인프라). 단 production 파이프라인 공용 파일이라 회사PC 동작 회귀 확인 필요.

## 권장 순서
1. ✅ dd_30_25 (완료)
2. defense 게이팅 — opt-in 플래그로 추가(기본 off), 약세장 대비. **real-capital 병행의 전제조건.**
3. fnguide flush(저위험) → 증분 로직(중위험, 회사PC 회귀확인)
4. dynamic weight — **KR 데이터 1~2개월 후** (집중도 변경은 검증 필수)

## 핵심 원칙
KR EPS는 paper 검증 단계. v84 이식은 "검증된 mechanism 가져오기"지 "KR에서 입증된 알파"가 아님. **실자본 투입은 60일 KR BT 통과 후.** 그 전까진 production이 실자본 주력.
