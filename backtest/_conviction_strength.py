# -*- coding: utf-8 -*-
"""확신가중 강도 차등 실험 (2026-06-25, 사용자: sleeve 강할수록 더 사기).
현재 binary(top100=×3) vs 강도 차등(순위비례·grow값비례·계단식). look-ahead 상한 BT라 상대비교용."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
pcol = {c: i for i, c in enumerate(prices.columns)}; parr = prices.values
tdays = [d.strftime('%Y%m%d') for d in prices.index]; tdi = {d: i for i, d in enumerate(tdays)}
kc = pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:, 0]; ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
cache = pickle.load(open(P+'/backtest/_earn_cache.pkl', 'rb'))
ar = {}; dts = []
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102' and dt in tdi:  # ★가격 있는 날만
        ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dts.append(dt)
dts = sorted(dts)
def reg_s():
    reg = {}; md = True; stk = 0; ss = None
    for d in dts:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
reg = reg_s()
def ttm(t, d):
    dd = cache.get(t); s = dd.get('ni') if dd else None
    if s is None: return None
    v = s[1][s[0] <= np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))]
    return v[-4:].sum() if len(v) >= 4 else None
# 일별 top100 선행성장 + grow값 (월별 캐시)
confirm = {}; cur = {}; curm = None
for d in dts:
    if d[:6] != curm:
        curm = d[:6]; i = tdi[d]; d1 = tdays[min(i+250, len(tdays)-1)]; fg = []
        for t in cache:
            if t not in pcol or not (parr[i, pcol[t]] > 0): continue
            e0 = ttm(t, d); e1 = ttm(t, d1)
            if e0 and e0 > 0 and e1 is not None: fg.append((t, e1/e0-1))
        fg.sort(key=lambda z: -z[1])
        top = fg[:100]
        cur = {t: {'rank': r+1, 'grow': g} for r, (t, g) in enumerate(top)}
    confirm[d] = cur
def sim(wfn):
    """wfn(info)->weight. info=None(미확인) or {'rank','grow'}."""
    held = []; daily = []; prev = None; pw = {}
    for d in dts:
        ret = 0.0
        if held and prev and prev in tdi:
            num = 0; den = 0
            for t in held:
                if t in pcol and parr[tdi[prev], pcol[t]] > 0 and parr[tdi[d], pcol[t]] > 0:
                    w = pw.get(t, 1.0); num += w*(parr[tdi[d], pcol[t]]/parr[tdi[prev], pcol[t]]-1); den += w
            ret = num/den if den > 0 else 0.0
        daily.append(ret)
        if not reg.get(d, True): held = []; pw = {}
        else:
            held = [x['ticker'] for x in sorted(ar[d], key=lambda z: z.get('rank', 99))[:3]]
            cf = confirm.get(d, {}); pw = {t: wfn(cf.get(t)) for t in held}
        prev = d
    a = np.array(daily); eq = np.cumprod(1+a); peak = np.maximum.accumulate(eq); mdd = ((eq-peak)/peak).min()*100
    n = len(a); cagr = (eq[-1]**(252/max(n, 1))-1)*100
    return cagr, mdd, (cagr/abs(mdd) if mdd < 0 else 0)
# 강도함수들
def binary(cw): return lambda i: (cw if i else 1.0)
def rank_lin(cw): return lambda i: (1.0 + (cw-1)*(100-i['rank']+1)/100 if i else 1.0)  # rank1→cw, rank100→~1
def grow_lin(k, cap): return lambda i: (min(1.0+k*max(i['grow'], 0), cap) if i else 1.0)  # grow비례
def step(): return lambda i: (5.0 if i and i['rank']<=10 else (4.0 if i and i['rank']<=30 else (2.5 if i else 1.0)))
print("[확신가중 강도 차등 — look-ahead 상한 BT, 상대비교]\n")
print(f"  {'방식':<24}{'CAGR':>7}{'MDD':>8}{'Calmar':>8}")
for nm, fn in [('동일가중(baseline)', binary(1.0)),
               ('★binary ×3 (현행)', binary(3.0)),
               ('순위비례 1~3 (rank약)', rank_lin(3.0)),
               ('순위비례 1~5', rank_lin(5.0)),
               ('grow비례 k=1 cap3', grow_lin(1.0, 3.0)),
               ('grow비례 k=2 cap5', grow_lin(2.0, 5.0)),
               ('계단식 top10×5/30×4/100×2.5', step())]:
    c, m, cal = sim(fn)
    print(f"  {nm:<24}{c:>6.0f}%{m:>7.1f}%{cal:>8.2f}")
print("\n→ 현행 binary×3 넘으면 강도차등 채택. 비슷/미달이면 binary가 단순·우월")
