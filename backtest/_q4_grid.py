# -*- coding: utf-8 -*-
"""진입(E)/이탈(X)/슬롯(S) 그리드 최적화 — v80.23(과열캡 W=0.2) baseline.
현재 E3/X4/S3가 최적인지 검증. production-replay (state_peg_bt cr(W=0.2))."""
import sys, json, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt')
PENALTY=50;TOP_N=20;W=0.2
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
RAW={}
for f in sorted(PEG.glob('ranking_*.json')):
    ds=f.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8 and '20190102'<=ds<='20260605'): continue
    rows=json.load(open(f,encoding='utf-8')).get('rankings',[])
    if rows: RAW[ds]=[(str(r['ticker']).zfill(6),(r.get('score',0.0)or 0.0)+W*(r.get('overheat_pen',0.0)or 0.0)) for r in rows]
AD=sorted(RAW); crc={d:{tk:i+1 for i,(tk,_) in enumerate(sorted(RAW[d],key=lambda x:-x[1]))} for d in RAW}
def reg_f():
    sma=kospi.rolling(20).mean();lma=kospi.rolling(80).mean();r={};md=False;stk=0;ss=None
    for d in AD:
        ts=pd.Timestamp(d);sv=sma.get(ts);lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): r[d]=md;continue
        s=sv>lv; stk=stk+1 if s==ss else 1; ss=s
        if stk>=5 and md!=s: md=s
        r[d]=md
    return r
reg=reg_f()
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    v=ohlcv.at[ts,tk] if tk in ohlcv.columns else None
    return v if (v is not None and pd.notna(v) and v>0) else None
def run(EB,XB,SLOTS,wf=False):
    pf={};eq=1.0;eh={};turn=0
    for i,d in enumerate(AD):
        ib=reg.get(d,True);er=EB if ib else 0;xr=XB if ib else 8
        if i>=1 and pf:
            rs=[gp(d,tk)/gp(AD[i-1],tk)-1 for tk in pf if gp(AD[i-1],tk) and gp(d,tk)]
            if rs: eq*=(1+np.mean(rs)*len(pf)/SLOTS)
        eh[d]=eq
        if i>=1 and reg.get(AD[i-1],True)!=ib: pf.clear()
        if not ib: continue
        cr0=crc.get(d,{});cr1=crc.get(AD[i-1],{}) if i>=1 else {};cr2=crc.get(AD[i-2],{}) if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk]; turn+=1
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf or len(pf)>=SLOTS: continue
            if gp(d,tk): pf[tk]=gp(d,tk); turn+=1
    ea=np.array(list(eh.values()))
    cagr=(ea[-1]**(252/len(ea))-1)*100;p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    cal=cagr/mdd if mdd>0 else 0
    if not wf: return cal,cagr,mdd,turn
    es=pd.Series(eh);wfb=[]
    for st,ed in [('20190102','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260605')]:
        sub=es[(es.index>=st)&(es.index<=ed)]
        if len(sub)<50: continue
        sr=(sub.iloc[-1]/sub.iloc[0])**(252/len(sub))-1; sp=np.maximum.accumulate(sub.values);sd=-((sub.values-sp)/sp).min()
        wfb.append((sr*100)/(sd*100) if sd>0 else 0)
    return cal,cagr,mdd,turn,(min(wfb) if wfb else 0)
res=[]
for EB in [2,3,4,5]:
    for XB in [4,5,6,8,10]:
        for SLOTS in [2,3,4,5]:
            if EB>SLOTS or XB<EB: continue
            c,cg,m,t=run(EB,XB,SLOTS)
            res.append({'E':EB,'X':XB,'S':SLOTS,'cal':c,'cagr':cg,'mdd':m,'turn':t})
df=pd.DataFrame(res)
cur=df[(df.E==3)&(df.X==4)&(df.S==3)].iloc[0]
print(f'현재 E3/X4/S3: Cal {cur.cal:.3f} CAGR {cur.cagr:.1f}% MDD {cur.mdd:.2f}% 회전 {int(cur.turn)}')
print(f'\n=== Cal 상위 12 조합 ===')
print(f'{"E":>2}{"X":>3}{"S":>3}{"Cal":>8}{"CAGR":>8}{"MDD":>8}{"회전":>7}')
for r in df.nlargest(12,'cal').to_dict('records'):
    mk=' ←현재' if (r['E']==3 and r['X']==4 and r['S']==3) else ''
    print(f"{r['E']:>2}{r['X']:>3}{r['S']:>3}{r['cal']:>8.3f}{r['cagr']:>7.1f}%{r['mdd']:>7.2f}%{int(r['turn']):>7}{mk}")
df.to_csv('backtest/_q4_grid_results.csv',index=False)
print(f'\n현재 순위: Cal 기준 {(df.cal>cur.cal).sum()+1}위 / {len(df)}조합')
PYEOF=None