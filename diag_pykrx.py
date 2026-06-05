# -*- coding: utf-8 -*-
import os, sys, json
os.environ['PRODUCTION_MODE'] = '1'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backtest')
import pandas as pd, numpy as np
from fast_generate_rankings_v2 import preload_all_data, find_nearest_cache

pre = preload_all_data('20260401', '20260605', trading_dates=['20260605'], production_mode=True)
fp = pre['fundamentals_pykrx']
print("pykrx fundamentals cache dates available:", sorted(fp.keys())[-8:])

k05 = find_nearest_cache(fp, '20260605', 10)
k04 = find_nearest_cache(fp, '20260604', 10)
print(f"fund_key for 0605 -> {k05}   for 0604 -> {k04}")

f05 = fp[k05]
print(f"0605 fund rows={len(f05)} cols={list(f05.columns)}")
# global health: how many have EPS<=0 / PER>200 / all-zero
for kk, ff in [('0605', f05), ('0604', fp.get(k04))]:
    if ff is None: continue
    eps0 = (ff['EPS'].fillna(0) <= 0).sum() if 'EPS' in ff else None
    az = ((ff.get('PER',0).fillna(0)==0)&(ff.get('PBR',0).fillna(0)==0)&(ff.get('EPS',0).fillna(0)==0)&(ff.get('BPS',0).fillna(0)==0)).sum() if 'PER' in ff else None
    per200 = (ff['PER']>200).sum() if 'PER' in ff else None
    print(f"  {kk}({'same' if (kk=='0605' and k05==k04) else ''}): rows={len(ff)} EPS<=0={eps0} all-zero={az} PER>200={per200}")

r04 = {x['ticker']: x for x in json.load(open('state/ranking_20260604.json', encoding='utf-8'))['rankings']}
r05 = set(x['ticker'] for x in json.load(open('state/ranking_20260605.json', encoding='utf-8'))['rankings'])
dropped = sorted([(t, r04[t]['rank']) for t in r04 if t not in r05], key=lambda x: x[1])

print(f"\n{'tk':7}{'rk04':>5}  {'EPS':>9}{'BPS':>9}{'PER':>8}{'PBR':>7}  ROE     verdict")
for t, rk in dropped:
    row = f05.loc[t] if t in f05.index else None
    if row is None:
        print(f"{t:7}{rk:5}  NOT IN pykrx 0605 cache  -> all-zero/NO_FUND")
        continue
    eps, bps, per, pbr = row.get('EPS'), row.get('BPS'), row.get('PER'), row.get('PBR')
    roe = (eps/bps*100) if (bps and bps>0 and pd.notna(eps)) else np.nan
    v=[]
    if pd.notna(per) and per>200: v.append('PER>200')
    if pd.notna(roe) and roe<=0: v.append('ROE<=0')
    if (per or 0)<=0 and (pbr or 0)<=0 and (eps or 0)==0 and (bps or 0)==0: v.append('all-zero')
    print(f"{t:7}{rk:5}  {eps if pd.notna(eps) else 0:9.0f}{bps if pd.notna(bps) else 0:9.0f}{per if pd.notna(per) else 0:8.1f}{pbr if pd.notna(pbr) else 0:7.2f}  {roe:6.1f}  {','.join(v) or '??pass'}")
