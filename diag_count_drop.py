# -*- coding: utf-8 -*-
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

def load(d):
    with open(f'state/ranking_{d}.json', encoding='utf-8') as f:
        return json.load(f)['rankings']

days = ['20260527','20260529','20260602','20260604','20260605']
sets = {}
for d in days:
    r = load(d)
    sets[d] = {x['ticker']: x for x in r}
    print(f"{d}: {len(r)} stocks")

print("\n=== net change ===")
prev = None
for d in days:
    if prev:
        added = set(sets[d]) - set(sets[prev])
        dropped = set(sets[prev]) - set(sets[d])
        print(f"{prev}->{d}: +{len(added)} -{len(dropped)}  (net {len(sets[d])-len(sets[prev])})")
    prev = d

# what dropped 0604 -> 0605
a, b = sets['20260604'], sets['20260605']
dropped = set(a) - set(b)
print(f"\n=== dropped 0604->0605: {len(dropped)} ===")
for t in sorted(dropped):
    x = a[t]
    print(f"  {t} {x['name'][:10]:10} V={x.get('value_s'):.2f} Q={x.get('quality_s'):.2f} G={x.get('growth_s'):.2f} M={x.get('momentum_s'):.2f} rank={x.get('rank')}")
