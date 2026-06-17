# -*- coding: utf-8 -*-
"""휩쏘 회피 연구 2단계: mom10 팩터가 휩쏘 원인인가? 빼면 Calmar는?
mom10 overlay(0.05) on/off로 ①Calmar(TurboSim) ②휩쏘건수(상태머신) 비교. _sp0b_co."""
import sys,io,glob,os,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator,_run_regime_inner
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r=s.pct_change(fill_method=None); ev=r[(r<-0.33)|(r>0.45)]; s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50: s2.loc[s2.index<d]*=f
    return s2
px=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]; ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
ar,days={}, []
for f in sorted(glob.glob(os.path.join(PROJ,'_sp0b_co','ranking_*.json'))):
    d=os.path.basename(f)[8:16]
    if d>='20190102': ar[d]=json.load(open(f,encoding='utf-8'))['rankings']; days.append(d)
days=sorted(days)
reg={};md=True;stk=0;ss=None
for d in days:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
    s=bool(ma20[ts]>ma80[ts]); stk=stk+1 if s==ss else 1; ss=s
    if stk>=5 and md!=s: md=s
    reg[d]=md
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
# ① Calmar: TurboSim mom10 on/off (overlay 재구성)
def calmar(mom10_w):
    t=TurboSimulator(ar,days,px,overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    # overlay_pre 재구성: 0.2*overheat + mom10_w*mom10 + 0.06*vollow
    for d in days:
        tks=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen') or 0)+mom10_w*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0) for tk in tks])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,days,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(days),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar'),r.get('cagr'),r.get('mdd')
# ② 휩쏘 건수: score에서 mom10 기여 빼고 재랭킹 → 상태머신
didx={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}; arr=px.values; cols={c:i for i,c in enumerate(px.columns)}
def rr(tk,d0,d1):
    ci=cols.get(tk); i0=didx.get(d0); i1=didx.get(d1)
    if ci is None or i0 is None or i1 is None: return None
    p0,p1=arr[i0,ci],arr[i1,ci]
    return (p1/p0-1) if p0>0 and p1>0 else None
def whipsaw(remove_mom10):
    # 일별 cr 재계산 (score - 0.05*mom10 if remove)
    CR={}
    for d in days:
        sc={}
        for x in ar[d]:
            s=x.get('score') or 0
            if remove_mom10: s-=0.05*(x.get('mom_10_z') or 0)
            sc[x['ticker']]=s
        order=sorted(sc,key=lambda t:-sc[t]); CR[d]={t:i+1 for i,t in enumerate(order)}
    wrrank={}
    for i,d in enumerate(days):
        c0=CR[d]; p1={t:r for t,r in (CR[days[i-1]] if i>=1 else {}).items() if r<=20}; p2={t:r for t,r in (CR[days[i-2]] if i>=2 else {}).items() if r<=20}
        wr={t:c0[t]*0.4+p1.get(t,50)*0.35+p2.get(t,50)*0.25 for t in c0}
        wrrank[d]={t:k+1 for k,t in enumerate(sorted(wr,key=lambda x:wr[x]))}
    hold={}; eps=[]
    for i,d in enumerate(days):
        if not reg[d]:
            for tk in list(hold): hold.pop(tk)
            continue
        wr=wrrank[d]
        for tk in list(hold):
            if wr.get(tk,999)>6: eps.append((tk,hold[tk],d)); hold.pop(tk)
        for tk,rk in wr.items():
            if rk<=3 and tk not in hold: hold[tk]=d
    n_ent=len(eps); rets=[(days.index(d1)-days.index(d0),rr(tk,d0,d1)) for tk,d0,d1 in eps]
    rets=[(du,r) for du,r in rets if r is not None]
    ws=[(du,r) for du,r in rets if du<=3]
    return n_ent, len(ws), np.mean([r for _,r in ws])*100 if ws else 0
print("① Calmar (mom10 overlay 가중치별):")
for w in [0.05,0.0,0.10]:
    c,cg,m=calmar(w); print(f"  mom10_w={w}: Calmar {c:.3f}  CAGR {cg:.0f}%  MDD {m:.1f}%" + (" ←현행" if w==0.05 else ""))
print("\n② 휩쏘(≤3일) 건수:")
for rm,l in [(False,'mom10 유지(현행)'),(True,'mom10 제거')]:
    ne,nw,wr=whipsaw(rm); print(f"  {l}: 진입 {ne}건, 휩쏘 {nw}건({nw/ne*100:.0f}%), 휩쏘평균 {wr:+.1f}%")
print("\n→ mom10 제거가 휩쏘 줄이고 Calmar 유지/상승이면 채택 검토. Calmar 하락이면 휩쏘는 mom10 효익의 비용(유지).")
