# -*- coding: utf-8 -*-
"""공매도 잔고비율 필터 BT — v80.24 baseline(E3/X6/S3, W0.2).
가설: 높은 숏 잔고비율 종목(작전·스퀴즈 위험) 거르면 개선? 양방향(고숏/저숏) + 픽 EDA."""
import sys, json, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt'); PENALTY=50;TOP_N=20;W=0.2; EB,XB,SLOTS=3,6,3
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
short=pd.read_parquet('backtest/_short_balance.parquet')  # date×ticker 잔고비율%
short.index=pd.to_datetime(short.index); short=short.sort_index()
RAW={}
for f in sorted(PEG.glob('ranking_*.json')):
    ds=f.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8 and '20190102'<=ds<='20260605'): continue
    rows=json.load(open(f,encoding='utf-8')).get('rankings',[])
    if rows: RAW[ds]=[(str(r['ticker']).zfill(6),r.get('name',''),(r.get('score',0.0)or 0.0)+W*(r.get('overheat_pen',0.0)or 0.0)) for r in rows]
AD=sorted(RAW)
# 주간→일별 ffill (각 거래일에 가장 최근 스냅샷)
sf=short.reindex(pd.to_datetime(AD), method='ffill')
def sratio(d,tk):
    dt=pd.Timestamp(d)
    if dt not in sf.index or tk not in sf.columns: return None
    v=sf.at[dt,tk]
    return None if pd.isna(v) else v
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
def keep(d,tk,mode,thr):
    if mode=='none': return True
    v=sratio(d,tk)
    if v is None: return True   # 데이터없으면 통과(보수)
    if mode=='hi': return v<=thr   # 고숏 제외
    if mode=='lo': return v>=thr   # 저숏 제외
    return True
def run(mode,thr,exclude=None,sub=None):
    crc={}
    for d,rows in RAW.items():
        items=sorted([(tk,sc) for (tk,nm,sc) in rows if keep(d,tk,mode,thr) and not(exclude and tk in exclude)],key=lambda x:-x[1])
        crc[d]={tk:i+1 for i,(tk,_) in enumerate(items)}
    pf={};eq=1.0;eh={}
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
            if wr.get(tk,999)>xr: del pf[tk]
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf or len(pf)>=SLOTS: continue
            if gp(d,tk): pf[tk]=gp(d,tk)
    ea=np.array(list(eh.values()))
    if len(ea)<30: return 0,0,0
    cagr=(ea[-1]**(252/len(ea))-1)*100;p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    return cagr/mdd if mdd>0 else 0,cagr,mdd

# 데이터 커버리지
print(f'공매도 패널: {short.shape[0]}일 ({short.index[0].date()}~{short.index[-1].date()}) × {short.shape[1]}종목')
cov=sum(1 for d in AD for (tk,nm,sc) in RAW[d][:30] if sratio(d,tk) is not None)
tot=sum(min(30,len(RAW[d])) for d in AD)
print(f'상위30 픽 공매도 커버리지: {cov*100//tot}%')

# EDA: 픽(top3)의 숏 잔고비율 분포
print('\n① 진입픽(top3) 숏 잔고비율 분포')
vals=[]
crc0={d:{tk:i+1 for i,(tk,_,_) in enumerate(sorted(RAW[d],key=lambda x:-x[2]))} for d in AD}
for i,d in enumerate(AD):
    if i<2: continue
    cr0=crc0[d];cr1=crc0[AD[i-1]];cr2=crc0[AD[i-2]]
    t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
    wr={tk:c*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c in cr0.items()}
    for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:3]:
        v=sratio(d,tk)
        if v is not None: vals.append(v)
vals=np.array(vals)
if len(vals):
    print(f'  중앙 {np.median(vals):.2f}% | p75 {np.percentile(vals,75):.2f}% | p90 {np.percentile(vals,90):.2f}% | >5% {np.mean(vals>5)*100:.0f}% | >8% {np.mean(vals>8)*100:.0f}%')

base=run('none',0)
print(f'\nbaseline: Cal {base[0]:.3f} MDD {base[2]:.2f}%')
print('② 고숏 제외 필터')
print(f'{"임계":>8}{"Cal":>8}{"Δ":>8}{"MDD":>8}')
for thr in [3,5,8,10,15]:
    c,cg,m=run('hi',thr)
    fl=' ★' if c-base[0]>0.10 else (' +' if c>base[0] else '')
    print(f'  >{thr}%제외{c:>8.3f}{c-base[0]:>+8.3f}{m:>7.2f}%{fl}')
print('③ 저숏 제외 (역방향 확인)')
for thr in [1,2]:
    c,cg,m=run('lo',thr)
    print(f'  <{thr}%제외{c:>8.3f}{c-base[0]:>+8.3f}{m:>7.2f}%')
