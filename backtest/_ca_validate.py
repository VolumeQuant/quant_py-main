# -*- coding: utf-8 -*-
"""corpaction 제거 배포 전 robustness battery: corp-ON(_sp0b) vs corp-OFF(_sp0b_co).
고정 운영config V15Q0G55M30 12m E3X6S3. ①전체 ②WF 3블록 ③LOWO(슈퍼위너 하나씩 제외).
corp-OFF가 전구간·전블록·전LOWO에서 일관 우위면 = 단일종목 착시 아님, 배포 안전."""
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
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
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
ON,dO=load('_sp0b'); OFF,dF=load('_sp0b_co')
common=sorted(set(dO)&set(dF)); reg=calc_reg(common)
def cal(ar, sub, drop_names=None):
    a={}
    for d in sub:
        if drop_names: a[d]=[s for s in ar[d] if not any(x in s['name'] for x in drop_names)]
        else: a[d]=ar[d]
    t=TurboSimulator(a, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
print(f"[{common[0]}~{common[-1]} {len(common)}일] corpaction 제거 검증 (corp-OFF가 일관 우위면 배포안전)")
print(f"\n=== ① 전체 (고정 config) ===")
cON=cal(ON,common); cOFF=cal(OFF,common)
print(f"  corp-ON {cON:.3f}  vs  corp-OFF {cOFF:.3f}   Δ(OFF-ON) {cOFF-cON:+.3f}")
print(f"\n=== ② WF 3블록 ===")
for nm,lo,hi in [('19-21','20190102','20211231'),('22-23(약세장)','20220101','20231231'),('24-26','20240101','20261231')]:
    sub=[d for d in common if lo<=d<=hi]
    if len(sub)<60: continue
    a=cal(ON,sub); b=cal(OFF,sub)
    print(f"  {nm:<12}: ON {a:.2f}  OFF {b:.2f}   Δ {b-a:+.2f}")
print(f"\n=== ③ LOWO (슈퍼위너 하나씩 제외, corp-OFF가 여전히 우위면 단일종목 착시 아님) ===")
WINNERS=['SK하이닉스','제주반도체','디바이스','한미반도체','제룡전기','이오테크닉스']
print(f"  (제외없음)        : ON {cON:.2f}  OFF {cOFF:.2f}  Δ {cOFF-cON:+.2f}")
for w in WINNERS:
    a=cal(ON,common,[w]); b=cal(OFF,common,[w])
    print(f"  −{w:<12}: ON {a:.2f}  OFF {b:.2f}  Δ {b-a:+.2f}")
print(f"\n→ 전구간·전블록(약세장 포함)·전LOWO에서 Δ>0(OFF우위) 일관이면 corpaction 제거 배포 안전.")
