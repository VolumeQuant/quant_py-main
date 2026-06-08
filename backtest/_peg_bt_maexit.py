# -*- coding: utf-8 -*-
"""MA60/MA120 이탈 매도 BT — v80.23(과열캡 W=0.2) baseline에 추세이탈 매도 추가.
baseline 매도: wr>4 단독. 변형: wr>4 OR 종가<MA_N. (+재진입 차단 옵션)
production-replay (MA20x80x5 국면, 진입3/슬롯3). state_peg_bt cr(W=0.2)."""
import sys, json, time, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt')
PENALTY=50; TOP_N=20; EB=3; SLOTS=3; XB=4; W=0.2
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
# 거래일만 (>=50% 종목 가격 있는 행) → MA 계산
td_mask=ohlcv.notna().sum(axis=1)>=(ohlcv.shape[1]*0.5)
px=ohlcv.loc[td_mask]
MA={60:px.rolling(60,min_periods=40).mean(), 120:px.rolling(120,min_periods=80).mean()}
print(f'거래일 {len(px)} MA 계산 완료 {time.time()-t0:.0f}s',flush=True)

RAW={}
for f in sorted(PEG.glob('ranking_*.json')):
    ds=f.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8 and '20190102'<=ds<='20260605'): continue
    d=json.load(open(f,encoding='utf-8')); rows=d.get('rankings',[])
    if not rows: continue
    RAW[ds]=[(str(r['ticker']).zfill(6), (r.get('score',0.0) or 0.0)+W*(r.get('overheat_pen',0.0) or 0.0)) for r in rows]
ADATES=sorted(RAW.keys())
crc={d:{tk:i+1 for i,(tk,_) in enumerate(sorted(RAW[d],key=lambda x:-x[1]))} for d in RAW}
print(f'{len(ADATES)}일 cr 계산 {time.time()-t0:.0f}s',flush=True)

def regime_cross(ds_list):
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
reg=regime_cross(ADATES)
_pcache={}
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    v=ohlcv.at[ts,tk] if tk in ohlcv.columns else None
    return v if (v is not None and pd.notna(v) and v>0) else None
def below_ma(d,tk,N):
    """종가 < MA_N 이면 True (추세이탈)."""
    ts=pd.Timestamp(d)
    if tk not in px.columns: return False
    # 해당일 이하 마지막 거래일
    idx=px.index.searchsorted(ts, side='right')-1
    if idx<0: return False
    tsv=px.index[idx]
    c=px.at[tsv,tk]; m=MA[N].at[tsv,tk]
    if pd.isna(c) or pd.isna(m) or m<=0: return False
    return c<m

def run(ma_n=None, block_reentry=False):
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
        cr0=crc.get(d,{});cr1=crc.get(ADATES[i-1],{}) if i>=1 else {};cr2=crc.get(ADATES[i-2],{}) if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c in cr0.items()}
        # 매도: wr>4 OR (ma_n 이탈)
        for tk in list(pf.keys()):
            sell = wr.get(tk,999)>xr
            if ma_n and not sell and below_ma(d,tk,ma_n): sell=True
            if sell: del pf[tk]; turn+=1
        # 진입
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if len(pf)>=SLOTS: break
            if block_reentry and ma_n and below_ma(d,tk,ma_n): continue  # 추세이탈 종목 진입 차단
            cp=gp(d,tk)
            if cp: pf[tk]=cp; turn+=1
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

print('\n=== MA 이탈 매도 BT (v80.23 과열캡 baseline) ===')
print(f'{"매도룰":<26}{"Cal":>7}{"CAGR":>7}{"MDD":>7}{"WFmin":>7}{"회전":>7}')
configs=[('baseline (wr>4 단독)',None,False),
         ('+ MA60 이탈매도',60,False),
         ('+ MA60 이탈매도+재진입차단',60,True),
         ('+ MA120 이탈매도',120,False),
         ('+ MA120 이탈매도+재진입차단',120,True)]
for nm,man,blk in configs:
    c,cg,m,wf,tn=run(man,blk)
    print(f'{nm:<26}{c:>7.3f}{cg:>6.1f}%{m:>6.2f}%{wf:>7.3f}{tn:>7}',flush=True)
print(f'\n총 {time.time()-t0:.0f}s')
