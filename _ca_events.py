# -*- coding: utf-8 -*-
"""raw vs 수정주가 ratio 점프에서 CA 이벤트(종목,날짜,방향) 추출 → 명시 페널티 팩터용.
방향: down=무상증자/분할/유상권리락, up=병합."""
import sys, io, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
raw = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*_2026061*.parquet'))[-1]).replace(0, np.nan)
adj = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/adjusted_close_*.parquet'))[-1])
THR = 0.02
events = []  # (ticker, date_str, direction)
for tk in adj.columns:
    if tk not in raw.columns:
        continue
    df = pd.DataFrame({'raw': raw[tk], 'adj': adj[tk].reindex(raw.index)}).dropna()
    if len(df) < 2:
        continue
    dlog = np.log(df['adj'] / df['raw']).diff()
    for d, dl in dlog.items():
        if np.isfinite(dl) and abs(dl) >= THR:
            events.append((tk, d.strftime('%Y%m%d'), 'down' if dl > 0 else 'up'))
out = {'events': events}
json.dump(out, open('C:/dev/data_cache/ca_events.json', 'w'), ensure_ascii=False)
dn = sum(1 for e in events if e[2] == 'down'); up = sum(1 for e in events if e[2] == 'up')
print(f"CA 이벤트 {len(events)}건 (down 무상증자/분할 {dn}, up 병합 {up}) → ca_events.json")
print(f"종목수: {len(set(e[0] for e in events))}")
# 연도별 분포
yr = {}
for tk, d, di in events:
    yr[d[:4]] = yr.get(d[:4], 0) + 1
print("연도별:", {k: yr[k] for k in sorted(yr)})
