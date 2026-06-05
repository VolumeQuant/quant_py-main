# -*- coding: utf-8 -*-
# proposal 임계값 검증: 과거 거래일별 "오늘 가격바 존재 종목수" 분포
import sys, glob
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd, numpy as np

f = sorted(glob.glob('data_cache/all_ohlcv_*.parquet'))
f = [x for x in f if '_full' not in x]; f.sort(key=lambda p: p.split('_')[-1])
df = pd.read_parquet(f[-1]).replace(0, np.nan)

# last 40 trading days: per-day present count (전체 종목 중 그날 가격 있는 수)
present = df.notna().sum(axis=1)
tail = present.tail(40)
print("최근 40거래일 '가격바 존재 종목수' 분포:")
print(f"  min={tail.min()}  p5={tail.quantile(.05):.0f}  median={tail.median():.0f}  max={tail.max()}")
print(f"  마지막 5일:")
for d, v in tail.tail(5).items():
    print(f"    {pd.Timestamp(d).date()}: {int(v)}")
print(f"\n임계 2000 대비: 최근 40일 최소값 {tail.min()} → 마진 {tail.min()-2000} (양수면 정상일 절대 안 걸림)")
# 2026-05-28 yfinance 대량실패일 확인 (사고 표본)
for probe in ['20260528','20260529']:
    ts = pd.Timestamp(probe)
    if ts in present.index:
        print(f"  (참고) {probe} 수집사고 의심일 존재수: {int(present.loc[ts])}")
