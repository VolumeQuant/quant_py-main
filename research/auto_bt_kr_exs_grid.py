"""진입/이탈/슬롯 (E/X/S) grid 재검증 — 7년, production 실제 score base.
현재 production: E3/X6/S3 (진입 rank≤3, 이탈 rank>6, 슬롯3, v80.24). 최적인지 + 더 나은 조합?
base = state 'score'(과열캡/일회성/seasonality 전부 반영). 진입2-4 × 이탈4-10 × 슬롯2-4 스윕.
채택 기준: Cal noise(±0.10) 초과 + WFmin·MDD·IS/OOS 비악화 + 인접 안정(과적합 아님).
실행: python research/auto_bt_kr_exs_grid.py
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\dev\claude-code\quant_py-main'); STATE = ROOT/'state'; DATA = ROOT/'data_cache'
PENALTY=50; TOP_N=20
ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0,np.nan)
kospi = pd.read_parquet(str(DATA/'kospi_yf.parquet')).iloc[:,0].sort_index()

def load(d):
    fp=STATE/f'ranking_{d}.json'
    if not fp.exists(): return {}
    data=json.load(open(fp,encoding='utf-8'))
    return {str(r['ticker']).zfill(6):float(r['score']) for r in data['rankings'] if r.get('score') is not None}

dates=sorted([fp.stem.replace('ranking_','') for fp in STATE.glob('ranking_*.json')
              if fp.stem.replace('ranking_','').isdigit() and len(fp.stem.replace('ranking_',''))==8
              and '20180702'<=fp.stem.replace('ranking_','')<='20260529'])
print(f'BT {len(dates)}일', flush=True)
sc={d:load(d) for d in dates}
crc_cache={}
def cr_map(d):
    if d not in crc_cache:
        rows=sorted(sc.get(d,{}).items(), key=lambda x:-x[1])
        crc_cache[d]={t:i+1 for i,(t,_) in enumerate(rows)}
    return crc_cache[d]

def cross(ds):
    sma=kospi.rolling(20).mean(); lma=kospi.rolling(80).mean(); reg={};md=False;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d);sv=sma.get(ts);lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d]=md;continue
        s=sv>lv
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        i=ohlcv.index.searchsorted(ts)
        if i>=len(ohlcv): return None
        ts=ohlcv.index[i]
    if tk not in ohlcv.columns: return None
    v=ohlcv.loc[ts,tk]; return v if pd.notna(v) and v>0 else None

def run_bt(ds,regime,eb,xb,slots):
    pf={};eq=1.0;eh={}
    for i,d in enumerate(ds):
        ib=regime.get(d,True)
        if i>=1 and pf:
            rets=[]
            for tk in list(pf):
                pp=gp(ds[i-1],tk);cp=gp(d,tk)
                if pp and cp: rets.append(cp/pp-1)
            if rets: eq*=(1+np.mean(rets)*len(pf)/slots)
        eh[d]=eq
        if i>=1 and regime.get(ds[i-1],True)!=ib: pf.clear()
        if not ib: continue
        c0=cr_map(d);c1=cr_map(ds[i-1]) if i>=1 else {};c2=cr_map(ds[i-2]) if i>=2 else {}
        t1={t:c for t,c in c1.items() if c<=TOP_N};t2={t:c for t,c in c2.items() if c<=TOP_N}
        wr={t:c0[t]*0.4+t1.get(t,PENALTY)*0.35+t2.get(t,PENALTY)*0.25 for t in c0}
        for tk in list(pf):
            if wr.get(tk,999)>xb: del pf[tk]
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:eb]:
            if tk in pf: continue
            if len(pf)>=slots: break
            if gp(d,tk): pf[tk]=1
    ea=np.array(list(eh.values()))
    if len(ea)<50: return (0,0,0)
    cagr=(ea[-1]**(252/len(ea))-1)*100
    pk=np.maximum.accumulate(ea);mdd=-((ea-pk)/pk).min()*100
    return (cagr/mdd if mdd>0 else 0,cagr,mdd)

isd=[d for d in dates if d<='20221231']; oosd=[d for d in dates if d>='20230102']
reg=cross(dates); regi=cross(isd); rego=cross(oosd)
wf_blocks=[('20180702','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260529')]
wf_reg={k:cross([d for d in dates if k[0]<=d<=k[1]]) for k in wf_blocks}

# 전체 grid
results=[]
for eb in [2,3,4]:
    for xb in [4,5,6,7,8,10]:
        for slots in [2,3,4]:
            if eb>slots: continue
            cal,cagr,mdd=run_bt(dates,reg,eb,xb,slots)
            results.append((eb,xb,slots,cal,cagr,mdd))
results.sort(key=lambda x:-x[3])
cur=[r for r in results if r[0]==3 and r[1]==6 and r[2]==3][0]
print(f'\n현재 production E3/X6/S3: Cal {cur[3]:.2f} CAGR {cur[4]:.0f}% MDD {cur[5]:.0f}%', flush=True)
print(f'\n=== Top 10 by Cal (전체 {len(results)}조합) ===', flush=True)
print(f'{"E/X/S":>8} | {"Cal":>5} {"CAGR":>5} {"MDD":>5} | {"IS":>5} {"OOS":>5} {"WFmin":>5} | vs현재', flush=True)
for eb,xb,slots,cal,cagr,mdd in results[:10]:
    ic,_,_=run_bt(isd,regi,eb,xb,slots); oc,_,_=run_bt(oosd,rego,eb,xb,slots)
    wf=[run_bt([d for d in dates if k[0]<=d<=k[1]],wf_reg[k],eb,xb,slots)[0] for k in wf_blocks]
    tag='← 현재' if (eb,xb,slots)==(3,6,3) else f'{cal-cur[3]:+.2f}'
    print(f'  {eb}/{xb}/{slots} | {cal:5.2f} {cagr:5.0f} {mdd:5.0f} | {ic:5.2f} {oc:5.2f} {min(wf):5.2f} | {tag}', flush=True)
print('\n채택: Cal 현재+0.10 초과 + WFmin·MDD·IS/OOS 비악화 + 인접조합도 우수(과적합 아님). 아니면 현재 유지.', flush=True)
