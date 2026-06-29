# -*- coding: utf-8 -*-
"""멀티팩터 V/Q/G/M 재검증 — production-faithful (recent_ca 페널티 포함, 2026-06-29).
state/ JSON에 저장된 recent_ca=1 플래그로 점수에 -0.3 재적용(overlay_pre에 주입).
turbo_simulator.py 무수정(생성 후 패치). VALIDATE=1이면 풀기간 prod config on/off만."""
import sys, io, os, glob, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECENT_CA_W = 0.3  # production FACTOR_RECENT_CA_W

def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan).apply(ba)
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

def patch_ca(t, ar_dict):
    """생성된 TurboSim의 overlay_pre에 -0.3*recent_ca 주입 (production 정합). 반영 종목 수 반환."""
    cnt=0
    for date, arr in t._overlay_pre.items():
        if arr is None: continue
        rk = ar_dict.get(date)
        if rk is None: continue
        for j, s in enumerate(rk):
            rc = s.get('recent_ca')
            if rc:
                arr[j] -= RECENT_CA_W * float(rc); cnt+=1
    return cnt

PROD=(15,0,55,30)
ar_all,d_all=load('state')

def bt(sub, vqgm, ca=True):
    reg=calc_reg(sub); sd={d:ar_all[d] for d in sub}
    t=TurboSimulator(sd, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    nca = patch_ca(t, sd) if ca else 0
    v,q,g,m=vqgm
    t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('cagr',0),r.get('mdd',0),r.get('total',0),nca

if os.environ.get('VALIDATE'):
    sub=[d for d in d_all if '20190102'<=d<='20261231']
    off=bt(sub,PROD,ca=False); on=bt(sub,PROD,ca=True)
    print(f"[검증] state full {sub[0]}~{sub[-1]} {len(sub)}일, prod V15Q0G55M30")
    print(f"  recent_ca OFF(이전측정) : Calmar {off[0]:.3f}  MDD {off[2]:.1f}%  누적 {off[3]:.0f}%")
    print(f"  recent_ca ON (faithful) : Calmar {on[0]:.3f}  MDD {on[2]:.1f}%  누적 {on[3]:.0f}%  (페널티 반영 {on[4]}건)")
    print(f"  → ON이 문서 production(~4.05~4.24)에 근접하면 패치 정상")
    sys.exit()

# 풀 그리드
combos=sorted({(v,q,g,100-v-q-g) for v in [0,10,15,20,25,30]
               for q in [0,5,10] for g in range(30,71,5)
               if 10<=100-v-q-g<=45 and 30<=g<=70})
if PROD not in combos: combos.append(PROD)
PERIODS=[('2026단독','20260101','20261231'),('full(19-26)','20190102','20261231'),
         ('2024-26','20240101','20261231'),('정상+약세19-23','20190102','20231231'),
         ('약세22-23','20220101','20231231')]
_only=os.environ.get('ONLY_PERIOD')
if _only: PERIODS=[p for p in PERIODS if p[0]==_only]
print(f"production = V15 Q0 G55 M30 (boost) | recent_ca 페널티 ON | {len(combos)}조합 × {len(PERIODS)}기간\n")
for nm,lo,hi in PERIODS:
    sub=[d for d in d_all if lo<=d<=hi]
    if len(sub)<20: continue
    t0=time.time()
    reg=calc_reg(sub); sd={d:ar_all[d] for d in sub}
    t=TurboSimulator(sd, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    patch_ca(t, sd)
    res={}
    for v,q,g,m in combos:
        t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
        flat=list(t._cached_flat)
        r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
        res[(v,q,g,m)]=(r.get('calmar',0),r.get('cagr',0),r.get('mdd',0),r.get('total',0))
    short = nm.startswith('2026')
    key=(lambda kv:-kv[1][3]) if short else (lambda kv:-kv[1][0])
    ranked=sorted(res.items(), key=key)
    pcal,pcg,pmd,ptot=res[PROD]; prank=[c for c,_ in ranked].index(PROD)+1
    bc,(bcal,bcg,bmd,btot)=ranked[0]
    print(f"== {nm} [{sub[0]}~{sub[-1]} {len(sub)}일] ({time.time()-t0:.0f}s) ==")
    metric='누적수익률(짧은창)' if short else 'Calmar'
    print(f"  production V15Q0G55M30 : Calmar {pcal:.2f}  누적 {ptot:.0f}%  MDD {pmd:.1f}%  → {metric}기준 {prank}/{len(combos)}위")
    print(f"  기간 best  V{bc[0]}Q{bc[1]}G{bc[2]}M{bc[3]} : Calmar {bcal:.2f}  누적 {btot:.0f}%  MDD {bmd:.1f}%")
    for c,(cal,cg,md,tot) in ranked[:5]:
        print(f"     V{c[0]}Q{c[1]}G{c[2]}M{c[3]}  Cal {cal:.2f}  누적 {tot:.0f}%  MDD {md:.1f}%{'  ←prod' if c==PROD else ''}")
    print()
