# -*- coding: utf-8 -*-
import os, sys
os.environ['PRODUCTION_MODE'] = '1'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backtest')
import pandas as pd
from fast_generate_rankings_v2 import preload_all_data, find_nearest_cache

date = '20260605'
base_ts = pd.Timestamp(date)
pre = preload_all_data('20260401', '20260605', trading_dates=[date], production_mode=True)

mkey = find_nearest_cache(pre['market_cap'], date, 10)
mcap = pre['market_cap'][mkey]
vkey = find_nearest_cache(pre['avg_volume'], date, 10)
avgv = pre['avg_volume'][vkey] if vkey else None
ttm = pre['ttm_lookup'].get(date, {})
fs = pre.get('fs', {})

# stocks that were rank<=100 on 0604 but dropped on 0605
import json
r04 = {x['ticker']: x for x in json.load(open('state/ranking_20260604.json', encoding='utf-8'))['rankings']}
r05 = set(x['ticker'] for x in json.load(open('state/ranking_20260605.json', encoding='utf-8'))['rankings'])
dropped = [(t, r04[t]['rank']) for t in r04 if t not in r05]
dropped.sort(key=lambda x: x[1])

print(f"market_cap stocks: {len(mcap)}  avg_volume key={vkey}")
print(f"{'tk':7} {'rank04':>6} {'cap억':>8} {'avg_tv':>7} {'q_PIT':>5} {'in_ttm':>6}  gate")
for t, rk in dropped:
    cap = mcap.loc[t, '시가총액']/1e8 if t in mcap.index else None
    tv = float(avgv.get(t)) if (avgv is not None and t in avgv.index) else None
    qn = None
    fdf = fs.get(t)
    if fdf is not None and not fdf.empty and '공시구분' in fdf.columns:
        q = fdf[fdf['공시구분'] == 'q']
        if 'rcept_dt' in q.columns:
            qa = q[q['rcept_dt'].notna() & (q['rcept_dt'] <= base_ts)]
            qn = qa['기준일'].nunique()
    in_ttm = t in ttm
    # diagnose gate
    gate = []
    if cap is None: gate.append('NO_MCAP')
    elif cap < 1000: gate.append(f'CAP<1000')
    if tv is not None:
        thr = 50 if (cap or 0) >= 10000 else 20
        if tv < thr: gate.append(f'TV<{thr}')
    if not in_ttm: gate.append('NO_FUND')
    if qn is not None and qn < 8: gate.append(f'q={qn}<8')
    caps = f"{cap:8.0f}" if cap is not None else "    None"
    tvs = f"{tv:7.1f}" if tv is not None else "   None"
    print(f"{t:7} {rk:6} {caps} {tvs} {str(qn):>5} {str(in_ttm):>6}  {','.join(gate) or 'PASS-all-hard?'}")
