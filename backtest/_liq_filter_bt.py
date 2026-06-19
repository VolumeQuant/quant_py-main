# -*- coding: utf-8 -*-
"""장기윈도우 거래대금 필터 BT — v80.24 baseline(E3/X6/S3, W0.2).
20d 필터(현행)가 못 거르는 spike-inflated 종목을 120d/250d로 필터.
필터: 후보 중 거래대금 MA_w < 임계 제외 → 재랭킹 → 매매."""
import sys, json, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt'); PENALTY=50;TOP_N=20;W=0.2
EB,XB,SLOTS=3,6,3
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
MA={w:pd.read_parquet(f'backtest/_liq_ma{w}_eok.parquet') for w in [20,60,120,250]}
for w in MA: MA[w].index=pd.to_datetime(MA[w].index)
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
def liq_ok(d,tk,w,thr):
    if thr<=0: return True
    dt=pd.Timestamp(d); m=MA[w]
    if dt not in m.index or tk not in m.columns: return True  # 데이터 없으면 통과(보수)
    v=m.at[dt,tk]
    return (pd.isna(v)) or (v>=thr)  # NaN이면 통과
def crc_filt(w,thr,exclude=None):
    crc={}
    for d,rows in RAW.items():
        items=[(tk,sc) for (tk,sc) in rows if liq_ok(d,tk,w,thr) and not(exclude and tk in exclude)]
        items.sort(key=lambda x:-x[1])
        crc[d]={tk:i+1 for i,(tk,_) in enumerate(items)}
    return crc
def run(crc,sub=None):
    pf={};eq=1.0;eh={};turn=0
    rng=AD if sub is None else [d for d in AD if sub[0]<=d<=sub[1]]
    for i,d in enumerate(rng):
        ib=reg.get(d,True);er=EB if ib else 0;xr=XB if ib else 8
        if i>=1 and pf:
            rs=[gp(d,tk)/gp(rng[i-1],tk)-1 for tk in pf if gp(rng[i-1],tk) and gp(d,tk)]
            if rs: eq*=(1+np.mean(rs)*len(pf)/SLOTS)
        eh[d]=eq
        if i>=1 and reg.get(rng[i-1],True)!=ib: pf.clear()
        if not ib: continue
        cr0=crc.get(d,{});cr1=crc.get(rng[i-1],{}) if i>=1 else {};cr2=crc.get(rng[i-2],{}) if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk]; turn+=1
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf or len(pf)>=SLOTS: continue
            if gp(d,tk): pf[tk]=gp(d,tk); turn+=1
    ea=np.array(list(eh.values()))
    if len(ea)<30: return 0,0,0,0
    cagr=(ea[-1]**(252/len(ea))-1)*100;p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    return cagr/mdd if mdd>0 else 0,cagr,mdd,turn
base=run(crc_filt(20,0))  # 필터 없음 = 현행(state_peg_bt 유니버스필터만)
print(f'baseline (현행, 추가필터X): Cal {base[0]:.3f} CAGR {base[1]:.1f}% MDD {base[2]:.2f}% 회전 {base[3]}')
print(f'\n=== 장기윈도우 거래대금 최소 필터 (Cal / MDD / 회전) ===')
print(f'{"윈도우":>6}{"임계억":>7}{"Cal":>8}{"MDD":>8}{"회전":>7}{"IS":>7}{"OOS":>8}')
for w in [120,250]:
    for thr in [30,50,75,100,150]:
        crc=crc_filt(w,thr)
        c,cg,m,t=run(crc)
        isc=run(crc,('20190102','20221231'))[0]; oosc=run(crc,('20230102','20260605'))[0]
        print(f'{w:>6}{thr:>7}{c:>8.3f}{m:>7.2f}%{t:>7}{isc:>7.2f}{oosc:>8.2f}')
