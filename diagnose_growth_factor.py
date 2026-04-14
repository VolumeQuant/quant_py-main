"""Growth 팩터 실패 원인 진단
가설 A: 2016 데이터 없는 종목만 Growth 0 → 수집 확장 도움
가설 B: 2016 있는 종목도 Growth 0 → 다른 원인 (로직 문제)
"""
import pandas as pd
import json
from pathlib import Path

# 2018-01-02 ranking에서 rev_z 값 분포
d = json.load(open('C:/dev/backtest/bt_extended_h1_sample/ranking_20180102.json', 'r', encoding='utf-8'))
rks = d['rankings']
print(f'Ranking: {len(rks)}종목')

# fs_dart 2016 분기 커버리지 캐시
CACHE = Path('C:/dev/data_cache')
fs_tickers_2016 = {}
for fp in CACHE.glob('fs_dart_*.parquet'):
    ticker = fp.stem.replace('fs_dart_', '')
    try:
        df = pd.read_parquet(fp)
        if df.empty:
            fs_tickers_2016[ticker] = 0
            continue
        y2016 = df[df['기준일'].dt.year == 2016]
        fs_tickers_2016[ticker] = len(y2016['기준일'].unique())
    except:
        fs_tickers_2016[ticker] = 0

# ranking에 나온 종목의 2016 커버리지 분석
coverage_counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
growth_by_coverage = {0: [], 1: [], 2: [], 3: [], 4: []}
for r in rks:
    tk = r['ticker']
    cov = fs_tickers_2016.get(tk, 0)
    coverage_counts[cov] = coverage_counts.get(cov, 0) + 1
    rev_z = r.get('rev_z', 0)
    growth_by_coverage.setdefault(cov, []).append(rev_z)

print(f'\n2018-01-02 ranking 149종목의 2016 DART 커버리지:')
for cov, cnt in sorted(coverage_counts.items()):
    gvs = growth_by_coverage.get(cov, [])
    non_zero = sum(1 for v in gvs if v != 0)
    print(f'  2016 분기수={cov}: {cnt}종목, rev_z!=0: {non_zero}/{cnt}')

# 상위 10개 종목 상세
print(f'\n상위 10개 종목 상세:')
for r in rks[:10]:
    tk = r['ticker']
    cov = fs_tickers_2016.get(tk, 0)
    print(f'  {tk} {r.get("name", "")}: 2016분기={cov}, rev_z={r.get("rev_z", 0)}, oca_z={r.get("oca_z", 0)}, score={r.get("score", 0):.3f}')

# 2016 완전 커버 종목(Q1~Q4) 찾아서 ranking에 있는지 샘플 확인
full_2016 = [t for t, c in fs_tickers_2016.items() if c >= 4]
print(f'\n전체 2016 완전 커버 종목: {len(full_2016)}')
ranked_tickers = {r["ticker"] for r in rks}
full_in_ranking = set(full_2016) & ranked_tickers
print(f'이 중 2018-01-02 ranking에 있는 종목: {len(full_in_ranking)}')
if full_in_ranking:
    # 이 종목들의 rev_z 값
    samples = []
    for r in rks:
        if r['ticker'] in full_in_ranking:
            samples.append((r['ticker'], r.get('name', ''), r.get('rev_z', 0), r.get('oca_z', 0)))
    non_zero = sum(1 for _, _, rz, _ in samples if rz != 0)
    print(f'  이 중 rev_z != 0: {non_zero}/{len(samples)}')
    print(f'  샘플 5개: {samples[:5]}')
