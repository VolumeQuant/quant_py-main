"""외국인 점수가산 — 풀 production 하니스 BT (채택 결정 게이트).
단순 재구성(V15G65M20) 대신 state ranking의 실제 production 'score'(=멀티팩터_점수,
과열캡 pen_cs + 계절성 + 일회성 페널티 v80.25 + mom_10 + vol_low 전부 반영된 최종값)를
base로 사용 → 외국인 z만 얹어 재랭킹. 외국인 효과가 기존 풀팩터 위에서도 살아남는지 검증.
2022~2026 (flows 범위). 실행: python research/auto_bt_kr_foreign_fullharness.py
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\dev\claude-code\quant_py-main'); STATE = ROOT/'state'; DATA = ROOT/'data_cache'
PENALTY=50; TOP_N=20
FLOW_PATH = DATA/'kr_investor_flows.parquet'

ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0,np.nan)
kospi = pd.read_parquet(str(DATA/'kospi_yf.parquet')).iloc[:,0].sort_index()

flows = pd.read_parquet(FLOW_PATH); flows['date']=flows['date'].astype(str)
fdates = sorted(flows['date'].unique())
fpiv = flows.pivot_table(index='date', columns='ticker', values='foreign_net', aggfunc='last').sort_index()
fcum = fpiv.fillna(0).rolling(20, min_periods=5).sum()
def flow_at(d):
    if d in fcum.index: return fcum.loc[d].to_dict()
    idx=fcum.index.searchsorted(d)-1; return fcum.iloc[idx].to_dict() if idx>=0 else {}

def load_scores(d):
    """production 최종 멀티팩터 점수(과열캡/일회성 등 전부 반영) — JSON 'score'."""
    fp=STATE/f'ranking_{d}.json'
    if not fp.exists(): return {}
    data=json.load(open(fp,encoding='utf-8'))
    out={}
    for r in data['rankings']:
        s=r.get('score')
        if s is not None: out[str(r['ticker']).zfill(6)]=float(s)
    return out

dates=sorted([fp.stem.replace('ranking_','') for fp in STATE.glob('ranking_*.json')
              if fp.stem.replace('ranking_','').isdigit() and len(fp.stem.replace('ranking_',''))==8
              and fdates[0]<=fp.stem.replace('ranking_','')<='20260529'])
print(f'BT 대상 {len(dates)}일 ({dates[0]}~{dates[-1]})', flush=True)
sc_map={d:load_scores(d) for d in dates}
fcm={d:flow_at(d) for d in dates}

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

def _zmap(vals):
    s=pd.Series(vals).replace([np.inf,-np.inf],np.nan).dropna()
    if len(s)<5 or s.std()==0: return {}
    return ((s-s.mean())/s.std()).to_dict()

def cr_map(d,exclude,fw):
    """production score base + fw×외국인z 재랭킹 (fw=0이면 순수 production)."""
    sc=sc_map.get(d,{}); sc2=[]
    zf=_zmap({t:fcm.get(d,{}).get(t,np.nan) for t in sc}) if fw>0 else {}
    for t,s in sc.items():
        if t in exclude: continue
        sc2.append((t, s + fw*zf.get(t,0)))
    sc2.sort(key=lambda x:-x[1])
    return {t:i+1 for i,(t,_) in enumerate(sc2)}

def run_bt(ds,regime,fw,slots=3,eb=3,xb=4,exclude=set(),track=False):
    pf={};eq=1.0;eh={};contrib={}
    crc={d:cr_map(d,exclude,fw) for d in ds}
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
    if len(ea)<50: return (0,0,0,contrib)
    cagr=(ea[-1]**(252/len(ea))-1)*100
    pk=np.maximum.accumulate(ea);mdd=-((ea-pk)/pk).min()*100
    return (cagr/mdd if mdd>0 else 0,cagr,mdd,contrib)

isd=[d for d in dates if d<='20231231']; oosd=[d for d in dates if d>='20240101']
reg=cross(dates); regi=cross(isd); rego=cross(oosd)
print(f'\n{"config":>18} | {"Cal":>5} {"CAGR":>5} {"MDD":>5} | {"IS":>5} {"OOS":>5} | {"WFmin":>5} | {"LOO3":>5}', flush=True)
print('-'*76, flush=True)
base=None
for lbl,fw in [('production(순수)',0),('+외국인0.08',0.08),('+외국인0.10',0.10),('+외국인0.12',0.12),('+외국인0.15',0.15)]:
    cal,cagr,mdd,contrib=run_bt(dates,reg,fw,track=True)
    ic,_,_,_=run_bt(isd,regi,fw); oc,_,_,_=run_bt(oosd,rego,fw)
    wf=[]
    for st,ed in [('20220101','20221231'),('20230101','20231231'),('20240101','20241231'),('20250101','20260529')]:
        sub=[d for d in dates if st<=d<=ed]
        if len(sub)>=50: c,_,_,_=run_bt(sub,cross(sub),fw); wf.append(c)
    top=sorted(contrib.items(),key=lambda x:-x[1])[:3]; ex=set(t for t,_ in top)
    loo3,_,_,_=run_bt(dates,reg,fw,exclude=ex)
    dd='' if base is None else f' (Δ{cal-base:+.2f})'
    if fw==0: base=cal
    print(f'{lbl:>18} | {cal:5.2f} {cagr:5.0f} {mdd:5.0f} | {ic:5.2f} {oc:5.2f} | {min(wf) if wf else 0:5.2f} | {loo3:5.2f}{dd}', flush=True)

print('\n채택: 풀 production score 위에서도 외국인이 Cal·MDD·WFmin·LOO 우월 유지 + 인접 plateau.', flush=True)
print('흡수(Δ~0)되면 기존 팩터와 redundant → 미적용. 유지되면 production 적용 권고.', flush=True)
