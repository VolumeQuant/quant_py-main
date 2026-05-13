"""150 비정수 점프 종목 — 옛 OHLCV vs 새 OHLCV 비교

판단 기준:
- 옛 정상 + 새 점프 → 새 OHLCV 잘못
- 옛 점프 + 새 정상 → 옛 OHLCV 잘못 (refill로 정정됨)
- 둘 다 점프 → 진짜 액면/거래정지 재개
- 옛 없음 + 새 있음 → 신규 (점프 무관)
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np

old = pd.read_parquet('C:/dev/data_cache_ohlcv_backup_20260513/all_ohlcv_20170601_20260511.parquet').replace(0, np.nan)
new = pd.read_parquet('C:/dev/data_cache/all_ohlcv_20170601_20260512.parquet').replace(0, np.nan)

print(f'옛 OHLCV: {old.shape}')
print(f'새 OHLCV: {new.shape}')

# 새 OHLCV에서 비정수 점프 150종목 다시 추출
weekdays = new[new.index.dayofweek < 5]
zero_pct_per_day = (weekdays.isna()).sum(axis=1) / weekdays.shape[1]
trading = weekdays[zero_pct_per_day < 0.5]

irregular = []
for tk in trading.columns:
    series = trading[tk].dropna()
    if len(series) < 100: continue
    ratio = series / series.shift(1)
    extreme = ratio[(ratio > 10) | (ratio < 0.1)]
    if not extreme.empty:
        is_int = all(any(abs(abs(r) - n) < n*0.1 for n in [2,3,4,5,10,20]) for r in extreme.values)
        if not is_int:
            irregular.append((tk, extreme.index[0], extreme.iloc[0]))

print(f'\n비정수 점프 종목: {len(irregular)}')

# 점프 종목 옛/새 비교
def get_price(df, tk, date, offset=0):
    """date에서 offset 거래일 가격"""
    if tk not in df.columns: return None
    series = df[tk].dropna()
    series = series[series.index <= date] if offset <= 0 else series
    series = series.replace(0, np.nan).dropna()
    if len(series) == 0: return None
    if offset == 0:
        if date in series.index:
            return float(series.loc[date])
        return None
    elif offset < 0:
        return float(series.iloc[offset]) if len(series) >= abs(offset) else None
    return None


# 분류
classes = {'old_jump_new_normal': [], 'old_normal_new_jump': [], 'both_jump': [],
           'no_old': [], 'unclear': []}

for tk, jump_dt, jump_ratio in irregular:
    # 새 OHLCV: 점프 직전, 점프 직후
    s_new = new[tk].dropna()
    s_new = s_new[s_new > 0]
    if jump_dt not in s_new.index: continue
    new_idx = s_new.index.get_loc(jump_dt)
    if new_idx == 0: continue
    new_pre = float(s_new.iloc[new_idx-1])
    new_post = float(s_new.iloc[new_idx])

    # 옛 OHLCV: 같은 날
    if tk not in old.columns:
        classes['no_old'].append((tk, jump_dt, new_pre, new_post))
        continue
    s_old = old[tk].dropna()
    s_old = s_old[s_old > 0]
    if jump_dt not in s_old.index:
        classes['no_old'].append((tk, jump_dt, new_pre, new_post))
        continue
    old_idx = s_old.index.get_loc(jump_dt)
    if old_idx == 0:
        classes['no_old'].append((tk, jump_dt, new_pre, new_post))
        continue
    old_pre = float(s_old.iloc[old_idx-1])
    old_post = float(s_old.iloc[old_idx])

    # 점프 비율
    new_jump = new_post / new_pre
    old_jump = old_post / old_pre if old_pre > 0 else 0

    is_new_jump = (new_jump > 5 or new_jump < 0.2)
    is_old_jump = (old_jump > 5 or old_jump < 0.2)

    info = (tk, jump_dt.date(), old_pre, old_post, new_pre, new_post)
    if is_old_jump and not is_new_jump:
        classes['old_jump_new_normal'].append(info)  # 새 정정
    elif not is_old_jump and is_new_jump:
        classes['old_normal_new_jump'].append(info)  # 옛이 정확
    elif is_old_jump and is_new_jump:
        classes['both_jump'].append(info)  # 진짜 액면/재개
    else:
        classes['unclear'].append(info)

print(f'\n=== 분류 ===')
print(f'  옛 점프 + 새 정상 (refill로 정정): {len(classes["old_jump_new_normal"])}')
print(f'  옛 정상 + 새 점프 (새가 잘못): {len(classes["old_normal_new_jump"])} ⚠️')
print(f'  둘 다 점프 (액면/재개 가능): {len(classes["both_jump"])}')
print(f'  옛 없음 (신규/회복 어려움): {len(classes["no_old"])}')
print(f'  불명확: {len(classes["unclear"])}')

# 새 잘못된 케이스 표본 (가장 위험)
if classes['old_normal_new_jump']:
    print(f'\n⚠️ 옛 정상 + 새 점프 (새 OHLCV refill 사고 의심):')
    for tk, dt, op, opo, np_, np_post in classes['old_normal_new_jump'][:10]:
        print(f'  {tk} {dt}: 옛 {int(op)}→{int(opo)} | 새 {int(np_)}→{int(np_post)}')

# 옛 점프 + 새 정상 (refill 정정 — 좋은 신호)
if classes['old_jump_new_normal']:
    print(f'\n✓ 옛 점프 + 새 정상 (refill 정정 효과):')
    for tk, dt, op, opo, np_, np_post in classes['old_jump_new_normal'][:5]:
        print(f'  {tk} {dt}: 옛 {int(op)}→{int(opo)} | 새 {int(np_)}→{int(np_post)}')

# 둘 다 점프 — 진짜 액면 또는 재개
if classes['both_jump']:
    print(f'\n📊 둘 다 점프 (진짜 액면/거래재개 가능):')
    for tk, dt, op, opo, np_, np_post in classes['both_jump'][:5]:
        print(f'  {tk} {dt}: 옛 {int(op)}→{int(opo)} | 새 {int(np_)}→{int(np_post)}')

# 옛 없음 (신규상장 등)
print(f'\nℹ️ 옛 없음 (신규상장/거래재개): {len(classes["no_old"])} 종목')
