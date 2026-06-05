"""EDA1: per/price 일별 반응성 + JSON 종목수 분포 확인."""
import json, glob, sys
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')

files = sorted(glob.glob('state/ranking_2024*.json'))
print('n files 2024:', len(files))

# 1) 종목 수 분포
counts = []
for f in files[::20]:
    d = json.load(open(f, encoding='utf-8'))
    items = d if isinstance(d, list) else d.get('rankings', [])
    counts.append(len(items))
print('item counts (every 20th file):', counts)
print('min/max/mean count:', min(counts), max(counts), round(np.mean(counts),1))

# 2) per/price 일별 반응성: 한 종목을 연속일에 추적
# 삼성전자 005930, SK하이닉스 000660, 제룡전기 033100
track = {'005930':[], '000660':[], '033100':[]}
seq_files = sorted(glob.glob('state/ranking_2024*.json'))[80:110]  # 30 연속일
for f in seq_files:
    date = f.split('_')[-1].replace('.json','')
    d = json.load(open(f, encoding='utf-8'))
    items = d if isinstance(d, list) else d.get('rankings', [])
    by_tk = {it['ticker']: it for it in items}
    for tk in track:
        if tk in by_tk:
            it = by_tk[tk]
            track[tk].append((date, it.get('price'), it.get('per'), it.get('pbr'),
                              it.get('value_s'), it.get('composite_rank')))

for tk, rows in track.items():
    print(f'\n=== {tk} (date, price, per, pbr, value_s, comp_rank) ===')
    for r in rows[:15]:
        print('   ', r)
    # price 변하는데 per 변하나? 상관 확인
    if len(rows) > 5:
        prices = np.array([r[1] for r in rows if r[1]], dtype=float)
        pers = np.array([r[2] for r in rows if r[2] is not None], dtype=float)
        if len(prices)>3 and len(pers)==len(prices):
            dp = np.diff(prices)
            dper = np.diff(pers)
            # 가격 변한 날 중 per도 변한 비율
            price_moved = np.abs(dp) > 0
            per_moved = np.abs(dper) > 1e-9
            both = (price_moved & per_moved).sum()
            print(f'    price-moved days: {price_moved.sum()}/{len(dp)}, per-also-moved: {both}')
            print(f'    price std: {prices.std():.0f}, per std: {pers.std():.3f}, per range: {pers.min():.2f}~{pers.max():.2f}')
