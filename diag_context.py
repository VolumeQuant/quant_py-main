# -*- coding: utf-8 -*-
import sys, json, glob
sys.stdout.reconfigure(encoding='utf-8')

# today's top picks (sanity)
r = json.load(open('state/ranking_20260605.json', encoding='utf-8'))['rankings']
print("=== 0605 ranking: top 8 ===")
for x in r[:8]:
    print(f"  {x['rank']:2} {x['ticker']} {x['name'][:12]:12} score={x['score']:.3f} V/Q/G/M={x['value_s']:+.2f}/{x['quality_s']:+.2f}/{x['growth_s']:+.2f}/{x['momentum_s']:+.2f}")

# count history across all ranking files
print("\n=== ranking 종목수 추이 (최근 25일) ===")
files = sorted(glob.glob('state/ranking_2026*.json'))
rows = []
for f in files:
    d = f.split('ranking_')[1].replace('.json','')
    if not d.isdigit(): continue
    try:
        n = len(json.load(open(f, encoding='utf-8'))['rankings'])
        rows.append((d, n))
    except Exception:
        pass
for d, n in rows[-25:]:
    bar = '#' * (n//10)
    flag = '  <150!' if n < 150 else ''
    print(f"  {d}: {n:4}  {bar}{flag}")

# how many days <150 historically
below = [(d,n) for d,n in rows if n < 150]
print(f"\n전체 {len(rows)}일 중 150 미만: {len(below)}일")
for d,n in below:
    print(f"  {d}: {n}")
