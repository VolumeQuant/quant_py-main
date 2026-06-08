# -*- coding: utf-8 -*-
"""진입/이탈/슬롯 robust 최적화 — raw Cal 아닌 LOO-최악 + OOS로 줄세움.
단일 최고점(과적합) 대신 robust 영역 탐색. v80.23 baseline."""
import sys, json, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt'); PENALTY=50;TOP_N=20;W=0.2
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
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
_P={}
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    v=ohlcv.at[ts,tk] if tk in ohlcv.columns else None
    return v if (v is not None and pd.notna(v) and v>0) else None
# crc 4 exclusion 세트 사전계산
EXC={'full':None,'-033':{'033100'},'-660':{'000660'},'-both':{'033100','000660'}}
CRC={}
for k,exc in EXC.items():
    CRC[k]={d:{tk:i+1 for i,(tk,_) in enumerate(sorted([r for r in RAW[d] if not(exc and r[0] in exc)],key=lambda x:-x[1]))} for d in RAW}
def run(crc,EB,XB,SLOTS,sub=None):
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
    if len(ea)<30: return 0
    cagr=(ea[-1]**(252/len(ea))-1)*100;p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    return cagr/mdd if mdd>0 else 0
res=[]
for EB in [2,3,4]:
    for XB in [4,5,6,7,8,10]:
        for SLOTS in [2,3,4]:
            if EB>SLOTS or XB<EB: continue
            cals={k:run(CRC[k],EB,XB,SLOTS) for k in EXC}
            loomin=min(cals.values())
            is_c=run(CRC['full'],EB,XB,SLOTS,('20190102','20221231'))
            oos_c=run(CRC['full'],EB,XB,SLOTS,('20230102','20260605'))
            res.append({'E':EB,'X':XB,'S':SLOTS,'cal':cals['full'],'loomin':loomin,
                        'IS':is_c,'OOS':oos_c,'robust':min(loomin,oos_c,is_c)})
df=pd.DataFrame(res)
cur=df[(df.E==3)&(df.X==4)&(df.S==3)].iloc[0]
print(f'현재 E3/X4/S3: Cal {cur.cal:.2f} | LOO최악 {cur.loomin:.2f} | IS {cur.IS:.2f} | OOS {cur.OOS:.2f}')
print(f'\n=== robust 기준(LOO최악+IS+OOS 중 최소) 상위 10 ===')
print(f'{"E":>2}{"X":>3}{"S":>3}{"Cal":>7}{"LOO최악":>8}{"IS":>7}{"OOS":>7}{"robust":>8}')
for r in df.nlargest(10,'robust').to_dict('records'):
    mk=' ←현재' if (r['E']==3 and r['X']==4 and r['S']==3) else (' ★X6' if (r['E']==3 and r['X']==6 and r['S']==3) else '')
    print(f"{r['E']:>2}{r['X']:>3}{r['S']:>3}{r['cal']:>7.2f}{r['loomin']:>8.2f}{r['IS']:>7.2f}{r['OOS']:>7.2f}{r['robust']:>8.2f}{mk}")
print(f'\n=== raw Cal 상위 5 (비교 — 과적합 점검) ===')
for r in df.nlargest(5,'cal').to_dict('records'):
    print(f"  E{r['E']}/X{r['X']}/S{r['S']}: Cal {r['cal']:.2f} but LOO최악 {r['loomin']:.2f}")
df.to_csv('backtest/_q4_robust.csv',index=False)
