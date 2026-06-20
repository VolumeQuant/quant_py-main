# -*- coding: utf-8 -*-
"""KR 섹터 브레드스 게이트 — US 위너(섹터 브레드스) 방식 정직 재현 (2026-06-20).
US: 11 SPDR 섹터 중 자기 200DMA 위 비율 <45% (3/15일 확인) OR into 게이트 → MDD 36.5→27.4%.
KR 재현: ~24 KRX 섹터 EW지수 중 자기 200DMA 위 비율 <X → defense (MA게이트에 OR).
★전종목 브레드스(노이즈·소형주지배)와 다름 = 거친 섹터레벨(저노이즈). 캐시만(IP無관)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
sec = pd.read_parquet(sorted(glob.glob(P + '/data_cache/krx_sector_*.parquet'))[-1])
sec.columns = ['ticker', 'sector'] if list(sec.columns)[:2] == list(sec.columns)[:2] else sec.columns
sec = sec.rename(columns={sec.columns[0]: 'ticker', sec.columns[1]: 'sector'})
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)
dts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])

# 섹터 EW 지수 → 자기 200DMA 위 비율 (섹터 브레드스)
ret = prices.pct_change(fill_method=None)
sec_groups = sec.groupby('sector')['ticker'].apply(list).to_dict()
sec_idx = {}
for s, tks in sec_groups.items():
    cols = [t for t in tks if t in ret.columns]
    if len(cols) < 5: continue
    sr = ret[cols].mean(axis=1)             # 섹터 EW 일수익
    sec_idx[s] = (1 + sr.fillna(0)).cumprod()
print(f"섹터 지수 {len(sec_idx)}개 구성")
sec_df = pd.DataFrame(sec_idx)
sec_ma200 = sec_df.rolling(200, min_periods=150).mean()
above = (sec_df > sec_ma200)
valid = sec_df.notna() & sec_ma200.notna()
sec_breadth = (above & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
sb = sec_breadth.reindex(dts)
print(f"현재 섹터브레드스 {sb.iloc[-1]*100:.0f}% (평균 {sec_breadth.mean()*100:.0f}%, 약세2022 최저 {sec_breadth['2022-01-01':'2023-06-01'].min()*100:.0f}%)")

def ma_regime():
    s_ = kc.rolling(20).mean(); l_ = kc.rolling(80).mean(); reg = {}; md = True; stk = 0; ss = None
    for d in days:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
        if pd.isna(sv) or pd.isna(lv): reg[d] = md; continue
        s = bool(sv > lv); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
def confirm(boolser, k):
    reg = {}; md = True; stk = 0; ss = None
    for i, d in enumerate(days):
        v = boolser.iloc[i]; s = (bool(v) if not pd.isna(v) else ss)
        if s is None: reg[d] = md; continue
        stk = stk+1 if s == ss else 1; ss = s
        if stk >= k and md != s: md = s
        reg[d] = md
    return reg
def bt(reg, lo='20190102', hi='20260617'):
    sub = [d for d in days if lo <= d <= hi]
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench, t._date_row_indices, len(sub), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0), sum(1 for d in sub if not reg[d])
base = ma_regime()
def show(nm, reg):
    c = bt(reg); bb = bt(reg, '20220101', '20231231'); cv = bt(reg, '20200101', '20201231')
    print(f"{nm:<40}{c[0]:>7.3f}{c[1]:>7.1f}%{c[2]:>7.1f}%{c[3]:>6}일  약세 {bb[2]:.1f}% 코로나 {cv[2]:.1f}%")
print(f"\n{'전략':<40}{'Calmar':>7}{'CAGR':>8}{'MDD':>7}{'현금':>6}  MDD분해\n"+"-"*96)
show("baseline MA20/80/5", base)
print("--- US방식: MA defense OR 섹터브레드스<X (조기방어 가산) ---")
for X in [0.35, 0.40, 0.45, 0.50]:
    for cf in [3, 5]:
        reg = {d: base[d] and confirm(sb > X, cf)[d] for d in days}
        show(f"MA OR 섹터breadth<{int(X*100)}% ({cf}일확인)", reg)
print("\n[판정] baseline(Cal4.05/MDD25.9%) 대비 MDD↓ & Calmar 비악화(>3.9)면 ★US처럼 위너. 아니면 KR baseline이 이미 충분.")
