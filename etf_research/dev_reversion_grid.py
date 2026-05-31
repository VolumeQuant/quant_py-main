"""괴리율 반전 sweet-spot — 임계값 × 보유기간 그리드 (다국면 2021~2026, _cache/ohlcv_hist).
유일한 robust edge를 실사용 스펙으로 정밀화. 거래대금≥20억.
실행: python etf_research/dev_reversion_grid.py
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
C = Path(__file__).parent / '_cache'
oh = pd.read_parquet(C/'ohlcv_hist.parquet'); oh['etf']=oh['etf'].astype(str)
close = oh.pivot_table(index='date', columns='etf', values='close').sort_index()
nav = oh.pivot_table(index='date', columns='etf', values='nav').sort_index()
val = oh.pivot_table(index='date', columns='etf', values='value').sort_index()
dev = (close/nav-1).where(nav>0)
THR = [-0.02,-0.03,-0.04,-0.05]; HOLD = [3,5,10,20]
print("괴리율 반전 sweet-spot (거래대금≥20억, 2021~2026 전체)", flush=True)
print("각 셀 = 음괴리 평균fwd / 정상대비 스프레드 / 승률 / 건수", flush=True)
hdr = f"{'임계/보유':<9}" + "".join(f"{str(h)+'d':>22}" for h in HOLD)
print(hdr, flush=True)
for thr in THR:
    row = f"{thr*100:>4.0f}%   "
    for h in HOLD:
        fwd = close.shift(-h)/close - 1
        d = dev.stack().rename('dev').to_frame(); d['fwd']=fwd.stack(); d['val']=val.stack()
        d = d.dropna(); d = d[(d.dev.abs()<0.5)&(d.val>=2e9)]
        neg = d[d.dev<=thr]; norm = d[d.dev.abs()<0.01]
        if len(neg) < 10:
            row += f"{'n='+str(len(neg)):>22}"; continue
        sp = (neg.fwd.mean()-norm.fwd.mean())*100; wr = (neg.fwd>0).mean()*100
        cell = f"{neg.fwd.mean()*100:+.2f}/{sp:+.2f}p/{wr:.0f}%/{len(neg)}"
        row += f"{cell:>22}"
    print(row, flush=True)
print("\n각 셀: 음괴리평균fwd / 정상대비스프레드 / 승률. 스프레드·승률 동시 최대 = 실사용 sweet-spot.", flush=True)
