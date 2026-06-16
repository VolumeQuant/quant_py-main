# -*- coding: utf-8 -*-
"""왜 권리락 보정(corpaction)이 7.4년 성과를 깎았나 — 원인 직접 측정.
실험1: 권리락 트리거 종목의 실제(ba보정) 미래수익. 부진하면 '회피=이득'.
실험2(결정타): 매일 근사 composite top3에서 corp-ON만 사는 종목 vs corp-OFF만 사는 종목의 미래수익.
  corp-ON/OFF 차이는 100% 모멘텀(밸류·성장 동일). ON-only가 부진하면 '보정이 패자를 사게 함' 증명."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
raw = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan)
raw = raw[raw.index >= pd.Timestamp('2019-01-02')]
adj = raw.apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
didx = {d.strftime('%Y%m%d'): i for i,d in enumerate(adj.index)}
arr = adj.values; cols = {c:i for i,c in enumerate(adj.columns)}
def fwd_ret(tk, d, fwd):
    ci = cols.get(tk); i0 = didx.get(d)
    if ci is None or i0 is None or i0+fwd >= len(arr): return None
    p0,p1 = arr[i0,ci], arr[i0+fwd,ci]
    return (p1/p0-1) if (p0>0 and p1>0) else None

# ===== 실험1: 권리락 트리거 종목의 미래 실제수익 =====
rets = raw.pct_change(fill_method=None)
down = (rets < -0.33); up = (rets > 0.45)
print("="*60)
print("실험1: 권리락 트리거 종목의 트리거일 이후 실제(보정) 미래수익")
print("="*60)
for lbl, mask in [('하락트리거(<-33%, 무상증자/분할)', down), ('상승트리거(>+45%, 병합/갭)', up)]:
    idx = np.argwhere(mask.values)
    for fwd in [20,60,250]:
        frs=[]
        for ri,ci in idx:
            d = adj.index[ri].strftime('%Y%m%d'); tk = adj.columns[ci]
            fr = fwd_ret(tk, d, fwd)
            if fr is not None: frs.append(fr)
        frs=np.array(frs)
        print(f"  {lbl[:20]:<22} fwd{fwd:>3}d: n={len(frs):>4} 평균 {frs.mean()*100:+6.2f}% 중앙 {np.median(frs)*100:+6.2f}% 승률(>0) {(frs>0).mean()*100:4.0f}%")
# 기준선: 전체 종목-날 평균 미래수익
print("  --- 기준선(전체 종목-날 무작위) ---")
allr = adj.pct_change(fill_method=None)
for fwd in [20,60,250]:
    base = (adj.shift(-fwd)/adj - 1).values.flatten()
    base = base[np.isfinite(base)]
    print(f"  {'전체평균':<22} fwd{fwd:>3}d: n={len(base):>6} 평균 {np.mean(base)*100:+6.2f}% 중앙 {np.median(base)*100:+6.2f}% 승률 {(base>0).mean()*100:4.0f}%")

# ===== 실험2: corp-ON만 사는 종목 vs corp-OFF만 사는 종목 =====
def load(folder):
    ar={}
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']
    return ar
ON=load('_sp0b'); OFF=load('_sp0b_co')
common=sorted(set(ON)&set(OFF))
def comp(rk):  # 근사 composite (mom10/vollow 0.11은 생략, 지배항 mom_12m 0.30 포함)
    out={}
    for s in rk:
        out[s['ticker']]=0.15*s.get('value_s',0)+0.55*s.get('growth_s',0)+0.30*s.get('mom_12m_s',0)+0.2*s.get('overheat_pen',0)
    return out
def boost(d):
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in ma80.index or pd.isna(ma80[ts]): return True
    return bool(ma20[ts]>ma80[ts])
TOPN=3
on_only=[]; off_only=[]; on_only_mom_gap=[]
for d in common:
    if not boost(d): continue
    co=comp(ON[d]); cf=comp(OFF[d])
    ton=set(sorted(co,key=lambda t:-co[t])[:TOPN]); tof=set(sorted(cf,key=lambda t:-cf[t])[:TOPN])
    for tk in ton-tof:
        fr=fwd_ret(tk,d,20)
        if fr is not None: on_only.append(fr)
    for tk in tof-ton:
        fr=fwd_ret(tk,d,20)
        if fr is not None: off_only.append(fr)
on_only=np.array(on_only); off_only=np.array(off_only)
print("\n"+"="*60)
print(f"실험2: boost일 근사 composite top{TOPN}, corp-ON vs OFF가 다르게 고른 종목의 fwd20d 실제수익")
print("="*60)
print(f"  corp-ON만 매수(보정으로 모멘텀 살아나 진입): n={len(on_only):>4} 평균 {on_only.mean()*100:+6.2f}% 중앙 {np.median(on_only)*100:+6.2f}% 승률 {(on_only>0).mean()*100:4.0f}%")
print(f"  corp-OFF만 매수(보정 안해 그 자리 차지)     : n={len(off_only):>4} 평균 {off_only.mean()*100:+6.2f}% 중앙 {np.median(off_only)*100:+6.2f}% 승률 {(off_only>0).mean()*100:4.0f}%")
print(f"\n  → ON만 매수 종목이 OFF만 매수 종목보다 부진하면(평균 낮음) = '보정이 패자를 사게 만든다' 직접증명.")
print(f"  차이(ON-only − OFF-only) 평균: {(on_only.mean()-off_only.mean())*100:+.2f}%p")
