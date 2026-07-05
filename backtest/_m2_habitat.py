# -*- coding: utf-8 -*-
"""EDA M2 — 시스템 서식지 변화: top20 시총/섹터/회전속도/보유상관 연도별 추이."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from collections import Counter

R = 'C:/dev/claude-code/quant_py-main'
files = sorted(glob.glob(R + '/state/ranking_*.json'))
files = [f for f in files if os.path.basename(f)[8:16].isdigit() and os.path.basename(f)[8:16] >= '20190102']

top20_by_day = {}
sector_by_day = {}
corr_by_day = {}
for f in files:
    dt = os.path.basename(f)[8:16]
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    rk = sorted(d.get('rankings', []), key=lambda x: x.get('composite_rank', 999))[:20]
    top20_by_day[dt] = [x['ticker'] for x in rk]
    sector_by_day[dt] = [x.get('sector', '기타') for x in rk]
    md = d.get('metadata') or {}
    c = md.get('correlation_60d')
    if c is not None:
        corr_by_day[dt] = c

days = sorted(top20_by_day)
print(f"일수: {len(days)}")

# ① top20 일일 교체율 (어제 대비 새 얼굴 수)
print("\n===== ① top20 일일 교체 속도 (연도별 평균, 종목/일) =====")
turn = {}
for i in range(1, len(days)):
    a, b = set(top20_by_day[days[i-1]]), set(top20_by_day[days[i]])
    turn[days[i]] = len(b - a)
ts = pd.Series(turn)
for y, g in ts.groupby(ts.index.str[:4]):
    print(f"  {y}: 하루 평균 {g.mean():.2f}종목 교체 (최대 {g.max()})")

# ② 섹터 구성 연도별
print("\n===== ② top20 섹터 구성 (연도별 비중 %) =====")
sec_yr = {}
for dt, secs in sector_by_day.items():
    y = dt[:4]
    sec_yr.setdefault(y, Counter()).update(secs)
all_secs = Counter()
for c in sec_yr.values(): all_secs.update(c)
top_secs = [s for s, _ in all_secs.most_common(6)]
print(f"{'년':6s}" + ''.join(f"{s[:5]:>8s}" for s in top_secs))
for y in sorted(sec_yr):
    tot = sum(sec_yr[y].values())
    print(f"{y:6s}" + ''.join(f"{sec_yr[y].get(s,0)/tot*100:>7.0f}%" for s in top_secs))

# ③ 보유 상관 (metadata correlation_60d = 페어별 dict) 연도별
print("\n===== ③ 상위종목 60일 페어상관 (연도별) =====")
cvals = {}
for dt, c in corr_by_day.items():
    if isinstance(c, dict) and c:
        v = [x for x in c.values() if isinstance(x, (int, float))]
        if v:
            cvals[dt] = np.mean(v)
cs = pd.Series(cvals, dtype=float)
if len(cs):
    for y, g in cs.groupby(cs.index.str[:4]):
        print(f"  {y}: 평균 {g.mean():.2f} / 최대 {g.max():.2f} (n={len(g)})")

# ④ top20 시총 분포 — 연말 스냅샷 (market_cap_ALL 파일)
print("\n===== ④ top20 시총 중앙값 (연도별 스냅샷) =====")
mc_files = sorted(glob.glob(R + '/data_cache/market_cap_ALL_*.parquet'))
mc_dates = [os.path.basename(f).split('_')[-1].replace('.parquet', '') for f in mc_files]
for y in ['2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026']:
    cand = [d for d in mc_dates if d.startswith(y)]
    if not cand: continue
    snap_d = cand[-1]
    rk_days = [d for d in days if d[:4] == y]
    if not rk_days: continue
    rk_d = min(rk_days, key=lambda x: abs(int(x) - int(snap_d)))
    try:
        mc = pd.read_parquet(R + f'/data_cache/market_cap_ALL_{snap_d}.parquet')
    except Exception:
        continue
    col = [c for c in mc.columns if '시가총액' in str(c) or 'cap' in str(c).lower()]
    if not col:
        col = [mc.columns[0]]
    idx = mc.index.astype(str).str.zfill(6)
    mc_map = dict(zip(idx, mc[col[0]]))
    caps = [mc_map.get(t) for t in top20_by_day[rk_d]]
    caps = [c/1e8 for c in caps if c and c == c]
    if caps:
        print(f"  {y} ({snap_d} 기준): 중앙 {np.median(caps):,.0f}억 / 최소 {min(caps):,.0f}억 / 최대 {max(caps)/1e4:,.1f}조 (n={len(caps)})")
