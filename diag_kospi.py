# -*- coding: utf-8 -*-
import sys, glob
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
k = pd.read_parquet('data_cache/kospi_yf.parquet')
print("cols:", list(k.columns), " shape:", k.shape)
s = k['close'] if 'close' in k.columns else k.iloc[:,0]
print("range:", s.index.min(), "->", s.index.max())
print("last 12:")
for d, v in s.tail(12).items():
    print(f"  {pd.Timestamp(d).date()}  {v:,.1f}")
ma20 = s.rolling(20).mean().iloc[-1]
ma80 = s.rolling(80).mean().iloc[-1]
ma120 = s.rolling(120).mean().iloc[-1]
print(f"\nlast={s.iloc[-1]:,.1f}  MA20={ma20:,.1f}  MA80={ma80:,.1f}  MA120={ma120:,.1f}")
print(f"20d return: {(s.iloc[-1]/s.iloc[-21]-1)*100:+.1f}%")
print(f"60d return: {(s.iloc[-1]/s.iloc[-61]-1)*100:+.1f}%")
print(f"1y ago: {s.iloc[-252]:,.1f}  ytd-ish 120d ago: {s.iloc[-121]:,.1f}")
# any single-day jumps >15%?
ret = s.pct_change()
big = ret[ret.abs() > 0.15]
print(f"\nsingle-day moves >15%: {len(big)}")
for d, v in big.tail(8).items():
    print(f"  {pd.Timestamp(d).date()}  {v*100:+.1f}%  -> {s.loc[d]:,.1f}")
