# -*- coding: utf-8 -*-
import os, sys, json
os.environ['PRODUCTION_MODE'] = '1'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backtest')
import pandas as pd
from collections import Counter
from fast_generate_rankings_v2 import preload_all_data, find_nearest_cache, ttm_lookup_to_dataframe, calculate_multifactor_fast

date = '20260605'
base_ts = pd.Timestamp(date)
pre = preload_all_data('20260401', '20260605', trading_dates=[date], production_mode=True)

# replicate minimal: build universe like generate_ranking_for_date does, then score
# easier: just reuse generate to get the scored frame BEFORE (e). We re-run scoring inline.
# Use the same universe filter shortcut: take all stocks in ttm_lookup for date.
ttm = pre['ttm_lookup'].get(date, {})
universe = list(ttm.keys())
magic = ttm_lookup_to_dataframe(ttm, universe)

# attach mcap + name
mkey = find_nearest_cache(pre['market_cap'], date, 10)
mcap = pre['market_cap'][mkey]
magic = magic.merge(mcap[['시가총액']], left_on='종목코드', right_index=True, how='left')
magic = magic[magic.get('자본', 1) > 0].copy() if '자본' in magic.columns else magic

# pykrx merge
fkey = find_nearest_cache(pre['fundamentals_pykrx'], date, 10)
fdf = pre['fundamentals_pykrx'][fkey]
for col, nc in [('PER','pykrx_PER'),('PBR','pykrx_PBR'),('EPS','pykrx_EPS'),('BPS','pykrx_BPS')]:
    if col in fdf.columns:
        magic[nc] = magic['종목코드'].map(fdf[col].to_dict())

# build price_df
ohlcv = pre['ohlcv']
mcap_tickers = set(mcap.index)
cols = [c for c in ohlcv.columns if c in mcap_tickers]
price_df = ohlcv.loc[ohlcv.index <= base_ts, cols]

# sector
skey = find_nearest_cache(pre['sectors'], date)
sec_df = pd.read_parquet(pre['sectors'][skey])
sm = {r[sec_df.columns[0]]: str(r[sec_df.columns[1]]) for _, r in sec_df.iterrows()}

scored = calculate_multifactor_fast(magic, price_df, sm, date, pre['growth_lookup'], '12m')

g_sub = ['매출성장률_z','이익변화량_z','매출가속도_z','매출총이익성장_z','영업이익률변화_z','현금흐름성장_z']
existing = [c for c in g_sub if c in scored.columns]
def capped(row):
    vals = [row[c] for c in existing if pd.notna(row[c])]
    if len(vals) < 5: return (False, None)
    mc = Counter(vals).most_common(1)[0]
    return (mc[1] >= 5 and abs(mc[0]) > 1.5, mc)

n_capped = 0
sc = scored.set_index('종목코드')
for t in sc.index:
    c, mc = capped(sc.loc[t])
    if c: n_capped += 1
print(f"scored(after hard gates, before (e)): {len(scored)}")
print(f"(e) capped removes: {n_capped}")

# check dropped stocks
r04 = {x['ticker']: x for x in json.load(open('state/ranking_20260604.json', encoding='utf-8'))['rankings']}
r05 = set(x['ticker'] for x in json.load(open('state/ranking_20260605.json', encoding='utf-8'))['rankings'])
dropped = sorted([(t, r04[t]['rank']) for t in r04 if t not in r05], key=lambda x: x[1])
print(f"\n{'tk':7}{'rk04':>5}  capped?  most_common(val,count)   g-subfactors")
for t, rk in dropped:
    if t not in sc.index:
        print(f"{t:7}{rk:5}  NOT-SCORED"); continue
    row = sc.loc[t]
    c, mc = capped(row)
    gv = {col.replace('_z',''): (round(row[col],2) if pd.notna(row[col]) else None) for col in existing}
    print(f"{t:7}{rk:5}  {str(c):>6}  {str(mc):>22}  {gv}")
