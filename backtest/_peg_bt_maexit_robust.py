# -*- coding: utf-8 -*-
"""MA60 이탈매도 robustness (gross, 비용 0). v80.23 과열캡 baseline.
① MA윈도우 인접(50/55/60/65/70) ② WF블록 ③ LOO(슈퍼위너 제외)."""
import sys, json, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt')
PENALTY=50;TOP_N=20;EB=3;SLOTS=3;XB=4;W=0.2
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
tdm=ohlcv.notna().sum(axis=1)>=(ohlcv.shape[1]*0.5); px=ohlcv.loc[tdm]
MA={N:px.rolling(N,min_periods=int(N*0.67)).mean() for N in [50,55,60,65,70]}
RAW={}
for f in sorted(PEG.glob('ranking_*.json')):
    ds=f.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8 and '20190102'<=ds<='20260605'): continue
    rows=json.load(open(f,encoding='utf-8')).get('rankings',[])
    if rows: RAW[ds]=[(str(r['ticker']).zfill(6),(r.get('score',0.0)or 0.0)+W*(r.get('overheat_pen',0.0)or 0.0)) for r in rows]
AD=sorted(RAW)
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
def below(d,tk,N):
    ts=pd.Timestamp(d)
    if tk not in px.columns: return False
    idx=px.index.searchsorted(ts,side='right')-1
    if idx<0: return False
    tsv=px.index[idx]; c=px.at[tsv,tk]; m=MA[N].at[tsv,tk]
    return (not pd.isna(c) and not pd.isna(m) and m>0 and c<m)
def crc_for(exclude):
    return {d:{tk:i+1 for i,(tk,_) in enumerate(sorted([r for r in RAW[d] if not(exclude and r[0] in exclude)],key=lambda x:-x[1]))} for d in RAW}
def run(ma_n, exclude=None, wf_detail=False):
    crc=crc_for(exclude); pf={};eq=1.0;eh={}
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
            if wr.get(tk,999)>xr or (ma_n and below(d,tk,ma_n)): del pf[tk]
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf or len(pf)>=SLOTS: continue
            if gp(d,tk): pf[tk]=gp(d,tk)
    ea=np.array(list(eh.values()))
    cagr=(ea[-1]**(252/len(ea))-1)*100;p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    cal=cagr/mdd if mdd>0 else 0
    if not wf_detail: return cal,cagr,mdd
    es=pd.Series(eh);wf=[]
    for st,ed in [('20190102','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260605')]:
        sub=es[(es.index>=st)&(es.index<=ed)]
        if len(sub)<50: continue
        sr=(sub.iloc[-1]/sub.iloc[0])**(252/len(sub))-1
        sp=np.maximum.accumulate(sub.values);sd=-((sub.values-sp)/sp).min()
        wf.append(round((sr*100)/(sd*100),2) if sd>0 else 0)
    return cal,cagr,mdd,wf

print('① MA 윈도우 인접안정성 (Cal, gross) — 60이 plateau인가')
base=run(None)[0]
print(f'  baseline(매도 wr>4): Cal {base:.3f}')
cals=[]
for N in [50,55,60,65,70]:
    c=run(N)[0]; cals.append(c)
    print(f'  +MA{N} 이탈매도: Cal {c:.3f}  (Δ{c-base:+.3f})')
print(f'  → MA50~70 Cal std {np.std(cals):.3f}, CV {np.std(cals)/np.mean(cals):.3f}')

print('\n② WF 블록 (2019/20-21/22-23/24-26)')
for nm,man in [('baseline',None),('+MA60',60)]:
    r=run(man,wf_detail=True)
    print(f'  {nm:<10} Cal {r[0]:.3f} | WF {r[3]}')

print('\n③ LOO robustness — ΔCal(MA60 vs baseline), 동일 종목 제외')
print(f'  {"제외":<12}{"baseline":>10}{"+MA60":>9}{"ΔCal":>8}')
for nm,exc in [('전체',None),('-제룡전기',{'033100'}),('-SK하이닉스',{'000660'}),('-둘다',{'033100','000660'})]:
    b=run(None,exc)[0]; m=run(60,exc)[0]
    print(f'  {nm:<12}{b:>10.3f}{m:>9.3f}{m-b:>+8.3f}')
