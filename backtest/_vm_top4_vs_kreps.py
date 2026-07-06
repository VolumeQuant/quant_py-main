# -*- coding: utf-8 -*-
"""VM-top4 vs KR EPS 페이퍼 시스템 vs production — 동일 하니스·동일 기간(6/1~7/6) 실측 리플레이.
KR EPS = ntm_screening composite_rank(자체 순위) top2(US구조 2슬롯)/top4. 전부 5거래일 재선발(공정)."""
import sqlite3, glob, json, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT = 'C:/dev'
px = pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
px = px[px.notna().any(axis=1)]
pcol = {c: i for i, c in enumerate(px.columns)}; parr = px.values
tdays = [d.strftime('%Y%m%d') for d in px.index]; tdi = {d: i for i, d in enumerate(tdays)}
c = sqlite3.connect(ROOT+'/kr_eps_momentum/eps_momentum_data_kr.db')
ns = pd.read_sql("SELECT date,ticker,composite_rank,ntm_current,ntm_30d FROM ntm_screening", c)
ns['tk'] = ns['ticker'].str[:6]; ns['d8'] = ns['date'].str.replace('-', '')
snap_dates = sorted(ns['d8'].unique())
# production picks (state ranking)
prod = {}
for f in sorted(glob.glob(ROOT+'/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if dt >= snap_dates[0] and dt.isdigit():
        try: prod[dt] = [x['ticker'] for x in sorted(json.load(open(f, encoding='utf-8'))['rankings'], key=lambda z: z.get('rank', 99))[:3]]
        except Exception: pass

def replay(pick_fn, R=5):
    rebal = snap_dates[::R]
    held = []; daily = []
    i0, i1 = tdi[snap_dates[0]], len(tdays)-1
    ri = 0
    for i in range(i0, i1+1):
        d = tdays[i]
        if held:
            vs = [parr[i, pcol[t]]/parr[i-1, pcol[t]]-1 for t in held
                  if t in pcol and parr[i-1, pcol[t]] > 0 and parr[i, pcol[t]] > 0]
            daily.append(np.mean(vs) if vs else 0.0)
        else: daily.append(0.0)
        if ri < len(rebal) and d == rebal[ri]:
            held = pick_fn(d, i); ri += 1
    a = np.array(daily); eq = np.cumprod(1+a)
    peak = np.maximum.accumulate(eq); mdd = ((eq-peak)/peak).min()*100
    return (eq[-1]-1)*100, mdd

def eps_top(n):
    def f(d, i):
        g = ns[(ns['d8'] == d) & ns['composite_rank'].notna()].sort_values('composite_rank')
        return [t for t in g['tk'].head(n) if t in pcol]
    return f

def vm(fpe_max, sort, n=4):
    def f(d, i):
        g = ns[ns['d8'] == d]; pool = []
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
        return [t for _, t in pool[:n]]
    return f

def prod_top3(d, i):
    dd = max((k for k in prod if k <= d), default=None)
    return prod.get(dd, []) if dd else []

kospi = pd.read_parquet(ROOT+'/data_cache/kospi_yf.parquet').iloc[:, 0]
k0 = kospi[kospi.index >= '2026-06-01']
print(f"[동일 하니스 실측 리플레이 {snap_dates[0]}~{tdays[-1]}, 5거래일 재선발]  코스피 {(k0.iloc[-1]/k0.iloc[0]-1)*100:+.1f}%")
for nm, fn in [("KR EPS 시스템 top2 (자체 composite_rank)", eps_top(2)),
               ("KR EPS 시스템 top4", eps_top(4)),
               ("VM-top4: fwdPER<20 + rev30", vm(20, 'rev')),
               ("VM-top4: fwdPER<20 + 레벨", vm(20, 'level')),
               ("production top3 (실제 신호)", prod_top3)]:
    r, m = replay(fn)
    print(f"  {nm:<38} {r:+7.1f}% / MDD {m:5.1f}%")
