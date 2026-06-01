"""KP200+KQ150 universe 정식 재검증 — IS/OOS + WF + leave-one-out + 재현체크.
autopilot이 건너뛴 robust 검증. ranking JSON factor z-score 재가중 → universe 필터 → regime cross → 시뮬.
실행: python bt_kp_validate.py
"""
import sys, json, glob, re
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\dev\claude-code\quant_py-main'); STATE = ROOT/'state'; DATA = ROOT/'data_cache'
PENALTY=50; TOP_N=20

ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0,np.nan)
kospi = pd.read_parquet(str(DATA/'kospi_yf.parquet')).iloc[:,0].sort_index()
uj = json.load(open(DATA/'idx_kp200_kq150_20260529.json',encoding='utf-8'))
UNIV = set(str(t).zfill(6) for t in uj['kp200']) | set(str(t).zfill(6) for t in uj['kq150'])
print(f'universe KP200+KQ150: {len(UNIV)}종목', flush=True)

# 팩터 z-score 로드
def load_factors(d):
    fp=STATE/f'ranking_{d}.json'
    if not fp.exists(): return {}
    data=json.load(open(fp,encoding='utf-8'))
    out={}
    for r in data['rankings']:
        t=str(r['ticker']).zfill(6)
        out[t]=(r.get('value_s',0) or 0, r.get('quality_s',0) or 0, r.get('growth_s',0) or 0, r.get('momentum_s',0) or 0)
    return out
dates=sorted([fp.stem.replace('ranking_','') for fp in STATE.glob('ranking_*.json')
              if fp.stem.replace('ranking_','').isdigit() and len(fp.stem.replace('ranking_',''))==8
              and '20180702'<=fp.stem.replace('ranking_','')<='20260529'])
print(f'BT 대상 {len(dates)}일 ({dates[0]}~{dates[-1]})', flush=True)
fac={d:load_factors(d) for d in dates}

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
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    if tk not in ohlcv.columns: return None
    v=ohlcv.loc[ts,tk]; return v if pd.notna(v) and v>0 else None

def cr_map(d, w, exclude, use_univ=True):
    """universe 필터 + 가중치 재계산 → composite_rank dict"""
    f=fac.get(d,{})
    sc=[]
    for t,(vs,qs,gs,ms) in f.items():
        if use_univ and t not in UNIV: continue
        if t in exclude: continue
        sc.append((t, w[0]*vs+w[1]*qs+w[2]*gs+w[3]*ms))
    sc.sort(key=lambda x:-x[1])
    return {t:i+1 for i,(t,_) in enumerate(sc)}

def run_bt(ds, regime, w, slots=3, eb=3, xb=4, exclude=set(), track=False, use_univ=True):
    pf={};eq=1.0;eh={};contrib={}
    crc={d:cr_map(d,w,exclude,use_univ) for d in ds}
    for i,d in enumerate(ds):
        ib=regime.get(d,True)
        if i>=1 and pf:
            rets=[]
            for tk in list(pf):
                pp=gp(ds[i-1],tk);cp=gp(d,tk)
                if pp and cp:
                    r=cp/pp-1; rets.append(r)
                    if track: contrib[tk]=contrib.get(tk,0)+r*(1/slots)
            if rets: eq*=(1+np.mean(rets)*len(pf)/slots)
        eh[d]=eq
        if i>=1 and regime.get(ds[i-1],True)!=ib: pf.clear()
        if not ib: continue
        c0=crc.get(d,{});c1=crc.get(ds[i-1],{}) if i>=1 else {};c2=crc.get(ds[i-2],{}) if i>=2 else {}
        t1={t:c for t,c in c1.items() if c<=TOP_N};t2={t:c for t,c in c2.items() if c<=TOP_N}
        wr={t:c0[t]*0.4+t1.get(t,PENALTY)*0.35+t2.get(t,PENALTY)*0.25 for t in c0}
        for tk in list(pf):
            if wr.get(tk,999)>xb: del pf[tk]
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:eb]:
            if tk in pf: continue
            if len(pf)>=slots: break
            if gp(d,tk): pf[tk]=1
    ea=np.array(list(eh.values()))
    if len(ea)<50: return (0,0,0,eh,contrib)
    cagr=(ea[-1]**(252/len(ea))-1)*100
    pk=np.maximum.accumulate(ea);mdd=-((ea-pk)/pk).min()*100
    cal=cagr/mdd if mdd>0 else 0
    return (cal,cagr,mdd,eh,contrib)

W_ROBUST=(0.15,0.0,0.65,0.20)
isd=[d for d in dates if d<='20221231']; oosd=[d for d in dates if d>='20230102']

# 핵심: 같은 가중치(W_ROBUST)로 universe ON(KP200+KQ150) vs OFF(전체) head-to-head
for label,use_u in [('A. KP200+KQ150 (universe ON)',True),('B. 전체 유니버스 (universe OFF)',False)]:
    reg=cross(dates); regi=cross(isd); rego=cross(oosd)
    cal,cagr,mdd,eh,contrib=run_bt(dates,reg,W_ROBUST,track=True,use_univ=use_u)
    ic,_,_,_,_=run_bt(isd,regi,W_ROBUST,use_univ=use_u); oc,_,_,_,_=run_bt(oosd,rego,W_ROBUST,use_univ=use_u)
    wf=[]
    for st,ed in [('20180702','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260529')]:
        sub=[d for d in dates if st<=d<=ed]
        if len(sub)>=50:
            c,_,_,_,_=run_bt(sub,cross(sub),W_ROBUST,use_univ=use_u); wf.append(c)
    top=sorted(contrib.items(),key=lambda x:-x[1])[:5]
    loo={}
    for n in [3,5]:
        ex=set(t for t,_ in top[:n])
        c,_,_,_,_=run_bt(dates,reg,W_ROBUST,exclude=ex,use_univ=use_u); loo[n]=c
    print(f'\n=== {label} | 가중치 V15Q0G65M20 동일 ===', flush=True)
    print(f'  전체 Cal {cal:.2f} CAGR {cagr:.0f}% MDD {mdd:.0f}% | IS {ic:.2f} OOS {oc:.2f} | WFmin {min(wf):.2f} {[round(x,2) for x in wf]}', flush=True)
    print(f'  LOO top3제외 {loo[3]:.2f} (Δ{loo[3]-cal:+.2f}) / top5제외 {loo[5]:.2f} (Δ{loo[5]-cal:+.2f})', flush=True)
print('\n→ A(universe) vs B(전체): A가 전체기간·IS·OOS·WFmin·LOO에서 일관 우위면 universe 변경 가치 O. 비슷하면 변경 불필요.', flush=True)
