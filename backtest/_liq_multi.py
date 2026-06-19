# -*- coding: utf-8 -*-
"""다변량 유동성 필터 BT — 성과 개선 케이스 탐색. v80.24 baseline(E3/X6/S3, W0.2).
각도: 거래대금 극단tail / 회전율(거래대금÷시총, 작전 고회전 제외) / 스파이크비(20d÷250d, 펌프 제외) / 조합."""
import sys, json, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt'); PENALTY=50;TOP_N=20;W=0.2; EB,XB,SLOTS=3,6,3
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
# 패널
val=pd.read_parquet('backtest/_liq_value_eok.parquet'); val.index=pd.to_datetime(val.index)  # 거래대금 억
cap=pd.read_parquet('backtest/_liq_cap.parquet'); cap.index=pd.to_datetime(cap.index)         # 시총 원
valM={w:val.rolling(w,min_periods=int(w*0.5)).mean() for w in [20,120,250]}
turnover=(val*1e8)/cap.reindex_like(val)           # 일별 회전율(거래대금/시총)
turnM20=turnover.rolling(20,min_periods=10).mean()
spike=valM[20]/valM[250]                            # 스파이크비 (최근20d / 구조적250d)
def getp(panel,d,tk):
    if d not in panel.index or tk not in panel.columns: return None
    v=panel.at[d,tk]
    return None if pd.isna(v) else v
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
def keep(d,tk,spec):
    dt=pd.Timestamp(d); kind=spec[0]
    if kind=='none': return True
    if kind=='valfloor':
        v=getp(valM[spec[1]],dt,tk); return v is None or v>=spec[2]   # 데이터없으면 통과
    if kind=='turnhi':   # 고회전(작전) 제외
        v=getp(turnM20,dt,tk); return v is None or v<=spec[1]
    if kind=='turnlo':   # 저회전(방치) 제외
        v=getp(turnM20,dt,tk); return v is None or v>=spec[1]
    if kind=='spikehi':  # 펌프(20d>>250d) 제외
        v=getp(spike,dt,tk); return v is None or v<=spec[1]
    if kind=='combo':    # val250>=a AND spike<=b
        v1=getp(valM[250],dt,tk); v2=getp(spike,dt,tk)
        return (v1 is None or v1>=spec[1]) and (v2 is None or v2<=spec[2])
    return True
def run(spec,sub=None):
    crc={}
    for d,rows in RAW.items():
        items=sorted([(tk,sc) for (tk,sc) in rows if keep(d,tk,spec)],key=lambda x:-x[1])
        crc[d]={tk:i+1 for i,(tk,_) in enumerate(items)}
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
base=run(('none',))
print(f'baseline E3/X6/S3: Cal {base[0]:.3f} CAGR {base[1]:.1f}% MDD {base[2]:.2f}% 회전 {base[3]}\n')
variants=[
 ('거래대금250d≥5억',('valfloor',250,5)),('거래대금250d≥8억',('valfloor',250,8)),
 ('거래대금250d≥12억',('valfloor',250,12)),
 ('거래대금120d≥5억',('valfloor',120,5)),('거래대금120d≥8억',('valfloor',120,8)),
 ('거래대금120d≥10억',('valfloor',120,10)),('거래대금120d≥12억',('valfloor',120,12)),
 ('거래대금20d≥10억',('valfloor',20,10)),('거래대금20d≥20억',('valfloor',20,20)),
 ('회전율>30%제외',('turnhi',0.30)),('회전율>20%제외',('turnhi',0.20)),('회전율>15%제외',('turnhi',0.15)),
 ('회전율<0.5%제외',('turnlo',0.005)),('회전율<1%제외',('turnlo',0.01)),
 ('스파이크>10배제외',('spikehi',10)),('스파이크>5배제외',('spikehi',5)),('스파이크>3배제외',('spikehi',3)),
 ('조합 250≥8&스파이크≤5',('combo',8,5)),('조합 120≥8&스파이크≤8',('combo',8,8)),
]
print(f'{"필터":<24}{"Cal":>8}{"Δ":>8}{"MDD":>8}{"회전":>7}')
for nm,spec in variants:
    c,cg,m,t=run(spec)
    flag=' ★' if c-base[0]>0.10 else (' +' if c>base[0] else '')
    print(f'{nm:<24}{c:>8.3f}{c-base[0]:>+8.3f}{m:>7.2f}%{t:>7}{flag}')
