# -*- coding: utf-8 -*-
"""VM top4 KR — 풀 US 사양 재측정: 거래대금 floor(20일평균, 원시종가×거래량) + gap≥2.5 포함.
US $1B ≈ 시장회전율 비례 환산 ~300억. 100/300/500억 스윕. 나머지 하니스는 _vm_top4_kr_bt.py와 동일."""
import sys, io, os, glob, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
prices = prices[prices.notna().any(axis=1)]
pcol = {c: i for i, c in enumerate(prices.columns)}; parr = prices.values
tdays = [d.strftime('%Y%m%d') for d in prices.index]; tdi = {d: i for i, d in enumerate(tdays)}
NT = len(tdays)
day64 = np.array([np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])) for d in tdays])
# 거래대금 20일 평균 (원시종가 × 거래량 — 수정주가 왜곡 회피)
raw = pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
vol = pd.read_parquet(P+'/data_cache/all_volume_20150331_20260622.parquet')
common = [c for c in prices.columns if c in raw.columns and c in vol.columns]
tv = (raw[common].reindex(prices.index) * vol[common].reindex(prices.index)).rolling(20, min_periods=5).mean()
tvcol = {c: i for i, c in enumerate(tv.columns)}; tvarr = tv.values
kc = pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
cache = pickle.load(open(P+'/backtest/_earn_cache.pkl', 'rb'))
mc = pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh = {t: mc.loc[t, '상장주식수'] for t in mc.index}
i0 = tdi['20190102']; i_end = NT - 250
reg = {}; md = True; stk = 0; ss = None
for d in tdays:
    ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts in kc.index and not pd.isna(ma80.get(ts, np.nan)):
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
    reg[d] = md
TTM = {}
for t, dd in cache.items():
    s = dd.get('ni')
    if s is None or len(s[0]) < 4 or t not in pcol or t not in sh or not sh[t] or sh[t] <= 0: continue
    dts_r, vals = s[0], s[1]
    tr = np.full(len(vals), np.nan)
    for k in range(3, len(vals)): tr[k] = vals[k-3:k+1].sum()
    idx = np.searchsorted(dts_r, day64, side='right') - 1
    TTM[t] = np.where(idx >= 0, tr[np.clip(idx, 0, None)], np.nan)
tickers = sorted(TTM.keys())
SIG = {}
def get_sig(i):
    if i in SIG: return SIG[i]
    out = []; row = parr[i]
    for t in tickers:
        p = row[pcol[t]]
        if not (p > 0): continue
        mcap = p*sh[t]
        if mcap < 1000e8: continue
        e1 = TTM[t][min(i+250, NT-1)]
        if not (e1 and e1 > 0): continue
        e90 = TTM[t][min(i+160, NT-1)]; e0 = TTM[t][i]
        tv20 = tvarr[i, tvcol[t]] if t in tvcol else np.nan
        out.append((t, mcap/(e1*1e8), e1/e90-1 if (e90 and e90 > 0) else np.nan,
                    e1/e0 if (e0 and e0 > 0) else np.nan, tv20))
    SIG[i] = out; return out
def run(phase, fpe_max=20, sort='rev90', gap_min=None, tv_min=None, N=4, R=5):
    held = []; rets = []
    for j, i in enumerate(range(i0+phase, i_end)):
        d = tdays[i]; r = 0.0
        if held:
            vs = [parr[i, pcol[t]]/parr[i-1, pcol[t]]-1 for t in held if parr[i-1, pcol[t]] > 0 and parr[i, pcol[t]] > 0]
            r = float(np.mean(vs)) if vs else 0.0
        rets.append((d, r))
        if not reg.get(d, True): held = []; continue
        if j % R == 0:
            pool = []
            for t, fpe, rev, gap, tv20 in get_sig(i):
                if fpe_max and not (fpe < fpe_max): continue
                if gap_min is not None and not (np.isnan(gap) or gap >= gap_min): continue  # missing=pass
                if tv_min and not (tv20 and tv20 >= tv_min): continue
                v = -fpe if sort == 'level' else (rev if sort == 'rev90' else gap)
                if not np.isnan(v): pool.append((v, t))
            pool.sort(reverse=True)
            held = [t for _, t in pool[:N]]
    return rets
def stats(rets, sub=None):
    a = np.array([r for d, r in rets if (not sub or sub[0] <= d <= sub[1])])
    if len(a) < 40: return None
    eq = np.cumprod(1+a); peak = np.maximum.accumulate(eq)
    mdd = ((eq-peak)/peak).min()*100
    return (eq[-1]**(252/len(a))-1)*100, mdd, ((eq[-1]**(252/len(a))-1)*100)/abs(mdd) if mdd < 0 else 0
BLOCKS = [('전체', None), ('강세19-21', ('20190102', '20211231')), ('약세22-23', ('20220101', '20231231')), ('최근24-26', ('20240101', '20991231'))]
def report(label, **kw):
    pp = [run(ph, **kw) for ph in range(5)]
    line = f"  {label:<42}"
    for _, sub in BLOCKS:
        ss = [s for s in (stats(r, sub) for r in pp) if s]
        if not ss: line += f" {'—':>18}"; continue
        line += f" {np.mean([s[0] for s in ss]):+6.0f}%/{min(s[1] for s in ss):5.1f}/{np.mean([s[2] for s in ss]):4.2f}"
    print(line, flush=True)
print("[풀 US사양 재측정 — 위상평균 CAGR/최악MDD/Calmar]  (전체 / 강세19-21 / 약세22-23 / 최근24-26)")
report("baseline: fwdPER<20+rev90 (조건無)")
report("+거래대금>=100억", tv_min=100e8)
report("+거래대금>=300억 (US $1B 환산)", tv_min=300e8)
report("+거래대금>=500억", tv_min=500e8)
report("+gap>=2.5", gap_min=2.5)
report("★풀사양: gap2.5+거래대금300억", gap_min=2.5, tv_min=300e8)
report("풀사양 PER30 (US원본 임계)", fpe_max=30, gap_min=2.5, tv_min=300e8)
report("풀사양 + 레벨정렬", gap_min=2.5, tv_min=300e8, sort='level')
report("풀사양 + gap정렬", gap_min=2.5, tv_min=300e8, sort='gap')
