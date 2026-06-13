# -*- coding: utf-8 -*-
"""EPS×Volume 융합 forward 추적기 (2026-06-13, path A).
매일 volume-top3 vs fused-top3 + 각 forward수익 기록 → research/eps_fusion_track.csv 누적.
60일+ 후 "융합 > 볼륨 단독" 여부 판정용. ★검증 전 실자본 X.

팩터: ntm_z = winsor(zscore(adj_score), ±2), num_analysts>=8만 신뢰(미만=0).
      fused = volume_score + W_EPS × ntm_z.
사용: python eps_fusion_tracker.py [backfill]
"""
import sqlite3, json, glob, os, sys, io
import pandas as pd, numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJ = r'C:\dev\claude-code\quant_py-main'
DB = os.path.join(PROJ, 'kr_eps_momentum', 'eps_momentum_data_kr.db')
OUT = os.path.join(PROJ, 'research', 'eps_fusion_track.csv')
W_EPS, MIN_AN, CLIP = 0.2, 8, 2.0

px = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*.parquet')),
                            key=lambda f: f.split('_')[-1])[-1]).replace(0, np.nan).sort_index()

def fwd(tickers, d, n):
    rs = []
    for t in tickers:
        if t not in px.columns: continue
        s = px[t].dropna(); ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        i = s.index.searchsorted(ts)
        if i >= len(s) or s.index[i] != ts or i+n >= len(s): continue
        seg = s.iloc[i:i+n+1]
        if (seg.pct_change().dropna().abs() > 0.35).any(): continue
        rs.append((s.iloc[i+n]/s.iloc[i]-1)*100)
    return np.mean(rs) if rs else None

def topk(df, col, k=3):
    return list(df.sort_values(col, ascending=False).head(k)['tk'])

def run_date(date):
    vf = os.path.join(PROJ, 'state', f'ranking_{date}.json')
    if not os.path.exists(vf): return None
    vol = pd.DataFrame([dict(tk=x['ticker'], name=x['name'], score=x['score'])
                        for x in json.load(open(vf, encoding='utf-8'))['rankings']])
    con = sqlite3.connect(DB)
    eps = pd.read_sql(f"SELECT ticker,adj_score,num_analysts,ntm_90d,ntm_60d,ntm_30d,ntm_7d,ntm_current FROM ntm_screening WHERE date='{date[:4]}-{date[4:6]}-{date[6:]}'", con)
    con.close()
    if len(eps) == 0: return None
    eps['tk'] = eps['ticker'].str.replace('.KS', '', regex=False).str.replace('.KQ', '', regex=False)
    ntm_cols = ['ntm_90d', 'ntm_60d', 'ntm_30d', 'ntm_7d', 'ntm_current']
    m = vol.merge(eps[['tk', 'adj_score', 'num_analysts'] + ntm_cols], on='tk', how='left')
    # 0 글리치 필터: NTM 스냅샷 중 0 있으면 revision 신뢰불가(SK 케이스) → 중립
    no_zero = (m[ntm_cols] > 0).all(axis=1)
    rel = m['adj_score'].notna() & (m['num_analysts'].fillna(0) >= MIN_AN) & no_zero
    if rel.sum() < 5: return None
    mu, sd = m.loc[rel, 'adj_score'].mean(), m.loc[rel, 'adj_score'].std()
    m['ntm_z'] = np.where(rel, np.clip((m['adj_score']-mu)/sd, -CLIP, CLIP), 0.0)
    m['fused'] = m['score'] + W_EPS * m['ntm_z']
    vt, ft = topk(m, 'score'), topk(m, 'fused')
    rec = dict(date=date, n_reliable=int(rel.sum()),
               vol_top3='|'.join(vt), fused_top3='|'.join(ft),
               same=(set(vt) == set(ft)))
    for n in (1, 3, 5):
        rec[f'vol_fwd{n}'] = fwd(vt, date, n)
        rec[f'fused_fwd{n}'] = fwd(ft, date, n)
    return rec

mode = sys.argv[1] if len(sys.argv) > 1 else 'today'
if mode == 'backfill':
    con = sqlite3.connect(DB)
    dates = [r[0].replace('-', '') for r in con.execute('SELECT DISTINCT date FROM ntm_screening ORDER BY date')]
    con.close()
else:
    dates = [max(r[0].replace('-', '') for r in sqlite3.connect(DB).execute('SELECT DISTINCT date FROM ntm_screening'))]

rows = [r for d in dates if (r := run_date(d))]
df = pd.DataFrame(rows)
# 누적: 기존 CSV에 append + date 중복제거 (overwrite 버그 수정 2026-06-13)
if os.path.exists(OUT) and len(df):
    old = pd.read_csv(OUT, dtype={'date': str})
    df['date'] = df['date'].astype(str)
    old = old[~old['date'].isin(df['date'])]
    df = pd.concat([old, df], ignore_index=True)
df = df.sort_values('date').reset_index(drop=True)
df.to_csv(OUT, index=False)
print(f'[저장] {OUT} ({len(df)}일 누적)')
print(df[['date', 'n_reliable', 'same', 'vol_fwd3', 'fused_fwd3']].to_string(index=False))
valid = df.dropna(subset=['vol_fwd3', 'fused_fwd3'])
if len(valid):
    print(f"\n[누적 비교, {len(valid)}일 (8일=노이즈, 인프라 시드용)]")
    print(f"  볼륨 top3 fwd3 평균: {valid['vol_fwd3'].mean():+.2f}%")
    print(f"  융합 top3 fwd3 평균: {valid['fused_fwd3'].mean():+.2f}%")
    print(f"  top3 동일한 날: {df['same'].sum()}/{len(df)} (다른 날만 융합효과 발생)")
