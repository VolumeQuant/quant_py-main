"""괴리율 평균회귀 — 연도별(다국면) 재검증. _cache/ohlcv_hist.parquet(2021~) 사용.
실행: python etf_research/dev_reversion_hist.py
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
C = Path(__file__).parent / '_cache'
K = 5
oh = pd.read_parquet(C/'ohlcv_hist.parquet'); oh['etf']=oh['etf'].astype(str)
close = oh.pivot_table(index='date', columns='etf', values='close').sort_index()
nav = oh.pivot_table(index='date', columns='etf', values='nav').sort_index()
val = oh.pivot_table(index='date', columns='etf', values='value').sort_index()
dev = (close/nav-1).where(nav>0); fwd = close.shift(-K)/close-1
d = dev.stack().rename('dev').to_frame(); d['fwd']=fwd.stack(); d['val']=val.stack()
d=d.dropna(); d=d[d.dev.abs()<0.5]; d=d[d.val>=2e9]  # 거래대금 20억+ (함정 배제)
d['year']=d.index.get_level_values('date').str[:4]
print(f"거래대금≥20억, forward {K}d, 연도별 음괴리(≤-3%) 반전", flush=True)
print(f"{'연도':<6}{'관측':>8}{'음괴리건':>8}{'음괴리fwd':>10}{'정상fwd':>9}{'스프레드':>9}{'승률':>7}", flush=True)
for y in sorted(d.year.unique()):
    s=d[d.year==y]; neg=s[s.dev<=-0.03]; norm=s[s.dev.abs()<0.01]
    if len(neg)<5: 
        print(f"{y:<6}{len(s):>8,}{len(neg):>8}  (표본부족)", flush=True); continue
    sp=neg.fwd.mean()-norm.fwd.mean()
    print(f"{y:<6}{len(s):>8,}{len(neg):>8}{neg.fwd.mean()*100:>+9.2f}%{norm.fwd.mean()*100:>+8.2f}%{sp*100:>+8.2f}%p{(neg.fwd>0).mean()*100:>6.0f}%", flush=True)
print("\n판정: 매 연도(강세/약세/횡보) 스프레드 양수 유지 = robust edge. 특정 해만이면 국면의존.", flush=True)
