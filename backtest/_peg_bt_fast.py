"""빠른 경로: 기존 production state JSON(baked composite_rank/score) + 외부 pen 계산.
재생성 불필요. pen = clip(z(log(시총/TTM_NI)), <=0). cr(W)=rank(score+W*pen).
production-replay (MA20x80x5, 진입3/이탈4/슬롯3, v80.22). 재생성판과 교차검증용."""
import sys, json, time, glob, bisect
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()
DATA=Path('data_cache'); STATE=Path('state')
PENALTY=50; TOP_N=20; EB=3; SLOTS=3; XB=4; DEF_EB=0; DEF_XB=8

ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()

# market_cap: date->{tk:시총}
mc_files={f.split('_')[-1].replace('.parquet',''):f for f in glob.glob('data_cache/market_cap_ALL_*.parquet')}
mc_keys=sorted(mc_files.keys()); _mcc={}
def mc_asof(ds):
    i=bisect.bisect_right(mc_keys,ds)-1
    if i<0: return None
    k=mc_keys[i]
    if k not in _mcc: _mcc[k]=pd.read_parquet(mc_files[k])['시가총액'].to_dict()
    return _mcc[k]

# per-ticker TTM NI step series: list of (avail_date 'YYYYMMDD', ttm_eok)
print('TTM NI 시계열 구축...',flush=True)
ttm_series={}
for f in glob.glob('data_cache/fs_dart_*.parquet'):
    tk=f.split('_')[-1].replace('.parquet','')
    try:
        d=pd.read_parquet(f)
        ni=d[d['계정'].isin(['지배주주당기순이익','당기순이익'])].copy()
        if ni.empty: continue
        # 지배 우선: 분기별 지배 있으면 지배, 없으면 당기
        ni['기준일']=pd.to_datetime(ni['기준일']); ni['rcept_dt']=pd.to_datetime(ni['rcept_dt'])
        pref=ni[ni['계정']=='지배주주당기순이익']
        use=pref if pref['기준일'].nunique()>=ni['기준일'].nunique()*0.6 else ni[ni['계정']=='당기순이익']
        if use.empty: use=ni
        q=use.sort_values('기준일').drop_duplicates('기준일',keep='last')
        if len(q)<4: continue
        vals=q['값'].values; rcs=q['rcept_dt'].values
        ser=[]
        for i in range(3,len(q)):
            ttm=vals[i-3:i+1].sum()
            ser.append((pd.Timestamp(rcs[i]).strftime('%Y%m%d'), ttm))
        ser.sort()
        if ser: ttm_series[tk]=ser
    except Exception: pass
print(f'  {len(ttm_series)} 종목, {time.time()-t0:.0f}s',flush=True)
def ttm_asof(tk,ds):
    s=ttm_series.get(tk)
    if not s: return None
    i=bisect.bisect_right([x[0] for x in s],ds)-1
    return s[i][1] if i>=0 else None

# load existing production rankings + compute pen per date
print('기존 state 로드 + pen 계산...',flush=True)
RAW={}
for fp in sorted(STATE.glob('ranking_*.json')):
    ds=fp.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8 and '20190102'<=ds<='20260529'): continue
    try: d=json.load(open(fp,encoding='utf-8'))
    except: continue
    rows=d.get('rankings',[])
    if not rows: continue
    mc=mc_asof(ds)
    if mc is None: continue
    eys={}
    recs=[]
    for r in rows:
        tk=str(r['ticker']).zfill(6); sc=r.get('score',0.0) or 0.0
        cr0=r.get('composite_rank',r.get('rank',999))
        recs.append([tk,sc,cr0,0.0])  # pen filled below
        mcap=mc.get(tk,0); ni=ttm_asof(tk,ds)
        if mcap and mcap>0 and ni and ni>0:
            eys[tk]=(ni*1e8)/mcap
    if len(eys)>=20:
        le=np.log(pd.Series(eys)); m,s=le.mean(),le.std()
        if s>0:
            for rec in recs:
                tk=rec[0]
                if tk in eys:
                    rec[3]=min((np.log(eys[tk])-m)/s,0.0)
    RAW[ds]=recs
ADATES=sorted(RAW.keys())
print(f'  {len(ADATES)}일 ({ADATES[0]}~{ADATES[-1]}), {time.time()-t0:.0f}s',flush=True)

def regime_cross(dates,short=20,lp=80,cf=5):
    sma=kospi.rolling(short).mean();lma=kospi.rolling(lp).mean();reg={};md=False;stk=0;ss=None
    for d in dates:
        ts=pd.Timestamp(d);sv=sma.get(ts);lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d]=md;continue
        s=sv>lv
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=cf and md!=s: md=s
        reg[d]=md
    return reg
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    if tk not in ohlcv.columns: return None
    v=ohlcv.loc[ts,tk];return v if pd.notna(v) and v>0 else None
def cr_for_W(W,exclude=None):
    crc={}
    for d,rows in RAW.items():
        items=[(tk,sc+W*pen) for (tk,sc,cr0,pen) in rows if not(exclude and tk in exclude)]
        items.sort(key=lambda x:-x[1])
        crc[d]={tk:i+1 for i,(tk,_) in enumerate(items)}
    return crc
def run(dates,regime,crc):
    pf={};eq=1.0;eh={};turn=0
    for i,d in enumerate(dates):
        ib=regime.get(d,True);er=EB if ib else DEF_EB;xr=XB if ib else DEF_XB
        if i>=1 and pf:
            rs=[]
            for tk in pf:
                pp=gp(dates[i-1],tk);cp=gp(d,tk)
                if pp and cp: rs.append(cp/pp-1)
            if rs: eq*=(1+np.mean(rs)*len(pf)/SLOTS)
        eh[d]=eq
        if i>=1 and regime.get(dates[i-1],True)!=ib: pf.clear()
        if not ib: continue
        cr0=crc.get(d,{});cr1=crc.get(dates[i-1],{}) if i>=1 else {};cr2=crc.get(dates[i-2],{}) if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c0*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c0 in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk];turn+=1
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if len(pf)>=SLOTS: break
            cp=gp(d,tk)
            if cp: pf[tk]=cp;turn+=1
    ea=np.array(list(eh.values()))
    if len(ea)<50: return None
    cagr=(ea[-1]**(252/len(ea))-1)*100
    p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    cal=cagr/mdd if mdd>0 else 0
    es=pd.Series(eh);wf=[]
    for st,ed in [('20190102','20191231'),('20200101','20211231'),('20220101','20231231'),('20240101','20260529')]:
        sub=es[(es.index>=st)&(es.index<=ed)]
        if len(sub)<50: continue
        sr=(sub.iloc[-1]/sub.iloc[0])**(252/len(sub))-1
        sp=np.maximum.accumulate(sub.values);sd=-((sub.values-sp)/sp).min()
        wf.append((sr*100)/(sd*100) if sd>0 else 0)
    return {'cal':cal,'cagr':cagr,'mdd':mdd,'wfmin':min(wf) if wf else 0,'turn':turn}

WGRID=[0.0,0.05,0.1,0.15,0.2,0.3]
ISD=[d for d in ADATES if d<='20221231'];OOSD=[d for d in ADATES if d>='20230102']
reg_all=regime_cross(ADATES);reg_is=regime_cross(ISD);reg_oos=regime_cross(OOSD)
print(f'\n=== [빠른 경로] pen_cs W-그리드 (기존 state, 7.4년) ===',flush=True)
print(f'{"W":>6} {"Cal":>7} {"CAGR":>7} {"MDD":>7} {"WFmin":>7} {"IS_Cal":>7} {"OOS_Cal":>8} {"회전":>6}',flush=True)
out=[]
for W in WGRID:
    crc=cr_for_W(W)
    full=run(ADATES,reg_all,crc)
    isr=run(ISD,reg_is,{d:crc[d] for d in ISD})
    oosr=run(OOSD,reg_oos,{d:crc[d] for d in OOSD})
    out.append((W,full))
    mark=' ←baseline' if W==0 else ''
    print(f'{W:>6} {full["cal"]:>7.3f} {full["cagr"]:>6.1f}% {full["mdd"]:>6.2f}% {full["wfmin"]:>7.3f} {isr["cal"]:>7.3f} {oosr["cal"]:>8.3f} {full["turn"]:>6}{mark}',flush=True)
print(f'\n총 {time.time()-t0:.0f}s',flush=True)
