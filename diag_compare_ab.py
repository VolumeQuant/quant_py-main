# -*- coding: utf-8 -*-
import json, sys, os
sys.stdout.reconfigure(encoding='utf-8')

def load(path):
    return json.load(open(path, encoding='utf-8'))['rankings']

base = {x['ticker']: x for x in load(r'state_diag_base/ranking_20260605.json')}
noext = {x['ticker']: x for x in load(r'state_diag_noext/ranking_20260605.json')}
prod = {x['ticker']: x for x in load(r'state/ranking_20260605.json')}

print(f"production  : {len(prod)}")
print(f"baseline A/B: {len(base)}  (sanity: should ~= production)")
print(f"EXTREME=C   : {len(noext)}  (floor disabled)")
print(f"=> -1.5σ floor removes ~{len(noext)-len(base)} stocks today")

# which dropped good stocks reappear under C?
dropped_good = ['187870','033240','092870','103590','036200','100120']  # high-rank drops vs 0604
print("\ndropped-from-0604 good stocks — present under EXTREME=C?")
for t in dropped_good:
    inC = t in noext
    x = noext.get(t) or base.get(t)
    nm = x['name'] if x else '?'
    print(f"  {t} {nm:10} inC={inC} inBase={t in base}")
