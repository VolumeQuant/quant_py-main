# -*- coding: utf-8 -*-
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

# The ranking JSON only contains SURVIVORS (post-filter). To see how the floor
# bites, inspect how close survivors sit to the -1.5 edge per factor, and how
# the count trend correlates with KOSPI momentum.
days = ['20260527','20260529','20260602','20260604','20260605']
cols = [('value_s','V'),('quality_s','Q'),('growth_s','G'),('momentum_s','M')]
for d in days:
    r = json.load(open(f'state/ranking_{d}.json',encoding='utf-8'))['rankings']
    n = len(r)
    # min of each factor among survivors (should be >= -1.5 if floor applied)
    mins = {lbl: min(x.get(c,0) for x in r) for c,lbl in cols}
    # how many survivors sit within 0.2 of the -1.5 floor on their worst factor
    near = sum(1 for x in r if min(x.get(c,0) for c,_ in cols) <= -1.3)
    # how many have ANY factor below -1.5 (should be ~0 if floor active)
    below = sum(1 for x in r if any(x.get(c,0) < -1.5 for c,_ in cols))
    print(f"{d}: n={n:3d}  factor-mins V/Q/G/M = "
          f"{mins['V']:+.2f}/{mins['Q']:+.2f}/{mins['G']:+.2f}/{mins['M']:+.2f}"
          f"  near_edge(<=-1.3)={near}  below-1.5={below}")
