# -*- coding: utf-8 -*-
import os, sys, json
os.environ['PRODUCTION_MODE'] = '1'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backtest')
import pandas as pd
from fast_generate_rankings_v2 import preload_all_data, find_nearest_cache, vectorized_ma120_filter

date = '20260605'
base_ts = pd.Timestamp(date)
pre = preload_all_data('20260401', '20260605', trading_dates=[date], production_mode=True)

ni_yearly = pre.get('ni_yearly', {})
ar_yearly = pre.get('asset_rev_yearly', {})

# chronic set (PIT)
chronic = set()
for tk, hist in ni_yearly.items():
    avail = [(d, v) for d, rcpt, v in hist if rcpt is not None and rcpt <= base_ts]
    if len(avail) >= 3 and all(v < 0 for _, v in avail[-3:]):
        chronic.add(tk)
# asset dilution set (PIT)
asset_dil = set()
for tk, h in ar_yearly.items():
    a = [(d, v) for d, rc, v in h['assets'] if rc is not None and rc <= base_ts]
    r = [(d, v) for d, rc, v in h['revenue'] if rc is not None and rc <= base_ts]
    if len(a) >= 2 and len(r) >= 2 and a[-2][1] > 0 and r[-2][1] > 0:
        ag = (a[-1][1]/a[-2][1]-1)*100; rg = (r[-1][1]/r[-2][1]-1)*100
        if ag > 100 and rg < ag*0.5: asset_dil.add(tk)

# MA120
ohlcv = pre['ohlcv']
mkey = find_nearest_cache(pre['market_cap'], date, 10)
mcap = pre['market_cap'][mkey]
cols = [c for c in ohlcv.columns if c in set(mcap.index)]
price_df = ohlcv.loc[ohlcv.index <= base_ts, cols]

r04 = {x['ticker']: x for x in json.load(open('state/ranking_20260604.json', encoding='utf-8'))['rankings']}
r05 = set(x['ticker'] for x in json.load(open('state/ranking_20260605.json', encoding='utf-8'))['rankings'])
dropped = sorted([t for t in r04 if t not in r05], key=lambda t: r04[t]['rank'])

ma_pass, ma_fail = vectorized_ma120_filter(price_df, dropped, base_ts)
ma_fail = set(ma_fail)

print(f"chronic-3yr total={len(chronic)}  asset_dil total={len(asset_dil)}")
print(f"{'tk':7}{'rk04':>5}  chronic asset MA120fail  -> gate")
for t in dropped:
    g = []
    if t in chronic: g.append('CHRONIC')
    if t in asset_dil: g.append('ASSET_DIL')
    if t in ma_fail: g.append('MA120')
    print(f"{t:7}{r04[t]['rank']:5}  {str(t in chronic):>7} {str(t in asset_dil):>5} {str(t in ma_fail):>9}  -> {','.join(g) or '???none'}")
