"""EDA2: price_stored vs all_ohlcv close 일치 확인 + per-block 경계 + EPS_pit 안정성."""
import json, glob, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

# all_ohlcv 로드
import os
cand = sorted(glob.glob('data_cache/all_ohlcv_2017*_*.parquet'))
ohlcv_path = cand[-1]
print('ohlcv:', ohlcv_path)
ohlcv = pd.read_parquet(ohlcv_path)
print('ohlcv shape:', ohlcv.shape, '| cols sample:', list(ohlcv.columns[:6]))
print('ohlcv index name:', ohlcv.index.name, '| dtype:', ohlcv.index.dtype)
print('ohlcv index head:', list(ohlcv.index[:3]), '... tail:', list(ohlcv.index[-3:]))

# 1) price_stored vs ohlcv close 일치 (삼성 005930)
files = sorted(glob.glob('state/ranking_2024*.json'))[80:100]
print('\n=== price_stored vs ohlcv close (005930) ===')
for f in files[:10]:
    date = f.split('_')[-1].replace('.json','')
    d = json.load(open(f, encoding='utf-8'))
    items = d if isinstance(d, list) else d.get('rankings', [])
    it = next((x for x in items if x['ticker']=='005930'), None)
    if not it: continue
    # ohlcv close
    close = None
    dt = pd.Timestamp(date)
    if '005930' in ohlcv.columns:
        try: close = ohlcv.loc[dt, '005930']
        except Exception: pass
    print(f'  {date}: stored_price={it.get("price")}, ohlcv_close={close}, per={it.get("per")}')

# 2) per-block: 전체 2018~2026 한 종목 per 변화 시점 + EPS_pit = price/per 안정성
print('\n=== per-block 구조 (005930, 전 기간) ===')
allf = sorted(glob.glob('state/ranking_*.json'))
print('total ranking files:', len(allf))
prev_per = None
blocks = []
for f in allf[::1]:
    date = f.split('_')[-1].replace('.json','')
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception: continue
    items = d if isinstance(d, list) else d.get('rankings', [])
    it = next((x for x in items if x['ticker']=='005930'), None)
    if not it or it.get('per') is None: continue
    per = it.get('per'); price = it.get('price')
    eps_implied = price/per if per else None
    if per != prev_per:
        blocks.append((date, per, price, eps_implied))
        prev_per = per
print('n per-change events (005930):', len(blocks))
for b in blocks[:25]:
    print(f'  {b[0]}: per={b[1]}, price@change={b[2]}, EPS_implied(price/per)={b[3]:.0f}' if b[3] else f'  {b[0]}: per={b[1]}')
