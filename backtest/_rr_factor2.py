# -*- coding: utf-8 -*-
"""②-확인: 이진 recent_rights가 약한 이유 점검 — 더 풍부한 명시팩터도 corp-OFF(4.31) 못 미치나?
(a) 양방향(상승+하락) 트리거 플래그 (b) 등급형: 최근K일내 최저일수익 크기비례 페널티.
둘 다 corp-OFF에 한참 미달이면 = 'corp-OFF의 등급적 원가격모멘텀'을 이진/단순팩터론 대체 불가 확정."""
import sys, io, os, glob, json
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
rets=raw.pct_change(fill_method=None)
both=((rets<-0.33)|(rets>0.45))
# 등급형: 최근K일 최저 일수익(가장 큰 폭락 크기), clip
worstK=lambda K: rets.rolling(K,min_periods=1).min()  # 가장 음의 수익
def build(ar):
    t=TurboSimulator({d:ar[d] for d in common}, common, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    base={d: t._overlay_pre[d].copy() for d in common}
    return t,base
tON,baseON=build(ON); tOFF,baseOFF=build(OFF)
def runpen(t,base,penfn):
    for d in common:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); tks=t._preextracted[d][0]
        t._overlay_pre[d]=base[d]+penfn(ts,tks)
    t._cached_key=None
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
c_off=runpen(tOFF,baseOFF,lambda ts,tks: np.zeros(len(tks)))
print(f"기준선 corp-OFF(deployed) {c_off:.3f}\n")
# (a) 양방향 이진
print("=== (a) 양방향(상승+하락) 이진 플래그 (corp-ON 기반) ===")
print(f"{'K\\λ':>6}"+"".join(f"{l:>8}" for l in [0.3,0.5,0.8,1.2,2.0]))
for K in [126,252]:
    fm=(both.rolling(K,min_periods=1).max()>0); row=f"{K:>6}"
    for lam in [0.3,0.5,0.8,1.2,2.0]:
        def pf(ts,tks,fm=fm,lam=lam):
            r=fm.loc[ts] if ts in fm.index else None
            return np.zeros(len(tks)) if r is None else np.array([-lam if (tk in r.index and bool(r[tk])) else 0.0 for tk in tks])
        row+=f"{runpen(tON,baseON,pf):>8.2f}"
    print(row)
# (b) 등급형: 페널티 = λ * |min(worstK,0)| (폭락 클수록 더 감점)
print("\n=== (b) 등급형(최근K일 최대폭락 크기비례, corp-ON 기반) ===")
print(f"{'K\\λ':>6}"+"".join(f"{l:>8}" for l in [0.5,1.0,2.0,3.0]))
for K in [126,252]:
    wk=worstK(K); row=f"{K:>6}"
    for lam in [0.5,1.0,2.0,3.0]:
        def pf(ts,tks,wk=wk,lam=lam):
            r=wk.loc[ts] if ts in wk.index else None
            if r is None: return np.zeros(len(tks))
            return np.array([ -lam*abs(min(r.get(tk,0.0),0.0)) if (tk in r.index and pd.notna(r.get(tk))) else 0.0 for tk in tks])
        row+=f"{runpen(tON,baseON,pf):>8.2f}"
    print(row)
print(f"\n→ 둘 다 corp-OFF({c_off:.2f}) 한참 미달이면 = 명시 단순팩터로 대체 불가, corp-OFF(원가격모멘텀) 유지가 정답.")
