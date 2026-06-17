# -*- coding: utf-8 -*-
"""raw all_ohlcv에 flagged 종목만 KRX 수정주가로 교체 → 정본 adjusted 가격파일.
나머지 종목은 CA 없어 raw=수정주가 그대로. _backadjust_corpaction(자작) 대체.
출력: data_cache/all_ohlcv_adj_<range>.parquet"""
import sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd

raw_f = sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*_2026061*.parquet'))[-1]
adj_f = sorted(glob.glob('C:/dev/data_cache/adjusted_close_*.parquet'))[-1]
px = pd.read_parquet(raw_f).replace(0, np.nan)
adj = pd.read_parquet(adj_f)
print(f"raw: {os.path.basename(raw_f)} {px.shape}")
print(f"adj: {os.path.basename(adj_f)} {adj.shape}")

out = px.copy()
n_patched = 0
for tk in adj.columns:
    if tk in out.columns:
        # all_ohlcv 인덱스에 정렬 (수정주가 종가로 교체)
        s = adj[tk].reindex(out.index)
        # 수정주가가 비어있는 구간(상장 전 등)은 raw 유지 fallback
        out[tk] = s.where(s.notna(), out[tk])
        n_patched += 1
print(f"패치 완료: {n_patched}종목 수정주가 교체, 나머지 {out.shape[1]-n_patched} raw 유지")

base = os.path.basename(raw_f).replace('all_ohlcv_', 'all_ohlcv_adj_')
outpath = f'C:/dev/data_cache/{base}'
out.to_parquet(outpath)
print(f"[저장] {outpath} {out.shape}")

# 검증: 디바이스(187870) 무상증자 4/28, 와이지원(019210)
for tk, nm in [('187870', '디바이스'), ('019210', '와이지원')]:
    if tk not in out.columns:
        print(f"  {nm}({tk}): all_ohlcv에 없음"); continue
    print(f"\n{nm}({tk}) 4/20~4/30 종가 (raw → 수정주가):")
    for d in pd.date_range('2026-04-20', '2026-04-30'):
        if d in px.index:
            r = px.loc[d, tk]; a = out.loc[d, tk]
            if pd.notna(r):
                tag = ' ★교체' if abs((a or 0) - (r or 0)) > 1 else ''
                print(f"  {d.date()}  raw {r:>10,.0f} → adj {a:>10,.0f}{tag}")
