# -*- coding: utf-8 -*-
"""US VM top4 핸드오프 Phase A — KR 실측 컨센 리비전/레벨 IC (가용 전 소스).
소스: ①ntm_screening(6/1~, rev7/rev30 자체보유) ②fnguide_consensus_history(6/10·6/19·6/29 스냅샷)
③fusion_consensus_cache(6/25~7/6 일별). 전부 실측(look-ahead 없음), 단 창 짧음(최대 23td)."""
import sqlite3, glob, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT = 'C:/dev'
px = pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
px = px[px.notna().any(axis=1)]  # 캘린더 인덱스 → 영업일만
pcol = {c: i for i, c in enumerate(px.columns)}; parr = px.values
tdays = [d.strftime('%Y%m%d') for d in px.index]; tdi = {d: i for i, d in enumerate(tdays)}
LAST = tdays[-1]

def pr(t, d8):
    if t not in pcol or d8 not in tdi: return None
    v = parr[tdi[d8], pcol[t]]
    return float(v) if v > 0 else None

def fwd_ret(t, d8, h=None):
    """d8 종가 → h영업일 후(없으면 최종일) 수익률 %"""
    if t not in pcol or d8 not in tdi: return None
    i0 = tdi[d8]; i1 = min(i0+h, len(tdays)-1) if h else len(tdays)-1
    if i1 <= i0: return None
    p0, p1 = parr[i0, pcol[t]], parr[i1, pcol[t]]
    return (p1/p0-1)*100 if (p0 > 0 and p1 > 0) else None

def ic_table(df, cols, label):
    print(f"\n=== {label} (n={len(df)}) ===")
    for c, nm in cols:
        m = df[[c, 'fwd']].dropna()
        m = m[np.isfinite(m[c])]
        if len(m) < 20:
            print(f"  {nm:<28} n={len(m)} 부족"); continue
        ic = m[c].corr(m['fwd'], method='spearman')
        hi = m[m[c] > m[c].median()]['fwd'].mean(); lo = m[m[c] <= m[c].median()]['fwd'].mean()
        print(f"  {nm:<28} IC={ic:+.3f}  n={len(m)}  상위half {hi:+.2f}% vs 하위 {lo:+.2f}% (Δ{hi-lo:+.2f}p)")

# ── ① ntm_screening: per-date IC (Fama-MacBeth식) + pooled
c = sqlite3.connect(ROOT+'/kr_eps_momentum/eps_momentum_data_kr.db')
ns = pd.read_sql("SELECT date,ticker,ntm_current,ntm_30d,ntm_7d FROM ntm_screening", c)
ns['tk'] = ns['ticker'].str[:6]; ns['d8'] = ns['date'].str.replace('-', '')
rows = []
for _, r in ns.iterrows():
    if not r['ntm_current'] or r['ntm_current'] <= 0: continue
    p0 = pr(r['tk'], r['d8'])
    if not p0 or r['d8'] >= LAST: continue
    rows.append({
        'd8': r['d8'], 'tk': r['tk'],
        'rev30': (r['ntm_current']/r['ntm_30d']-1) if (r['ntm_30d'] and r['ntm_30d'] > 0) else np.nan,
        'rev7': (r['ntm_current']/r['ntm_7d']-1) if (r['ntm_7d'] and r['ntm_7d'] > 0) else np.nan,
        'lvl': -p0/r['ntm_current'],   # 레벨 = 선행PER 낮을수록 좋음
        'fwd': fwd_ret(r['tk'], r['d8'])})
o = pd.DataFrame(rows)
ic_table(o, [('rev30','리비전30일'), ('rev7','리비전7일'), ('lvl','레벨(-fwdPER)')],
         f"① ntm_screening pooled 6/1~ → {LAST} (혼합호라이즌 주의)")
# per-date IC 평균
print("  [per-date IC 평균 (n>=60 날만)]")
for col, nm in [('rev30','리비전30'), ('lvl','레벨')]:
    ics = []
    for d, g in o.groupby('d8'):
        m = g[[col, 'fwd']].dropna()
        if len(m) >= 60: ics.append(m[col].corr(m['fwd'], method='spearman'))
    if ics:
        a = np.array(ics)
        print(f"  {nm:<12} mean IC={a.mean():+.3f}  (일수={len(a)}, 양수비율 {(a>0).mean()*100:.0f}%)")

# ── ② fnguide_consensus_history: 6/10→6/29 rev(13td), fwd 6/29→최종
h = pd.read_parquet(ROOT+'/data_cache/fnguide_consensus_history.parquet')
h['ticker'] = h['ticker'].astype(str).str.zfill(6)
snaps = sorted(h['date'].unique())
if len(snaps) >= 2:
    a = h[h['date'] == snaps[0]].set_index('ticker')['forward_eps']
    b = h[h['date'] == snaps[-1]].set_index('ticker')
    common = [t for t in b.index if t in a.index and a[t] and a[t] > 0 and b.loc[t,'forward_eps'] > 0]
    rows = [{'rev': b.loc[t,'forward_eps']/a[t]-1, 'lvl': -b.loc[t,'forward_per'] if b.loc[t,'forward_per'] and b.loc[t,'forward_per']>0 else np.nan,
             'fwd': fwd_ret(t, snaps[-1])} for t in common]
    ic_table(pd.DataFrame(rows), [('rev', f'리비전 {snaps[0]}→{snaps[-1]}'), ('lvl','레벨(-fwdPER)')],
             f"② fnguide history 스냅샷 rev → fwd {snaps[-1]}→{LAST}")

# ── ③ fusion_consensus_cache: 6/25→7/1 rev(4td), fwd 7/1→최종(3td)
fc = pd.read_csv(ROOT+'/kr_eps_momentum/fusion_consensus_cache.csv', dtype={'ticker': str})
fc['ticker'] = fc['ticker'].str.zfill(6)
d0, d1 = '20260625', '20260701'
a = fc[(fc['date'].astype(str) == d0) & (fc['forward_eps'] > 0)].set_index('ticker')['forward_eps']
b = fc[(fc['date'].astype(str) == d1) & (fc['forward_eps'] > 0)].set_index('ticker')['forward_eps']
rows = []
for t in b.index:
    if t in a.index:
        p = pr(t, d1)
        rows.append({'rev': b[t]/a[t]-1, 'lvl': -p/b[t] if p else np.nan, 'fwd': fwd_ret(t, d1)})
ic_table(pd.DataFrame(rows), [('rev', f'리비전 {d0}→{d1}'), ('lvl','레벨(-fwdPER)')],
         f"③ fusion cache rev → fwd {d1}→{LAST}")
print("\n※ 전부 실측이나 창 극단적으로 짧음(호라이즌 1~23td) — 방향 참고용, 결론은 look-ahead proxy BT + 누적 후 재측정")
