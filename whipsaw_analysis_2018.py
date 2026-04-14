"""2018 whipsaw 정밀 분석
KP_MA200_5d 규칙 재현 → 2018/2023/2024 국면전환 횟수/간격 비교
"""
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, 'C:/dev')

# KOSPI 시리즈 병합
df = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
c0 = df.columns[0]  # 종가 (깨짐)
kospi = df[c0].fillna(df['kospi']).rename('close')
kospi = kospi.sort_index()
print(f'KOSPI: {kospi.index.min().date()} ~ {kospi.index.max().date()}, {len(kospi)} days')

# MA200
ma200 = kospi.rolling(200).mean()

# 단일일 signal: 1=attack(>MA200), 0=defense(<MA200)
raw_signal = (kospi > ma200).astype(int)

# 5일 연속 확인 규칙: 5일 연속 같은 방향이어야 전환
# 현재 regime은 "5일 연속 새 방향이 나오면 전환"
def apply_5d_rule(raw_signal, start_regime=None):
    """5일 연속 같은 방향 확인 후 전환"""
    regimes = []
    current = start_regime
    for i, sig in enumerate(raw_signal):
        if current is None:
            # 초기: MA200 계산 가능 + 첫 5일 일치
            if i >= 4 and raw_signal.iloc[i-4:i+1].nunique() == 1:
                current = int(sig)
            regimes.append(current)
            continue
        # 5일 연속 새 방향이면 전환
        if i >= 4:
            last5 = raw_signal.iloc[i-4:i+1]
            if last5.nunique() == 1 and int(last5.iloc[0]) != current:
                current = int(last5.iloc[0])
        regimes.append(current)
    return pd.Series(regimes, index=raw_signal.index, name='regime')

regime = apply_5d_rule(raw_signal)
valid = regime.dropna()

# 전환 이벤트 추출
transitions = []
prev = None
for dt, r in valid.items():
    if prev is not None and r != prev:
        transitions.append({'date': dt, 'from': prev, 'to': r})
    prev = r

tr_df = pd.DataFrame(transitions)
if not tr_df.empty:
    tr_df['gap_days'] = tr_df['date'].diff().dt.days
    print(f'\n=== 전체 전환 이벤트: {len(tr_df)}건 ===')
    print(tr_df.to_string())

    # 연도별 집계
    tr_df['year'] = tr_df['date'].dt.year
    yearly = tr_df.groupby('year').agg(
        count=('date', 'count'),
        mean_gap=('gap_days', 'mean'),
        min_gap=('gap_days', 'min')
    )
    print(f'\n=== 연도별 전환 ===')
    print(yearly.to_string())

    # Whipsaw 정의: gap <= 60일 (2개월 이내 재전환)
    wh = tr_df[tr_df['gap_days'] <= 60]
    print(f'\n=== Whipsaw (gap≤60일): {len(wh)}건 ===')
    print(wh.to_string())

    # 2018년 집중
    y2018 = tr_df[tr_df['year'] == 2018]
    print(f'\n=== 2018년 전환 상세: {len(y2018)}건 ===')
    print(y2018.to_string())

# KOSPI/MA200 괴리율
gap_pct = (kospi - ma200) / ma200 * 100
for year in [2018, 2023, 2024]:
    sub = gap_pct[gap_pct.index.year == year].dropna()
    if len(sub) == 0:
        continue
    print(f'\n=== {year}년 KOSPI/MA200 괴리율 분포 ===')
    print(f'  count={len(sub)}, mean={sub.mean():.2f}%, std={sub.std():.2f}%')
    print(f'  min={sub.min():.2f}%, max={sub.max():.2f}%')
    print(f'  |gap|<2%: {((sub.abs()<2).sum()/len(sub)*100):.1f}%')
    print(f'  |gap|<5%: {((sub.abs()<5).sum()/len(sub)*100):.1f}%')

# 저장
out = pd.DataFrame({'close': kospi, 'ma200': ma200, 'gap_pct': gap_pct, 'raw_signal': raw_signal, 'regime': regime})
out.to_parquet('C:/dev/data_cache/regime_analysis_2017_2026.parquet')
print(f'\n저장: regime_analysis_2017_2026.parquet')
if not tr_df.empty:
    tr_df.to_csv('C:/dev/data_cache/regime_transitions.csv', index=False, encoding='utf-8-sig')
    print(f'저장: regime_transitions.csv ({len(tr_df)}건)')
