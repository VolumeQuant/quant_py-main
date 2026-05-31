"""괴리율 평균회귀 검증 (오프라인, _cache/ohlcv_liquid).
가설: 시장가 < NAV (음의 괴리율 큼)인 ETF는 이후 가격이 NAV로 수렴 → 단기 초과수익?
역함정: 음의 괴리율은 해외기초/저유동에서 '못 따라잡는' 신호일 수도 → 데이터가 판정.
방법: 매일 각 ETF 괴리율 계산 → 괴리율 구간별 forward Kd '가격수익' 분포 (pooled).
실행: python etf_research/dev_reversion.py
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
C = Path(__file__).parent / '_cache'
K = 5  # forward 거래일
oh = pd.read_parquet(C/'ohlcv_liquid.parquet')
oh['etf'] = oh['etf'].astype(str)
close = oh.pivot_table(index='date', columns='etf', values='close').sort_index()
nav = oh.pivot_table(index='date', columns='etf', values='nav').sort_index()
dev = (close/nav - 1).where(nav>0)
fwd = close.shift(-K)/close - 1   # forward Kd 가격수익

# pooled long-form
d = dev.stack().rename('dev').to_frame()
d['fwd'] = fwd.stack()
d = d.dropna()
d = d[d['dev'].abs() < 0.5]  # 이상치 제거
print(f"관측 {len(d):,} (ETF×일), forward {K}d", flush=True)

bins = [(-1,-0.03,'≤ -3% (큰 음괴리)'), (-0.03,-0.01,'-3~-1%'), (-0.01,0.01,'±1% (정상)'),
        (0.01,0.03,'+1~3%'), (0.03,1,'≥ +3% (큰 양괴리)')]
print(f"\n=== 괴리율 구간별 forward {K}d 가격수익 ===", flush=True)
print(f"{'괴리율 구간':<18}{'관측수':>9}{'평균fwd':>9}{'중앙값':>8}{'승률':>7}", flush=True)
base = d['fwd'].mean()
for lo,hi,lbl in bins:
    s = d[(d.dev>lo)&(d.dev<=hi)]
    if len(s):
        print(f"{lbl:<18}{len(s):>9,}{s.fwd.mean()*100:>+8.2f}%{s.fwd.median()*100:>+7.2f}%{(s.fwd>0).mean()*100:>6.0f}%", flush=True)
print(f"\n전체 평균 forward {K}d: {base*100:+.2f}%", flush=True)
# 신호 강도: 큰 음괴리 - 큰 양괴리
neg = d[d.dev<=-0.03]['fwd'].mean(); pos = d[d.dev>=0.03]['fwd'].mean()
print(f"[신호] 큰음괴리 {neg*100:+.2f}% vs 큰양괴리 {pos*100:+.2f}% → 스프레드 {(neg-pos)*100:+.2f}%p", flush=True)
print("(양수 스프레드 = 음의괴리 매수가 유효. 단 저유동 함정 가능 → 거래대금 필터 후 재확인 권장)", flush=True)
