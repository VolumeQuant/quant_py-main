"""얇은 밸류트랩/지주사 정밀 제외 BT — 대덕류(고PER+저PBR+얇은거래)만 타겟.
앞선 BT: 고PER저PBR 단독 제외 +0.08(노이즈) — S-Oil 등 유동성큰 시클리컬까지 잡아 희석.
대덕 특징 = 거래대금 19억(얇음) + PER184 + PBR1.08. 거래대금 결합 시그니처로 정밀 타겟.
+ pick-level 유동성 게이트(Top3 픽이 얇으면 다음 종목으로 교체)도 테스트.
base = state 'score'(production), 거래대금 PIT = market_cap_ALL. 7년.
실행: python research/auto_bt_kr_thin_valuetrap.py
"""
import sys, json, re, bisect
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\dev\claude-code\quant_py-main'); STATE = ROOT/'state'; DATA = ROOT/'data_cache'
PENALTY=50; TOP_N=20; KW=('지주','홀딩스','홀딩')
ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0,np.nan)
kospi = pd.read_parquet(str(DATA/'kospi_yf.parquet')).iloc[:,0].sort_index()

# 거래대금 PIT (억)
mc_files=[]
for fp in DATA.glob('market_cap_ALL_*.parquet'):
    m=re.search(r'(\d{8})',fp.name)
    if m: mc_files.append((m.group(1),fp))
mc_files.sort(); mc_dates=[d for d,_ in mc_files]; _mcc={}
def _load_mc(p):
    if p not in _mcc:
        df=pd.read_parquet(p); col=next((c for c in df.columns if '거래대금' in str(c)), df.columns[3])
        _mcc[p]=(df[col]/1e8).to_dict()
    return _mcc[p]
def volmap(d):
    i=bisect.bisect_right(mc_dates,d)-1
    return _load_mc(mc_files[i][1]) if i>=0 else {}

def load(d):
    fp=STATE/f'ranking_{d}.json'
    if not fp.exists(): return {}
    data=json.load(open(fp,encoding='utf-8'))
    out={}
    for r in data['rankings']:
        s=r.get('score')
        if s is None: continue
        out[str(r['ticker']).zfill(6)]=(float(s),r.get('name',''),r.get('per'),r.get('pbr'))
    return out

dates=sorted([fp.stem.replace('ranking_','') for fp in STATE.glob('ranking_*.json')
              if fp.stem.replace('ranking_','').isdigit() and len(fp.stem.replace('ranking_',''))==8
              and '20180702'<=fp.stem.replace('ranking_','')<='20260529'])
print(f'BT {len(dates)}일', flush=True)
sc={d:load(d) for d in dates}; vol={d:volmap(d) for d in dates}

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

def excl(mode, nm, per, pbr, tv):
    """제외 시그니처."""
    is_vtrap = (per and pbr and per>40 and 0<pbr<1.5) or any(k in str(nm) for k in KW)
    if mode=='none': return False
    if mode=='vtrap_thin50': return is_vtrap and (tv is not None and tv<50)
    if mode=='vtrap_thin30': return is_vtrap and (tv is not None and tv<30)
    if mode=='thin50_per40': return (tv is not None and tv<50) and (per and per>40)
    return False

def cr_map(d,exclude,mode):
    vm=vol.get(d,{}); rows=[]
    for t,(s,nm,per,pbr) in sc.get(d,{}).items():
        if t in exclude: continue
        if excl(mode,nm,per,pbr,vm.get(t)): continue
        rows.append((t,s))
    rows.sort(key=lambda x:-x[1])
    return {t:i+1 for i,(t,_) in enumerate(rows)}

def run_bt(ds,regime,mode,exclude=set(),track=False):
    pf={};eq=1.0;eh={};contrib={}
    crc={d:cr_map(d,exclude,mode) for d in ds}
    for i,d in enumerate(ds):
        ib=regime.get(d,True)
        if i>=1 and pf:
            rets=[]
            for tk in list(pf):
                pp=gp(ds[i-1],tk);cp=gp(d,tk)
                if pp and cp:
                    r=cp/pp-1; rets.append(r)
                    if track: contrib[tk]=contrib.get(tk,0)+r/3
            if rets: eq*=(1+np.mean(rets)*len(pf)/3)
        eh[d]=eq
        if i>=1 and regime.get(ds[i-1],True)!=ib: pf.clear()
        if not ib: continue
        c0=crc.get(d,{});c1=crc.get(ds[i-1],{}) if i>=1 else {};c2=crc.get(ds[i-2],{}) if i>=2 else {}
        t1={t:c for t,c in c1.items() if c<=TOP_N};t2={t:c for t,c in c2.items() if c<=TOP_N}
        wr={t:c0[t]*0.4+t1.get(t,PENALTY)*0.35+t2.get(t,PENALTY)*0.25 for t in c0}
        for tk in list(pf):
            if wr.get(tk,999)>4: del pf[tk]
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:3]:
            if tk in pf: continue
            if len(pf)>=3: break
            if gp(d,tk): pf[tk]=1
    ea=np.array(list(eh.values()))
    if len(ea)<50: return (0,0,0,contrib)
    cagr=(ea[-1]**(252/len(ea))-1)*100
    pk=np.maximum.accumulate(ea);mdd=-((ea-pk)/pk).min()*100
    return (cagr/mdd if mdd>0 else 0,cagr,mdd,contrib)

isd=[d for d in dates if d<='20221231']; oosd=[d for d in dates if d>='20230102']
reg=cross(dates); regi=cross(isd); rego=cross(oosd)
print(f'\n{"config":>16} | {"Cal":>5} {"CAGR":>5} {"MDD":>5} | {"IS":>5} {"OOS":>5} | {"WFmin":>5} | {"LOO3":>5}', flush=True)
print('-'*74, flush=True)
base=None
for lbl,mode in [('baseline','none'),('밸류트랩+거래<50','vtrap_thin50'),('밸류트랩+거래<30','vtrap_thin30'),('거래<50&PER>40','thin50_per40')]:
    cal,cagr,mdd,contrib=run_bt(dates,reg,mode,track=True)
    ic,_,_,_=run_bt(isd,regi,mode); oc,_,_,_=run_bt(oosd,rego,mode)
    wf=[]
    for s_,e_ in [('20180702','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260529')]:
        sub=[d for d in dates if s_<=d<=e_]
        if len(sub)>=50: c,_,_,_=run_bt(sub,cross(sub),mode); wf.append(c)
    top=sorted(contrib.items(),key=lambda x:-x[1])[:3]; ex=set(t for t,_ in top)
    loo3,_,_,_=run_bt(dates,reg,mode,exclude=ex)
    dd='' if base is None else f' (Δ{cal-base:+.2f})'
    if mode=='none': base=cal
    print(f'{lbl:>16} | {cal:5.2f} {cagr:5.0f} {mdd:5.0f} | {ic:5.2f} {oc:5.2f} | {min(wf) if wf else 0:5.2f} | {loo3:5.2f}{dd}', flush=True)
print('\n채택: Cal noise(±0.10) 초과 + MDD·WFmin·IS/OOS·LOO 비악화. 미달이면 미적용.', flush=True)
