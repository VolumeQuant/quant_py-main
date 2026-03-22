"""0309 동일 데이터로 old/new renormalization 비교"""
import json, sys, io, numpy as np, pandas as pd
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# --- 0. 0309 원본 355개 종목 ---
with open('state/ranking_20260309_before_fix.json', encoding='utf-8') as f:
    orig = json.load(f)
tickers = [r['ticker'] for r in orig['rankings']]
meta = {r['ticker']: r for r in orig['rankings']}
print(f"0309 종목: {len(tickers)}개")

# --- 1. FnGuide 데이터 로드 ---
from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data, extract_revenue_growth, get_consensus_batch
fs_data = get_all_financial_statements(tickers, use_cache=True)
magic_df = extract_magic_formula_data(fs_data, base_date='20260309', use_ttm=True)
print(f"FnGuide magic_df: {len(magic_df)}개")

# 자본잠식 제외
if '자본' in magic_df.columns:
    magic_df = magic_df[magic_df['자본'] > 0].copy()
    print(f"자본잠식 제외 후: {len(magic_df)}개")

# --- 2. PER/PBR (0309 ranking에서 복원) ---
per_map = {r['ticker']: r.get('per') for r in orig['rankings']}
pbr_map = {r['ticker']: r.get('pbr') for r in orig['rankings']}
magic_df['PER'] = magic_df['종목코드'].map(per_map).astype(float)
magic_df['PBR'] = magic_df['종목코드'].map(pbr_map).astype(float)
print(f"PER: {magic_df['PER'].notna().sum()}, PBR: {magic_df['PBR'].notna().sum()}")

# --- 3. Forward PER (consensus cache) ---
consensus_df = get_consensus_batch(magic_df['종목코드'].tolist())
if consensus_df is not None and not consensus_df.empty:
    fwd_cols = consensus_df[['ticker', 'forward_per']].dropna(subset=['forward_per'])
    magic_df = magic_df.merge(fwd_cols, left_on='종목코드', right_on='ticker', how='left')
    if 'ticker' in magic_df.columns:
        magic_df.drop(columns=['ticker'], inplace=True)
    print(f"Forward PER: {magic_df['forward_per'].notna().sum()}/{len(magic_df)}")

# --- 4. 매출성장률 ---
rev_df = extract_revenue_growth(fs_data, base_date='20260309')
if not rev_df.empty:
    magic_df = magic_df.merge(rev_df, on='종목코드', how='left')
    print(f"매출성장률: {magic_df['매출성장률'].notna().sum()}/{len(magic_df)}")

# --- 5. OHLCV ---
CACHE_DIR = Path('data_cache')
ohlcv_files = sorted(CACHE_DIR.glob("all_ohlcv_*.parquet"))
price_df = pd.read_parquet(ohlcv_files[-1]) if ohlcv_files else pd.DataFrame()
if not price_df.empty:
    price_df = price_df.replace(0, np.nan)
    target = pd.Timestamp('20260309')
    price_df = price_df[price_df.index <= target]
    print(f"OHLCV: {price_df.shape}")

# --- 6. 종목명 추가 ---
name_map = {r['ticker']: r.get('name', '') for r in orig['rankings']}
magic_df['종목명'] = magic_df['종목코드'].map(name_map)
print(f"\n최종 입력: {len(magic_df)}개 종목")

# --- 7. 스코어링 함수 ---
from strategy_b_multifactor import MultiFactorStrategy

def run_scoring(data_in, price_df_in, mode='new'):
    """mode='old': fill -0.5 before renorm, mode='new': fill -0.5 after renorm"""
    data = data_in.copy()
    strategy = MultiFactorStrategy()

    # PER/PBR: already set from ranking JSON
    # Quality factors: calculate directly
    if '당기순이익' in data.columns and '자본' in data.columns:
        data['ROE'] = data['당기순이익'] / data['자본'] * 100
    if '매출총이익' in data.columns and '자산' in data.columns:
        data['GPA'] = data['매출총이익'] / data['자산'] * 100
    if '영업현금흐름' in data.columns and '자산' in data.columns:
        data['CFO'] = data['영업현금흐름'] / data['자산'] * 100
    # EPS개선도
    if 'forward_per' in data.columns and 'PER' in data.columns:
        mask = (data['forward_per'] > 0) & (data['PER'] > 0)
        data['EPS개선도'] = np.nan
        data.loc[mask, 'EPS개선도'] = (data.loc[mask, 'PER'] - data.loc[mask, 'forward_per']) / data.loc[mask, 'PER'] * 100
    # Momentum
    if price_df_in is not None and not price_df_in.empty:
        data = strategy.calculate_momentum(data, price_df_in)

    # PER/PBR 0이하 -> NaN
    for col in ['PER', 'PBR']:
        if col in data.columns:
            data.loc[data[col] <= 0, col] = np.nan

    # WZ z-score
    def wz(series, invert=False, lower=0.025, upper=0.975):
        valid = series.dropna()
        if len(valid) < 5:
            return pd.Series(np.nan, index=series.index)
        q_lo, q_hi = valid.quantile(lower), valid.quantile(upper)
        clipped = series.clip(q_lo, q_hi)
        m, s = clipped.mean(), clipped.std()
        if s == 0 or pd.isna(s):
            return pd.Series(0.0, index=series.index)
        z = (clipped - m) / s
        return -z if invert else z

    value_zs, quality_zs, growth_zs, momentum_zs = [], [], [], []
    for col in ['PER', 'PBR']:
        if col in data.columns:
            data[f'{col}_z'] = wz(data[col], invert=True)
            value_zs.append(f'{col}_z')
    for col in ['ROE', 'GPA', 'CFO']:
        if col in data.columns:
            data[f'{col}_z'] = wz(data[col])
            quality_zs.append(f'{col}_z')
    for col in ['EPS개선도', '매출성장률']:
        if col in data.columns and data[col].notna().sum() > 0:
            data[f'{col}_z'] = wz(data[col])
            growth_zs.append(f'{col}_z')
    if '모멘텀' in data.columns:
        data['모멘텀_z'] = wz(data['모멘텀'])
        momentum_zs.append('모멘텀_z')

    # Category averages
    data['V_raw'] = data[value_zs].mean(axis=1) if value_zs else 0
    data['Q_raw'] = data[quality_zs].mean(axis=1) if quality_zs else 0
    data['G_raw'] = data[growth_zs].mean(axis=1) if growth_zs else 0
    data['M_raw'] = data[momentum_zs].mean(axis=1) if momentum_zs else 0

    # Renormalization (THE KEY DIFFERENCE)
    for raw_col, score_col in [('V_raw', 'V'), ('Q_raw', 'Q'), ('G_raw', 'G'), ('M_raw', 'M')]:
        if mode == 'old':
            # OLD: fill -0.5 BEFORE renorm (contaminated mean/std)
            data[raw_col] = data[raw_col].fillna(-0.5)
            cat_mean = data[raw_col].mean()
            cat_std = data[raw_col].std()
            if cat_std > 0:
                data[score_col] = (data[raw_col] - cat_mean) / cat_std
            else:
                data[score_col] = 0.0
        else:
            # NEW: renorm with valid only, fill -0.5 AFTER
            valid = data[raw_col].dropna()
            cat_mean = valid.mean() if len(valid) > 0 else 0
            cat_std = valid.std() if len(valid) > 0 else 0
            if cat_std > 0:
                data[score_col] = (data[raw_col] - cat_mean) / cat_std
            else:
                data[score_col] = 0.0
            data[score_col] = data[score_col].fillna(-0.5)

    # Category clip (if mode == 'new_clip')
    if mode == 'new_clip':
        for col in ['V', 'Q', 'G', 'M']:
            data[col] = data[col].clip(-3, 3)

    # Piecewise scaling to ±3 (if mode == 'piecewise')
    if mode == 'piecewise':
        for col in ['V', 'Q', 'G', 'M']:
            pos_max = data[col].max()
            neg_min = data[col].min()
            if pos_max > 0:
                data.loc[data[col] > 0, col] = data.loc[data[col] > 0, col] * (3.0 / pos_max)
            if neg_min < 0:
                data.loc[data[col] < 0, col] = data.loc[data[col] < 0, col] * (-3.0 / neg_min)

    # Composite
    data['score'] = data['V'] * 0.25 + data['Q'] * 0.25 + data['G'] * 0.30 + data['M'] * 0.20
    return data

# --- 8. 실행 ---
print("\n" + "=" * 60)
print("OLD (fill -0.5 before renorm)")
print("=" * 60)
old_result = run_scoring(magic_df, price_df, mode='old')

print("\n" + "=" * 60)
print("NEW (fill -0.5 after renorm)")
print("=" * 60)
new_result = run_scoring(magic_df, price_df, mode='new')

print("\n" + "=" * 60)
print("NEW + CLIP (renorm after + category +-3 clip)")
print("=" * 60)
clip_result = run_scoring(magic_df, price_df, mode='new_clip')

print("\n" + "=" * 60)
print("PIECEWISE (renorm after + piecewise +-3 scaling)")
print("=" * 60)
pw_result = run_scoring(magic_df, price_df, mode='piecewise')

# --- 9. Fairness Table ---
weights = {'V': 0.25, 'Q': 0.25, 'G': 0.30, 'M': 0.20}

for label, df in [('OLD (before fix)', old_result), ('NEW (after fix)', new_result), ('NEW+CLIP (+-3)', clip_result), ('PIECEWISE (+-3)', pw_result)]:
    print(f'\n=== {label} ({len(df)}종목) ===')
    print(f'{"Factor":<8} {"Weight":<8} {"MIN":<9} {"MAX":<9} {"MINxW":<9} {"MAXxW":<9} {"Range":<9}')
    print('-' * 61)
    for name in ['V', 'Q', 'G', 'M']:
        w = weights[name]
        mn, mx = df[name].min(), df[name].max()
        print(f'{name:<8} {w:<8.0%} {mn:<9.3f} {mx:<9.3f} {mn*w:<9.3f} {mx*w:<9.3f} {(mx-mn)*w:<9.3f}')
    scores = df['score']
    print(f'{"Total":<8} {"":8} {"":9} {"":9} {"":9} {"":9} {scores.max()-scores.min():<9.3f}')
    print(f'Score: {scores.min():.3f} ~ {scores.max():.3f}')

# --- 10. G NaN 분석 ---
g_nan_old = old_result['G_raw'].isna().sum() if 'G_raw' in old_result.columns else 0
print(f'\nGrowth NaN (둘 다 없는 종목): {g_nan_old}개 / {len(old_result)}개')

# --- 11. Top 5 비교 ---
print('\n=== Top 5 비교 ===')
for label, df in [('OLD', old_result), ('NEW', new_result), ('NEW+CLIP', clip_result), ('PIECEWISE', pw_result)]:
    top5 = df.nlargest(5, 'score')
    print(f'\n{label}:')
    for _, row in top5.iterrows():
        nm = row.get('종목명', '?')
        print(f"  {nm:<12} V={row['V']:+.2f} Q={row['Q']:+.2f} G={row['G']:+.2f} M={row['M']:+.2f} = {row['score']:.3f}")
