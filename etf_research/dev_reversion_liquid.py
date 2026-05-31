"""괴리율 평균회귀 — 거래대금 필터 재검증 (저유동 함정 배제).
dev_reversion이 음괴리 fwd5d +3.46%(승률73%) 보였으나 저유동 가능 → 일별 거래대금 임계로 거른 뒤에도 유지되나?
실행: python etf_research/dev_reversion_liquid.py
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
C = Path(__file__).parent / '_cache'
K = 5
oh = pd.read_parquet(C/'ohlcv_liquid.parquet'); oh['etf']=oh['etf'].astype(str)
close = oh.pivot_table(index='date', columns='etf', values='close').sort_index()
nav = oh.pivot_table(index='date', columns='etf', values='nav').sort_index()
val = oh.pivot_table(index='date', columns='etf', values='value').sort_index()
dev = (close/nav-1).where(nav>0)
fwd = close.shift(-K)/close - 1

d = dev.stack().rename('dev').to_frame()
d['fwd'] = fwd.stack(); d['val'] = val.stack()
d = d.dropna(); d = d[d['dev'].abs()<0.5]

for thr_label, thr in [('전체', 0), ('거래대금≥5억', 5e8), ('거래대금≥20억', 2e9), ('거래대금≥50억', 5e9)]:
    s = d[d['val']>=thr]
    neg = s[s.dev<=-0.03]; pos = s[s.dev>=0.03]; norm = s[s.dev.abs()<0.01]
    if len(neg)<10:
        print(f"\n[{thr_label}] 음괴리 표본 {len(neg)} (부족)", flush=True); continue
    sprd = neg.fwd.mean()-pos.fwd.mean()
    print(f"\n[{thr_label}] 관측 {len(s):,}", flush=True)
    print(f"  ≤-3%(음괴리) {len(neg):>5}건 fwd {neg.fwd.mean()*100:+.2f}% 승률 {(neg.fwd>0).mean()*100:.0f}%"
          f" | 정상 {norm.fwd.mean()*100:+.2f}% | ≥+3% {pos.fwd.mean()*100:+.2f}% | 스프레드 {sprd*100:+.2f}%p", flush=True)
print("\n판정: 거래대금 올려도 음괴리 스프레드 양수 유지 = 진짜 edge. 사라지면 저유동 함정.", flush=True)
