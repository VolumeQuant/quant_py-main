# -*- coding: utf-8 -*-
import os, sys, glob
os.environ['PRODUCTION_MODE'] = '1'
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backtest')
import pandas as pd, numpy as np

# load latest ohlcv
f = sorted(glob.glob('data_cache/all_ohlcv_*.parquet'))
f = [x for x in f if '_full' not in x]
f.sort(key=lambda p: p.split('_')[-1])
path = f[-1]
print("OHLCV:", path)
df = pd.read_parquet(path)
df = df.replace(0, np.nan)
print("date range:", df.index.min(), "->", df.index.max(), " ndates=", len(df))

# last 8 dates
tail_dates = df.index[-8:]
for t in ['187870','033240','103590','092870']:
    if t not in df.columns:
        print(t, "NOT in ohlcv"); continue
    s = df[t]
    last120 = s.iloc[-120:]
    ma = last120.mean()
    cur = last120.iloc[-1]
    print(f"\n{t}: MA120={ma:.0f} current={cur:.0f} ratio={cur/ma:.3f}  pass={cur>=ma}")
    print("  last8 close:", [None if pd.isna(v) else round(v) for v in s.loc[tail_dates].values])

# universe-wide MA120 pass-rate: 0604 vs 0605
print("\n=== universe-wide MA120 pass (all ohlcv cols with >=126 history) ===")
for d in ['20260604','20260605']:
    ts = pd.Timestamp(d)
    sl = df.loc[df.index <= ts]
    if len(sl) < 120:
        print(d, "insufficient"); continue
    last120 = sl.iloc[-120:]
    cur = last120.iloc[-1]
    ma = last120.mean()
    hist = sl.notna().sum()
    ok_hist = hist >= 126
    cur_notna = cur.notna()
    passed = ((cur >= ma) & ok_hist & cur_notna)
    # restrict to stocks with data today
    universe_today = cur_notna & ok_hist
    n_uni = universe_today.sum()
    n_pass = passed.sum()
    # how many have today's bar missing among those with history
    miss_today = (ok_hist & ~cur_notna).sum()
    print(f"{d}: last_bar_date={sl.index[-1].date()} | hist>=126={ok_hist.sum()} | today_price_present={n_uni} | MA120_pass={n_pass} ({100*n_pass/max(n_uni,1):.1f}%) | missing_today_bar(among hist)={miss_today}")
