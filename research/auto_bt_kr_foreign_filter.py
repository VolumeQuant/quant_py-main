"""외국인/기관 순매수 결합 정식 BT — production에 ① 진입필터 ② 점수가산 두 방식 검증.
표본 EDA(외국인 +5.4%p) 통과분의 실현 BT. data_cache/kr_investor_flows.parquet 필요(수집 후).
2022~2026, baseline 대비 calmar/MDD/WFmin/IS·OOS/LOO. 거래대금 BT와 동일 기준.
실행(수집 완료 후): python research/auto_bt_kr_foreign_filter.py
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\dev\claude-code\quant_py-main'); STATE = ROOT/'state'; DATA = ROOT/'data_cache'
PENALTY=50; TOP_N=20; W=(0.15,0.0,0.65,0.20)
FLOW_PATH = DATA/'kr_investor_flows.parquet'

if not FLOW_PATH.exists():
    print('⏳ kr_investor_flows.parquet 아직 없음 — 수집 완료 후 실행하세요.', flush=True); sys.exit()

ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0,np.nan)
kospi = pd.read_parquet(str(DATA/'kospi_yf.parquet')).iloc[:,0].sort_index()

# ── 외국인/기관 20일 누적 순매수(억) PIT 맵 ──
flows = pd.read_parquet(FLOW_PATH)
flows['date'] = flows['date'].astype(str)
fdates = sorted(flows['date'].unique())
print(f'flows: {len(fdates)}일 ({fdates[0]}~{fdates[-1]}), {len(flows)}행', flush=True)
# pivot: date×ticker
fpiv = flows.pivot_table(index='date', columns='ticker', values='foreign_net', aggfunc='last').sort_index()
ipiv = flows.pivot_table(index='date', columns='ticker', values='inst_net', aggfunc='last').sort_index()
# 20일 누적 (rolling sum, 결측=0 취급)
fcum = fpiv.fillna(0).rolling(20, min_periods=5).sum()
icum = ipiv.fillna(0).rolling(20, min_periods=5).sum()

def flow_at(cum, d):
    if d in cum.index: return cum.loc[d].to_dict()
    idx = cum.index.searchsorted(d) - 1
    return cum.iloc[idx].to_dict() if idx >= 0 else {}

def load_factors(d):
    fp=STATE/f'ranking_{d}.json'
    if not fp.exists(): return {}
    data=json.load(open(fp,encoding='utf-8'))
    return {str(r['ticker']).zfill(6):(r.get('value_s',0) or 0,r.get('quality_s',0) or 0,
            r.get('growth_s',0) or 0,r.get('momentum_s',0) or 0) for r in data['rankings']}

# BT 기간 = flows 가용 범위 (2022~2026)
dates=sorted([fp.stem.replace('ranking_','') for fp in STATE.glob('ranking_*.json')
              if fp.stem.replace('ranking_','').isdigit() and len(fp.stem.replace('ranking_',''))==8
              and fdates[0]<=fp.stem.replace('ranking_','')<='20260529'])
print(f'BT 대상 {len(dates)}일 ({dates[0]}~{dates[-1]})', flush=True)
fac={d:load_factors(d) for d in dates}
fcm={d:flow_at(fcum,d) for d in dates}
icm={d:flow_at(icum,d) for d in dates}

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
    """dict ticker->값 → cross-sectional z dict."""
    s=pd.Series(vals).replace([np.inf,-np.inf],np.nan).dropna()
    if len(s)<5 or s.std()==0: return {}
    z=(s-s.mean())/s.std(); return z.to_dict()

def cr_map(d,exclude,mode,fw,cmap):
    """mode: 'base'(무결합) / 'filter'(순매수>0만) / 'score'(점수 += fw×z(순매수))."""
    f=fac.get(d,{}); fl=cmap.get(d,{}); sc=[]
    zf=_zmap({t:fl.get(t,np.nan) for t in f}) if mode=='score' else {}
    for t,(vs,qs,gs,ms) in f.items():
        if t in exclude: continue
        if mode=='filter' and fl.get(t,-1) <= 0: continue
        base=W[0]*vs+W[1]*qs+W[2]*gs+W[3]*ms
        if mode=='score': base += fw*zf.get(t,0)
        sc.append((t,base))
    sc.sort(key=lambda x:-x[1])
    return {t:i+1 for i,(t,_) in enumerate(sc)}

def run_bt(ds,regime,mode,fw,cmap,slots=3,eb=3,xb=4,exclude=set(),track=False):
    pf={};eq=1.0;eh={};contrib={}
    crc={d:cr_map(d,exclude,mode,fw,cmap) for d in ds}
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

configs = [('baseline','base',0,None),
           ('외국인 필터>0','filter',0,fcm),
           ('외국인 점수+0.05','score',0.05,fcm),
           ('외국인 점수+0.10','score',0.10,fcm),
           ('외국인 점수+0.20','score',0.20,fcm),
           ('기관 점수+0.10','score',0.10,icm)]
print(f'\n{"config":>16} | {"Cal":>5} {"CAGR":>5} {"MDD":>5} | {"IS":>5} {"OOS":>5} | {"WFmin":>5} | {"LOO3":>5}', flush=True)
print('-'*74, flush=True)
base=None
for lbl,mode,fw,cmap in configs:
    cal,cagr,mdd,contrib=run_bt(dates,reg,mode,fw,cmap,track=True)
    ic,_,_,_=run_bt(isd,regi,mode,fw,cmap); oc,_,_,_=run_bt(oosd,rego,mode,fw,cmap)
    wf=[]
    for st,ed in [('20220101','20221231'),('20230101','20231231'),('20240101','20241231'),('20250101','20260529')]:
        sub=[d for d in dates if st<=d<=ed]
        if len(sub)>=50: c,_,_,_=run_bt(sub,cross(sub),mode,fw,cmap); wf.append(c)
    top=sorted(contrib.items(),key=lambda x:-x[1])[:3]; ex=set(t for t,_ in top)
    loo3,_,_,_=run_bt(dates,reg,mode,fw,cmap,exclude=ex)
    dd='' if base is None else f' (Δ{cal-base:+.2f})'
    if mode=='base': base=cal
    print(f'{lbl:>16} | {cal:5.2f} {cagr:5.0f} {mdd:5.0f} | {ic:5.2f} {oc:5.2f} | {min(wf) if wf else 0:5.2f} | {loo3:5.2f}{dd}', flush=True)

print('\n채택: Cal·MDD·WFmin·IS/OOS·LOO baseline 우월 + 2022 약세장 WF 비손실.', flush=True)
print('필터>0이 over-narrow(거래대금처럼)면 기각, 점수가산이 우월하면 그쪽 채택.', flush=True)
