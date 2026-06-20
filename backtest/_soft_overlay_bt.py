# -*- coding: utf-8 -*-
"""soft 슬롯축소 overlay (2026-06-20 자율). 리서치 flagship: 현금 몰빵 아닌 부분 디리스크.
약세신호(브레드스 약함)일 때 슬롯 3→2→1로 줄여 노출만 축소(보유는 top랭크 유지).
먼저 고정3슬롯 재구현이 baseline Calmar 재현하는지 검증 후 변동슬롯."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
B = pd.read_parquet(P + '/data_cache/_breadth_series.parquet')
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)
dts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])
b200 = B['b200'].reindex(dts).values

# 게이트(MA20/80/5)
def ma_regime():
    s_ = kc.rolling(20).mean(); l_ = kc.rolling(80).mean(); reg = {}; md = True; stk = 0; ss = None
    for d in days:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
        if pd.isna(sv) or pd.isna(lv): reg[d] = md; continue
        s = bool(sv > lv); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
reg = ma_regime()
regA = np.array([reg[d] for d in days])

# flat 준비 (down-only overlay)
t = TurboSimulator(ar, days, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
for d in days:
    tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
    t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
flat = list(t._cached_flat)
parr = t._price_arr; drows = t._date_row_indices

def sim(slots_by_day):
    """변동슬롯 포트폴리오 시뮬. entry rank<=3, exit rank>6, 전환청산, defense=cash. 동일비중 일별수익."""
    port = {}; prev = None; rets = np.zeros(len(days))
    for i in range(2, len(days)):
        cur = regA[i]
        if prev is not None and cur != prev: port = {}
        prev = cur
        if flat[i] is None or not cur:
            # 수익 반영 (보유분, defense면 port 비었음)
            if i+1 < len(days) and port:
                cr = drows[i]; nr = drows[i+1]
                rr = [parr[nr, c]/parr[cr, c]-1 for c in port if parr[cr, c] == parr[cr, c] and parr[nr, c] == parr[nr, c] and parr[cr, c] > 0]
                rets[i+1] = np.mean(rr) if rr else 0
            continue
        wrank_arr, cand_cols, cand_prices, cand_wranks = flat[i]
        for c in list(port):
            if wrank_arr[c] > 6: del port[c]
        ms = slots_by_day[i]
        # 슬롯 줄면 초과보유분 정리(랭크 나쁜 것부터)
        if len(port) > ms:
            held = sorted(port, key=lambda c: wrank_arr[c], reverse=True)
            for c in held[:len(port)-ms]: del port[c]
        slots = ms - len(port)
        for k in range(len(cand_cols)):
            if slots <= 0: break
            if cand_wranks[k] <= 3 and cand_cols[k] not in port:
                port[cand_cols[k]] = cand_prices[k]; slots -= 1
        if i+1 < len(days) and port:
            cr = drows[i]; nr = drows[i+1]
            rr = [parr[nr, c]/parr[cr, c]-1 for c in port if parr[cr, c] == parr[cr, c] and parr[nr, c] == parr[nr, c] and parr[cr, c] > 0]
            rets[i+1] = np.mean(rr) if rr else 0
    eq = np.cumprod(1+rets)
    yrs = len(days)/252
    cagr = eq[-1]**(1/yrs)-1
    mdd = (eq/np.maximum.accumulate(eq)-1).min()
    cal = cagr/abs(mdd) if mdd < 0 else 0
    return cal, cagr*100, mdd*100

print(f"현재 b200={b200[-1]*100:.0f}%")
# 검증: 고정 3슬롯이 baseline 재현?
fixed3 = np.full(len(days), 3)
c = sim(fixed3)
print(f"\n[검증] 내 시뮬 고정3슬롯: Calmar {c[0]:.3f} CAGR {c[1]:.0f}% MDD {c[2]:.1f}% (공식 baseline 4.05/25.9% 재현 확인용)")
# 변동슬롯: b200 약하면 슬롯 축소
def slots_breadth(hi, lo):
    s = np.full(len(days), 3)
    for i in range(len(days)):
        bv = b200[i]
        if not np.isnan(bv):
            if bv < lo: s[i] = 1
            elif bv < hi: s[i] = 2
    return s
print("\n=== soft 슬롯축소 (b200<hi→2슬롯, b200<lo→1슬롯) ===")
for hi, lo in [(0.40, 0.30), (0.45, 0.35), (0.50, 0.40), (0.35, 0.25)]:
    c = sim(slots_breadth(hi, lo))
    print(f"  b200<{int(hi*100)}→2슬롯 / <{int(lo*100)}→1슬롯 : Calmar {c[0]:.3f} CAGR {c[1]:.0f}% MDD {c[2]:.1f}%")
print("\n[판정] 고정3 대비 MDD↓&Calmar 비악화면 soft overlay 가치. 아니면 부분디리스크도 무효.")
