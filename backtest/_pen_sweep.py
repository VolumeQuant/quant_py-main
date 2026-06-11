# -*- coding: utf-8 -*-
"""권외 벌점값(PENALTY) 스윕 BT — "50이 최적인가" 검증.
_oneoff_bt.py 하네스 재사용. baseline(mode none, W=0.2 overheat 포함 score) 고정,
오직 PENALTY만 변형: nocap(실제 cr 사용)/20/30/50/70/100.
wr = cr0*0.4 + cr1(>top_n면 PEN)*0.35 + cr2(>top_n면 PEN)*0.25
"""
import sys, json, time, glob, os
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt')
TOP_N=20; EB=3; SLOTS=3; XB=6; W=0.2
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)

RAW={}
for f in sorted(PEG.glob('ranking_*.json')):
    ds=f.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8 and '20190102'<=ds<='20260605'): continue
    d=json.load(open(f,encoding='utf-8')); rows=d.get('rankings',[])
    if not rows: continue
    RAW[ds]=[(str(r['ticker']).zfill(6),(r.get('score',0.0) or 0.0)+W*(r.get('overheat_pen',0.0) or 0.0)) for r in rows]
ADATES=sorted(RAW.keys())
print(f'{len(ADATES)}일 로드 {time.time()-t0:.0f}s',flush=True)

def regime_cross(ds_list,kospi):
    sma=kospi.rolling(20).mean();lma=kospi.rolling(80).mean();reg={};md=False;stk=0;ss=None
    for d in ds_list:
        ts=pd.Timestamp(d);sv=sma.get(ts);lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d]=md;continue
        s=sv>lv
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
reg=regime_cross(ADATES,kospi)
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    v=ohlcv.at[ts,tk] if tk in ohlcv.columns else None
    return v if (v is not None and pd.notna(v) and v>0) else None

# cr (full ranking, no cutoff)
CRC={}
for d in ADATES:
    CRC[d]={tk:i+1 for i,(tk,_) in enumerate(sorted(RAW[d],key=lambda x:-x[1]))}

def run(PENALTY, nocap=False):
    pf={};eq=1.0;eh={};turn=0
    for i,d in enumerate(ADATES):
        ib=reg.get(d,True);er=EB if ib else 0;xr=XB if ib else 8
        if i>=1 and pf:
            rs=[]
            for tk in pf:
                pp=gp(ADATES[i-1],tk);cp=gp(d,tk)
                if pp and cp: rs.append(cp/pp-1)
            if rs: eq*=(1+np.mean(rs)*len(pf)/SLOTS)
        eh[d]=eq
        if i>=1 and reg.get(ADATES[i-1],True)!=ib: pf.clear()
        if not ib: continue
        cr0=CRC.get(d,{});cr1=CRC.get(ADATES[i-1],{}) if i>=1 else {};cr2=CRC.get(ADATES[i-2],{}) if i>=2 else {}
        if nocap:
            # 실제 cr 사용 (top_n 캡 없음), 그날 유니버스에 없으면만 PENALTY
            t1=cr1; t2=cr2
        else:
            t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk];turn+=1
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if len(pf)>=SLOTS: break
            cp=gp(d,tk)
            if cp: pf[tk]=cp;turn+=1
    ea=np.array(list(eh.values()))
    cagr=(ea[-1]**(252/len(ea))-1)*100
    p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    cal=cagr/mdd if mdd>0 else 0
    es=pd.Series(eh);wf=[]
    for st,ed in [('20190102','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260605')]:
        sub=es[(es.index>=st)&(es.index<=ed)]
        if len(sub)<50: continue
        sr=(sub.iloc[-1]/sub.iloc[0])**(252/len(sub))-1
        sp=np.maximum.accumulate(sub.values);sd=-((sub.values-sp)/sp).min()
        wf.append((sr*100)/(sd*100) if sd>0 else 0)
    return cal,cagr,mdd,(min(wf) if wf else 0),turn

print(f'\n{"벌점값":<14}{"Cal":>7}{"CAGR":>8}{"MDD":>7}{"WFmin":>7}{"회전":>7}')
# nocap: 실제 cr
c,cg,m,wf,tn=run(50,nocap=True)
print(f'{"nocap(실제cr)":<14}{c:>7.3f}{cg:>7.1f}%{m:>6.1f}%{wf:>7.3f}{tn:>7}',flush=True)
for PEN in [20,30,50,70,100]:
    c,cg,m,wf,tn=run(PEN)
    star=' ←현행' if PEN==50 else ''
    print(f'{"PEN=%d"%PEN:<14}{c:>7.3f}{cg:>7.1f}%{m:>6.1f}%{wf:>7.3f}{tn:>7}{star}',flush=True)
print(f'\n총 {time.time()-t0:.0f}s')
