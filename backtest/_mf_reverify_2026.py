# -*- coding: utf-8 -*-
"""멀티팩터 V/Q/G/M 비율 재검증 (2026-06-29) — production state/ 재랭킹, 기간별 Calmar 그리드.
★사용자 요청: 2026년 단독부터. + full/2024-26/2019-23/bear(2022-23) 동시.
방법론(CLAUDE.md): 고정config 비교, max-selection 편향 경계 → production(V15Q0G55M30)의
각 기간 그리드 내 순위/백분위를 함께 보고. best-of-2026 채택은 과적합."""
import sys, io, os, glob, json, time
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

PROD=(15,0,55,30)
# 그리드: production 근방 + 넓게. 합=100, M>=10, G>=30
combos=sorted({(v,q,g,100-v-q-g) for v in [0,10,15,20,25,30]
               for q in [0,5,10] for g in range(30,71,5)
               if 10<=100-v-q-g<=45 and 30<=g<=70})
if PROD not in combos: combos.append(PROD)

ar_all,d_all=load('state')
PERIODS=[
 ('2026단독',  '20260101','20261231'),
 ('full(19-26)','20190102','20261231'),
 ('2024-26',   '20240101','20261231'),
 ('정상+약세19-23','20190102','20231231'),
 ('약세22-23', '20220101','20231231'),
]
def bt_on(sub):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar_all[d] for d in sub}, sub, prices, overheat_w=0.2)
    t._use_overlay=True; t._use_stored_growth=True
    out={}
    for v,q,g,m in combos:
        t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
        flat=list(t._cached_flat)
        r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
        out[(v,q,g,m)]=(r.get('calmar',0),r.get('cagr',0),r.get('mdd',0),r.get('total',0))  # cagr/mdd 이미 %
    return out

_only=os.environ.get('ONLY_PERIOD')
if _only: PERIODS=[p for p in PERIODS if p[0]==_only]
print(f"production = V15 Q0 G55 M30 (boost) | {len(combos)}조합 × {len(PERIODS)}기간\n")
for nm,lo,hi in PERIODS:
    sub=[d for d in d_all if lo<=d<=hi]
    if len(sub)<20: print(f"== {nm}: 데이터 부족({len(sub)}일) =="); continue
    t0=time.time(); res=bt_on(sub)
    short = nm.startswith('2026')  # 짧은 창은 누적수익률로 랭킹(연율 Calmar 폭발)
    key = (lambda kv:-kv[1][3]) if short else (lambda kv:-kv[1][0])
    ranked=sorted(res.items(), key=key)
    pcal,pcg,pmd,ptot=res[PROD]
    prank=[c for c,_ in ranked].index(PROD)+1
    bc,(bcal,bcg,bmd,btot)=ranked[0]
    print(f"== {nm} [{sub[0]}~{sub[-1]} {len(sub)}일] ({time.time()-t0:.0f}s) ==")
    metric = '누적수익률(연율Calmar 무의미)' if short else 'Calmar'
    print(f"  production V15Q0G55M30 : Calmar {pcal:.2f}  누적 {ptot:.0f}%  MDD {pmd:.1f}%  → {metric}기준 {prank}/{len(combos)}위 (상위 {prank/len(combos)*100:.0f}%)")
    print(f"  기간 best  V{bc[0]}Q{bc[1]}G{bc[2]}M{bc[3]} : Calmar {bcal:.2f}  누적 {btot:.0f}%  MDD {bmd:.1f}%")
    print("  top5:")
    for c,(cal,cg,md,tot) in ranked[:5]:
        star=' ←prod' if c==PROD else ''
        print(f"     V{c[0]}Q{c[1]}G{c[2]}M{c[3]}  Cal {cal:.2f}  누적 {tot:.0f}%  MDD {md:.1f}%{star}")
    print()
