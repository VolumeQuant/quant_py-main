import sqlite3, sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT='C:/dev'
px=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan); px=px.dropna(how='all')
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)};parr=px.values;pcol={c:i for i,c in enumerate(px.columns)}
# EPS 랭킹
c=sqlite3.connect(ROOT+'/kr_eps_momentum/eps_momentum_data_kr.db')
edf=pd.read_sql('SELECT date,ticker,composite_rank FROM ntm_screening',c)
edf['tk']=edf['ticker'].str[:6];edf['d8']=edf['date'].str.replace('-','')
edays=sorted([d for d in edf['d8'].unique() if d in tdi])
erk={d:dict(zip(edf[edf['d8']==d]['tk'],edf[edf['d8']==d]['composite_rank'])) for d in edays}
# production 랭킹 (state, 같은 날짜)
prk={}
for f in sorted(glob.glob(ROOT+'/state/ranking_*.json')):
    d=os.path.basename(f)[8:16]
    if d in edays:
        rk=sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99))
        prk[d]={x['ticker']:j+1 for j,x in enumerate(rk)}
pdays=[d for d in edays if d in prk]
days=pdays  # 공통 날짜
def ret(t,d0,d1):
    if t not in pcol: return 0.0
    p0=parr[tdi[d0],pcol[t]];p1=parr[tdi[d1],pcol[t]]
    return (p1/p0-1) if p0>0 and p1>0 else 0.0
def sim(rkmap,entry,exit_,slots,dd):
    held=[];eq=1.0;prev=None;a=[]
    for d in dd:
        if prev:
            r=np.mean([ret(t,prev,d) for t in held]) if held else 0.0;eq*=(1+r);a.append(r)
        rr=rkmap.get(d,{})
        held=[t for t in held if rr.get(t,999)<=exit_]
        for t in sorted([t for t in rr if rr[t]<=entry and t not in held],key=lambda t:rr[t]):
            if len(held)>=slots: break
            held.append(t)
        prev=d
    a=np.array(a);e=np.cumprod(1+a);pk=np.maximum.accumulate(e);mdd=((e-pk)/pk).min()*100 if len(e) else 0
    return (eq-1)*100,mdd
print(f"=== production vs EPS — 같은 {len(days)}일 ({days[0]}~{days[-1]}), 동일 하네스 ===")
print(f"  ※ 16일·단일 약세에피소드 = 예비\n")
bench=np.mean([ret(t,days[0],days[-1]) for t in erk[days[0]]])*100
print(f"  벤치(유니버스 buy&hold): {bench:+.1f}%\n")
print(f"  {'진입/이탈/슬롯':16s}{'production':>12s}{'EPS':>10s}{'우위':>8s}")
for e,x,s in [(3,6,3),(5,10,5),(3,10,3),(1,5,3)]:
    pc,pm=sim(prk,e,x,s,days);ec,em=sim(erk,e,x,s,days)
    print(f"  E{e} X{x} S{s:<9d}{pc:>+10.1f}%{ec:>+9.1f}%{('prod' if pc>ec else 'EPS'):>8s}")
# production 실제 보유 (top3)
print(f"\n  production 실제 보유종목(최근일 top3):")
last=days[-1];rk=sorted(prk[last].items(),key=lambda z:z[1])[:3]
nm=json.load(open(ROOT+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
def nameof(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in nm: return nm[k].get('shortName',t)
    return t
for t,r in rk:
    print(f"    {nameof(t)[:12]:12s} {ret(t,days[0],days[-1])*100:+.0f}% (구간)")
