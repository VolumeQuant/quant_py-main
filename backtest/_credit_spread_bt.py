# -*- coding: utf-8 -*-
"""KR 신용스프레드(회사채BBB- − 국고채3년) 게이트 검증 (2026-06-20, ECOS 기존키 사용).
research 후보: 신용경색 선행. 스프레드 레벨/변화 z-score 발동 → 50%스케일(브레드스와 동일 보험).
baseline(Cal 4.08/MDD25.9%) 대비 + 브레드스와 중복/보완 여부."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import numpy as np, pandas as pd, requests
from datetime import datetime
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from config import ECOS_API_KEY

# ── ECOS fetch (캐시) ──
cache = os.path.join(P, 'data_cache', 'kr_credit_spread.parquet')
if os.path.exists(cache):
    sp = pd.read_parquet(cache)['spread']
    print(f"신용스프레드 캐시 {len(sp)}일 ({sp.index[0].date()}~{sp.index[-1].date()})")
else:
    def fetch(code, nm):
        url = f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}/json/kr/1/10000/817Y002/D/20180101/{datetime.now().strftime('%Y%m%d')}/{code}"
        rows = requests.get(url, timeout=20).json().get('StatisticSearch', {}).get('row', [])
        rec = [{'date': pd.Timestamp(r['TIME']), 'rate': float(r['DATA_VALUE'])} for r in rows if r.get('DATA_VALUE')]
        d = pd.DataFrame(rec).set_index('date').sort_index()
        print(f"  {nm}: {len(d)}일"); return d['rate']
    ktb = fetch('010200000', '국고채3년')
    bbb = fetch('010320000', '회사채BBB-')
    sp = (bbb - ktb).dropna()
    sp.to_frame('spread').to_parquet(cache)
    print(f"신용스프레드 저장 {len(sp)}일")
print(f"현재 스프레드 {sp.iloc[-1]:.2f}%p | 5년평균 {sp.tail(1260).mean():.2f} | z(60d): {((sp.iloc[-1]-sp.tail(252).mean())/sp.tail(252).std()):.2f}")

# ── 상태/MA/sim (브레드스 BT와 동일 골격) ──
from turbo_simulator import TurboSimulator, _run_regime_inner
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days); dts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])
# 신용스프레드 시그널: 레벨 z, 변화 z (거래일 reindex, ffill)
sp_d = sp.reindex(dts).ffill()
lvl_z = ((sp_d - sp_d.rolling(252, min_periods=120).mean()) / sp_d.rolling(252, min_periods=120).std()).values
chg = sp_d.diff(21)
chg_z = ((chg - chg.rolling(252, min_periods=120).mean()) / chg.rolling(252, min_periods=120).std()).values
print(f"신용스프레드 거래일 매핑 {(~np.isnan(lvl_z)).sum()}/{len(days)}일")
s_ = kc.rolling(20).mean(); l_ = kc.rolling(80).mean()
regA = np.zeros(len(days), bool); md = True; stk = 0; ss = None
for i, d in enumerate(days):
    ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
    if pd.isna(sv) or pd.isna(lv): regA[i] = md; continue
    sb = bool(sv > lv); stk = stk+1 if sb == ss else 1; ss = sb
    if stk >= 5 and md != sb: md = sb
    regA[i] = md
t = TurboSimulator(ar, days, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
for d in days:
    tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
    t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
flat = list(t._cached_flat); parr = t._price_arr; drows = t._date_row_indices
def base_rets():
    port = {}; prev = None; r = np.zeros(len(days))
    for i in range(2, len(days)):
        cur = regA[i]
        if prev is not None and cur != prev: port = {}
        prev = cur
        if flat[i] is None or not cur:
            if i+1 < len(days) and port:
                cr = drows[i]; nr = drows[i+1]; rr = [parr[nr,c]/parr[cr,c]-1 for c in port if parr[cr,c]==parr[cr,c] and parr[nr,c]==parr[nr,c] and parr[cr,c]>0]; r[i+1] = np.mean(rr) if rr else 0
            continue
        wr, cc, cp, cw = flat[i]
        for c in list(port):
            if wr[c] > 6: del port[c]
        slots = 3-len(port)
        for k in range(len(cc)):
            if slots <= 0: break
            if cw[k] <= 3 and cc[k] not in port: port[cc[k]] = cp[k]; slots -= 1
        if i+1 < len(days) and port:
            cr = drows[i]; nr = drows[i+1]; rr = [parr[nr,c]/parr[cr,c]-1 for c in port if parr[cr,c]==parr[cr,c] and parr[nr,c]==parr[nr,c] and parr[cr,c]>0]; r[i+1] = np.mean(rr) if rr else 0
    return r
rets = base_rets(); cash_d = 0.03/252
def defarr(sig, thr, cf=3):
    out = np.zeros(len(days), bool); md = True; stk = 0; ss = None
    for i in range(len(days)):
        v = sig[i]; s = (v < thr) if v == v else ss  # z가 thr 미만=정상, 초과=스트레스(방어)
        if s is None: out[i] = (not md); continue
        stk = stk+1 if s == ss else 1; ss = s
        if stk >= cf and md != s: md = s
        out[i] = (not md)
    return out
def scaled(bdef, sc=0.5):
    r = rets.copy()
    for i in range(len(days)):
        if regA[i] and bdef[i]: r[i] = sc*rets[i]+(1-sc)*cash_d
    return r
def metr(r, mask=None):
    if mask is not None: r = r[mask]
    eq = np.cumprod(1+r); cagr = eq[-1]**(252/len(r))-1; mdd = (eq/np.maximum.accumulate(eq)-1).min()
    return cagr/abs(mdd), mdd*100
bearmask = np.array(['20220101' <= d <= '20231231' for d in days])
cb, mb = metr(rets)
print(f"\nbaseline: Calmar {cb:.3f} MDD {mb:.1f}%")
print(f"{'신호(50%스케일)':<26}{'Cal':>7}{'MDD':>7}{'약세MDD':>8}{'발동%':>7}")
print("-"*56)
for nm, sig, thr in [('레벨z>1.0', lvl_z, 1.0), ('레벨z>1.5', lvl_z, 1.5),
                     ('변화z>1.0', chg_z, 1.0), ('변화z>1.5', chg_z, 1.5)]:
    bdef = defarr(sig, thr); r = scaled(bdef); c, m = metr(r); _, bm = metr(r, bearmask)
    print(f"  {nm:<24}{c:>6.3f}{m:>6.1f}%{bm:>7.1f}%{bdef.sum()/len(days)*100:>6.0f}%")
print("\n[판정] baseline 4.08/약세24.7% 대비 개선이면 채택. 브레드스(4.36)와 비교 + 보완성.")
