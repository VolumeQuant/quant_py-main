# -*- coding: utf-8 -*-
"""② 명시적 recent_rights 페널티 검증 (전문가 권고).
가설: corp-ON(올바른 모멘텀,1.74) + '최근 K일내 하락트리거(권리락) 종목 감점'이
corp-OFF(모멘텀왜곡 우연알파,4.31)를 회복/대체하면 → 같은 알파를 튼튼한 명시규칙으로 얻음.
recent_rights는 가격만으로 계산 → regen 불필요. TurboSim 오버레이에 페널티 주입(core 무수정).
고정 config V15Q0G55M30 12m E3X6S3. 스윕(K,λ) + 최적 WF + LOWO."""
import sys, io, os, glob, json, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
raw = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan)
prices = raw.apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={}; md=True; stk=0; ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md; continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def load(folder):
    ar,dates={}, []
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
    return ar,sorted(dates)
ON,dON=load('_sp0b'); OFF,dOFF=load('_sp0b_co')
common=sorted(set(dON)&set(dOFF)); reg=calc_reg(common)
# 하락 트리거(<-33%) 발생일 매트릭스 → K영업일 rolling any
down = (raw.pct_change(fill_method=None) < -0.33)
def flag_matrix(K):
    return (down.rolling(K, min_periods=1).max() > 0)  # dates×tickers bool: 최근K일내 트리거 있었나
# TurboSim 빌드 (corp-ON) + base overlay 저장
def build(ar):
    t=TurboSimulator({d:ar[d] for d in common}, common, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    base={d: t._overlay_pre[d].copy() for d in common}
    return t, base
def run(t, base, K, lam):
    if lam>0:
        fm=flag_matrix(K)
        for d in common:
            ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
            tks=t._preextracted[d][0]
            row = fm.loc[ts] if ts in fm.index else None
            if row is None: pen=np.zeros(len(tks))
            else: pen=np.array([-lam if (tk in row.index and bool(row[tk])) else 0.0 for tk in tks])
            t._overlay_pre[d]=base[d]+pen
    else:
        for d in common: t._overlay_pre[d]=base[d].copy()
    t._cached_key=None
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
print(f"[{common[0]}~{common[-1]} {len(common)}일] corp-ON + 명시 recent_rights 페널티 스윕")
tON,baseON=build(ON); tOFF,baseOFF=build(OFF)
c_on=run(tON,baseON,0,0); c_off=run(tOFF,baseOFF,0,0)
print(f"\n기준선: corp-ON(λ0) {c_on:.3f}  |  corp-OFF(deployed) {c_off:.3f}")
print(f"\n=== corp-ON + recent_rights penalty (목표: corp-OFF {c_off:.2f} 회복?) ===")
print(f"{'K\\λ':>6}" + "".join(f"{l:>8}" for l in [0.1,0.2,0.3,0.5,0.8,1.2]))
best=(-9,None)
for K in [63,126,252]:
    row=f"{K:>6}"
    for lam in [0.1,0.2,0.3,0.5,0.8,1.2]:
        c=run(tON,baseON,K,lam); row+=f"{c:>8.2f}"
        if c>best[0]: best=(c,(K,lam))
    print(row)
print(f"\n최적 corp-ON+RR: {best[0]:.3f} @ K={best[1][0]} λ={best[1][1]}  (corp-OFF {c_off:.2f} 대비 {best[0]-c_off:+.2f})")
print(f"\n→ best가 corp-OFF(4.31) 회복/초과면 = 명시팩터가 모멘텀왜곡 대체 가능(튼튼). 한참 못미치면 = 왜곡채널이 더 많이 잡던것(명시론 일부만).")
