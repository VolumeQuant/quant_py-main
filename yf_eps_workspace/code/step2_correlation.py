"""YF Step 2 — G_score (v80.6 growth_s) vs YF NTM 모멘텀 점수 correlation

목적: 두 신호의 dimension 독립성 판정
  corr < 0.3: 독립 신호 → 통합 가치 있음
  corr > 0.6: 중복 신호 → v80.7 POP 사례 우려 (노이즈 추가)
  중간: 표본 BT로 추가 알파 측정 필수

NTM 모멘텀 점수 산출 (v80.10b 가중치 기반):
  s_7  = (current - 7d) / |7d|
  s_30 = (current - 30d) / |30d|
  s_60 = (current - 60d) / |60d|
  s_90 = (current - 90d) / |90d|
  NTM_score = 0.30*s_7 + 0.10*s_30 + 0.10*s_60 + 0.50*s_90
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
import numpy as np
from pathlib import Path
from scipy.stats import pearsonr, spearmanr

YF_DATA = Path(r'C:/dev/yf_eps_workspace/results/step1_intersect.csv')
PROD_RANK = Path(r'C:/dev/state/ranking_20260513.json')  # read-only
OUT = Path(r'C:/dev/yf_eps_workspace/results')


def safe_div(num, den):
    return np.where(np.abs(den) > 0, num / np.abs(den), np.nan)


# 1. YF 가용 종목 로드 (ticker는 6자리 0-padded string)
yf = pd.read_csv(YF_DATA, dtype={'ticker': str})
yf['ticker'] = yf['ticker'].str.zfill(6)
print(f'YF intersect: {len(yf)}종목, ticker dtype={yf["ticker"].dtype}, sample={yf["ticker"].head(3).tolist()}')

# 2. fy_complete + na>=3 filter (US 룰 호환)
yf_ok = yf[(yf['fy_complete_0y']) & (yf['na'] >= 3)].copy()
print(f'  US 룰 호환 (fy + na>=3): {len(yf_ok)}종목')

# 3. NTM 모멘텀 점수 (FY 0y 사용)
yf_ok['s_7']  = safe_div(yf_ok['0y_current'] - yf_ok['0y_7d'],  yf_ok['0y_7d'])
yf_ok['s_30'] = safe_div(yf_ok['0y_current'] - yf_ok['0y_30d'], yf_ok['0y_30d'])
yf_ok['s_60'] = safe_div(yf_ok['0y_current'] - yf_ok['0y_60d'], yf_ok['0y_60d'])
yf_ok['s_90'] = safe_div(yf_ok['0y_current'] - yf_ok['0y_90d'], yf_ok['0y_90d'])

# inf 처리 (0y_*가 0)
for c in ['s_7', 's_30', 's_60', 's_90']:
    yf_ok[c] = yf_ok[c].replace([np.inf, -np.inf], np.nan)

# v80.10b 가중치
yf_ok['NTM_score'] = (0.30 * yf_ok['s_7'] + 0.10 * yf_ok['s_30']
                     + 0.10 * yf_ok['s_60'] + 0.50 * yf_ok['s_90'])

# rev_up30 - rev_dn30 (analyst revision 신호)
yf_ok['rev_net30'] = yf_ok['up30'].fillna(0) - yf_ok['dn30'].fillna(0)

# 4. v80.6 ranking 로드
with open(PROD_RANK, encoding='utf-8') as f:
    prod = json.load(f)
prod_by_tic = {r['ticker']: r for r in prod['rankings']}

# 5. 교집합 + 점수 매핑
rows = []
for _, r in yf_ok.iterrows():
    p = prod_by_tic.get(r['ticker'])
    if not p: continue
    rows.append({
        'ticker': r['ticker'], 'name': r.get('name'), 'market': r['market'],
        'mc_krw': r['mc_krw'],
        'g_score': p.get('growth_s'),
        'rev_z': p.get('rev_z'),
        'oca_z': p.get('oca_z'),
        'v_score': p.get('value_s'),
        'q_score': p.get('quality_s'),
        'm_score': p.get('momentum_s'),
        'composite_score': p.get('score'),
        'composite_rank': p.get('composite_rank'),
        'ntm_score': r['NTM_score'],
        's_7': r['s_7'], 's_30': r['s_30'], 's_60': r['s_60'], 's_90': r['s_90'],
        'rev_net30': r['rev_net30'],
        'na': r['na'], 'fwd_pe': r.get('fwd_pe'),
    })
mdf = pd.DataFrame(rows)
mdf = mdf.dropna(subset=['g_score', 'ntm_score'])
print(f'\nMerged (G+NTM valid): {len(mdf)}종목\n')

# 6. Correlation 측정
print('=' * 70)
print('Cross-correlation — v80.6 점수 vs YF NTM 모멘텀 점수')
print('=' * 70)

pairs = [
    ('growth_s   vs NTM',      'g_score',        'ntm_score'),
    ('rev_z      vs NTM',      'rev_z',          'ntm_score'),
    ('oca_z      vs NTM',      'oca_z',          'ntm_score'),
    ('composite  vs NTM',      'composite_score', 'ntm_score'),
    ('m_score    vs NTM',      'm_score',        'ntm_score'),
    ('growth_s   vs rev_net30','g_score',        'rev_net30'),
    ('rev_z      vs rev_net30','rev_z',          'rev_net30'),
    ('growth_s   vs s_7d',     'g_score',        's_7'),
    ('growth_s   vs s_90d',    'g_score',        's_90'),
]
print(f'  {"비교":<28} Pearson    Spearman  |signal|')
print('-' * 70)
corr_results = []
for label, c1, c2 in pairs:
    sub = mdf[[c1, c2]].dropna()
    if len(sub) < 10:
        print(f'  {label:<28} N too small ({len(sub)})')
        continue
    pr, _ = pearsonr(sub[c1], sub[c2])
    sr, _ = spearmanr(sub[c1], sub[c2])
    sig = '★중복' if abs(sr) > 0.6 else ('+상관' if abs(sr) > 0.3 else '독립')
    print(f'  {label:<28} {pr:+7.3f}    {sr:+7.3f}    {sig}  (n={len(sub)})')
    corr_results.append({'pair': label, 'pearson': round(pr, 3), 'spearman': round(sr, 3), 'n': len(sub)})

# 7. NTM Top 픽 vs v80.6 Top 픽 중복도
print('\n' + '=' * 70)
print('NTM Top 10 vs v80.6 Top 10 종목 중복도 (5/13 단일 시점)')
print('=' * 70)
ntm_top = mdf.sort_values('ntm_score', ascending=False).head(10)
v80_top = mdf.sort_values('composite_rank', ascending=True).head(10)
print('\n  NTM Top 10 (yf 모멘텀):')
for _, r in ntm_top.iterrows():
    print(f'    {r["ticker"]} {(r.get("name") or "")[:14]:<15} NTM={r["ntm_score"]:>+6.2f}  '
          f'v80.6_rank={r["composite_rank"]:<4}  g_s={r["g_score"]:>+.2f}')
print('\n  v80.6 Top 10 (composite_rank) — yf 교집합:')
for _, r in v80_top.iterrows():
    print(f'    {r["ticker"]} {(r.get("name") or "")[:14]:<15} rank={r["composite_rank"]:<4}  '
          f'g_s={r["g_score"]:>+.2f}  NTM={r["ntm_score"] if pd.notna(r["ntm_score"]) else "?":>+6}')

overlap = set(ntm_top['ticker']) & set(v80_top['ticker'])
print(f'\n  교집합 Top 10: {len(overlap)}/10 ({len(overlap)*10}%)')

# 8. 결정 신호
print('\n' + '=' * 70)
print('Step 2 진단')
print('=' * 70)
g_ntm_sr = next((r['spearman'] for r in corr_results if 'growth_s' in r['pair'] and 'NTM' in r['pair'] and 'rev' not in r['pair']), None)
if g_ntm_sr is None:
    print('  correlation 데이터 부족')
else:
    print(f'  핵심: growth_s vs NTM Spearman = {g_ntm_sr:+.3f}')
    if abs(g_ntm_sr) < 0.3:
        decision = 'INDEPENDENT'
        print(f'  → ★ 독립 신호 (corr < 0.3). 통합 가치 있음. Step 3 (BT 검증) 진행 추천')
    elif abs(g_ntm_sr) < 0.6:
        decision = 'PARTIAL'
        print(f'  → + 부분 상관 (0.3~0.6). 표본 BT 알파 측정 필수 (Step 4 paired BT)')
    else:
        decision = 'OVERLAP'
        print(f'  → ❌ 중복 신호 (corr > 0.6). v80.7 POP 사례 재현 위험. 통합 비추')

# 9. 저장
mdf.to_csv(OUT / 'step2_merged.csv', index=False, encoding='utf-8-sig')
with open(OUT / 'step2_corr.json', 'w', encoding='utf-8') as f:
    json.dump({'corr_results': corr_results, 'decision': decision if g_ntm_sr is not None else 'INSUFFICIENT',
               'g_ntm_spearman': g_ntm_sr, 'overlap_top10': len(overlap),
               'n_merged': len(mdf)}, f, ensure_ascii=False, indent=2)
print(f'\n저장: {OUT / "step2_merged.csv"}, {OUT / "step2_corr.json"}')
