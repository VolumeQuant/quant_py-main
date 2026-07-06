# -*- coding: utf-8 -*-
"""US VM top4 핸드오프 Phase B — KR 실측 컨센 미니 리플레이 (6/1~7/6, 일화 수준 n).
ntm_screening(실측 rev30/ntm_current) 기반: fwd_PER 게이트 → rev30 상위 top4 동일가중, 5거래일 재선발.
※ 6월 = -15.6% 조정장 1개 에피소드. 성과 절대값 무의미, 게이트/정렬축 상대 방향만 참고."""
import sqlite3, glob, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT = 'C:/dev'
px = pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
px = px[px.notna().any(axis=1)]
pcol = {c: i for i, c in enumerate(px.columns)}; parr = px.values
tdays = [d.strftime('%Y%m%d') for d in px.index]; tdi = {d: i for i, d in enumerate(tdays)}
c = sqlite3.connect(ROOT+'/kr_eps_momentum/eps_momentum_data_kr.db')
ns = pd.read_sql("SELECT date,ticker,ntm_current,ntm_30d FROM ntm_screening", c)
ns['tk'] = ns['ticker'].str[:6]; ns['d8'] = ns['date'].str.replace('-', '')
snap_dates = sorted(ns['d8'].unique())

def replay(fpe_max, sort, N=4, R=5):
    rebal = snap_dates[::R] if R else snap_dates[:1]
    held = []; daily = []
    i_start = tdi[snap_dates[0]]; i_last = len(tdays)-1
    ri = 0
    for i in range(i_start, i_last+1):
        d = tdays[i]
        if held:
            vs = [parr[i, pcol[t]]/parr[i-1, pcol[t]]-1 for t in held
                  if t in pcol and parr[i-1, pcol[t]] > 0 and parr[i, pcol[t]] > 0]
            daily.append(np.mean(vs) if vs else 0.0)
        else:
            daily.append(0.0)
        if ri < len(rebal) and d == rebal[ri]:
            g = ns[ns['d8'] == d]
            pool = []
            for _, r in g.iterrows():
                if not r['ntm_current'] or r['ntm_current'] <= 0: continue
                t = r['tk']
                if t not in pcol or not (parr[i, pcol[t]] > 0): continue
                fpe = parr[i, pcol[t]]/r['ntm_current']
                if fpe_max and not (0 < fpe < fpe_max): continue
                rev = r['ntm_current']/r['ntm_30d']-1 if (r['ntm_30d'] and r['ntm_30d'] > 0) else np.nan
                v = -fpe if sort == 'level' else rev
                if not np.isnan(v): pool.append((v, t))
            pool.sort(reverse=True)
            held = [t for _, t in pool[:N]]
            ri += 1
    a = np.array(daily); eq = np.cumprod(1+a)
    peak = np.maximum.accumulate(eq); mdd = ((eq-peak)/peak).min()*100
    return (eq[-1]-1)*100, mdd

kospi = pd.read_parquet(ROOT+'/data_cache/kospi_yf.parquet').iloc[:, 0]
k0 = kospi[kospi.index >= '2026-06-01']
print(f"[실측 미니 리플레이 {snap_dates[0]}~{tdays[-1]} — 누적% / MDD%]  (코스피 동구간 {(k0.iloc[-1]/k0.iloc[0]-1)*100:+.1f}%)")
print("  ※ 1개월·조정장 1에피소드 = 일화. 방향만.")
for nm, fpe, sort in [("게이트無 + rev30", None, 'rev'), ("fwdPER<20 + rev30", 20, 'rev'),
                      ("fwdPER<25 + rev30", 25, 'rev'), ("fwdPER<20 + 레벨정렬", 20, 'level'),
                      ("게이트無 + 레벨정렬", None, 'level')]:
    r, m = replay(fpe, sort)
    print(f"  {nm:<24} {r:+6.1f}% / MDD {m:5.1f}%")
