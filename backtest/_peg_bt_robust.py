"""robustness: LOO(단일 슈퍼위너 제외) + WF 블록 상세. 빠른 경로(기존 state) 재사용."""
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
mc_files={f.split('_')[-1].replace('.parquet',''):f for f in glob.glob('data_cache/market_cap_ALL_*.parquet')}
mc_keys=sorted(mc_files.keys()); _mcc={}
def mc_asof(ds):
    i=bisect.bisect_right(mc_keys,ds)-1
    if i<0: return None
    k=mc_keys[i]
    if k not in _mcc: _mcc[k]=pd.read_parquet(mc_files[k])['시가총액'].to_dict()
    return _mcc[k]
ttm_series={}
for f in glob.glob('data_cache/fs_dart_*.parquet'):
    tk=f.split('_')[-1].replace('.parquet','')
    try:
        d=pd.read_parquet(f); ni=d[d['계정'].isin(['지배주주당기순이익','당기순이익'])].copy()
        if ni.empty: continue
        ni['기준일']=pd.to_datetime(ni['기준일']); ni['rcept_dt']=pd.to_datetime(ni['rcept_dt'])
        pref=ni[ni['계정']=='지배주주당기순이익']
        use=pref if pref['기준일'].nunique()>=ni['기준일'].nunique()*0.6 else ni[ni['계정']=='당기순이익']
        if use.empty: use=ni
        q=use.sort_values('기준일').drop_duplicates('기준일',keep='last')
        if len(q)<4: continue
        vals=q['값'].values; rcs=q['rcept_dt'].values; ser=[]
        for i in range(3,len(q)): ser.append((pd.Timestamp(rcs[i]).strftime('%Y%m%d'), vals[i-3:i+1].sum()))
        ser.sort()
        if ser: ttm_series[tk]=ser
    except Exception: pass
def ttm_asof(tk,ds):
    s=ttm_series.get(tk)
    if not s: return None
    i=bisect.bisect_right([x[0] for x in s],ds)-1
    return s[i][1] if i>=0 else None
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
    eys={}; recs=[]
    for r in rows:
        tk=str(r['ticker']).zfill(6); sc=r.get('score',0.0) or 0.0
        recs.append([tk,sc,0.0])
        mcap=mc.get(tk,0); ni=ttm_asof(tk,ds)
        if mcap and mcap>0 and ni and ni>0: eys[tk]=(ni*1e8)/mcap
    if len(eys)>=20:
        le=np.log(pd.Series(eys)); m,s=le.mean(),le.std()
        if s>0:
            for rec in recs:
                if rec[0] in eys: rec[2]=min((np.log(eys[rec[0]])-m)/s,0.0)
    RAW[ds]=recs
ADATES=sorted(RAW.keys())
print(f'로드 {len(ADATES)}일, {time.time()-t0:.0f}s',flush=True)
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
        items=[(tk,sc+W*pen) for (tk,sc,pen) in rows if not(exclude and tk in exclude)]
        items.sort(key=lambda x:-x[1])
        crc[d]={tk:i+1 for i,(tk,_) in enumerate(items)}
    return crc
def run(dates,regime,crc,wf_detail=False):
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
        if len(sub)<50: wf.append(None);continue
        sr=(sub.iloc[-1]/sub.iloc[0])**(252/len(sub))-1
        sp=np.maximum.accumulate(sub.values);sd=-((sub.values-sp)/sp).min()
        wf.append(round((sr*100)/(sd*100),2) if sd>0 else 0)
    r={'cal':cal,'cagr':cagr,'mdd':mdd}
    if wf_detail: r['wf']=wf
    return r
reg_all=regime_cross(ADATES)
print('\n=== WF 블록 상세 (2019 / 2020-21 / 2022-23 / 2024-26) ===',flush=True)
for W in [0.0,0.05,0.1,0.15,0.2,0.3]:
    r=run(ADATES,reg_all,cr_for_W(W),wf_detail=True)
    print(f'  W={W:<5} Cal {r["cal"]:.3f} | WF blocks {r["wf"]}',flush=True)
print('\n=== LOO robustness: ΔCal(W vs W=0), 동일 종목 제외 ===',flush=True)
print(f'  {"W":>5} {"전체":>9} {"-033100":>10} {"-000660":>10} {"-둘다":>9}',flush=True)
for W in [0.05,0.1,0.15,0.2]:
    cells=[]
    for loo in [None,{'033100'},{'000660'},{'033100','000660'}]:
        rW=run(ADATES,reg_all,cr_for_W(W,exclude=loo))
        r0=run(ADATES,reg_all,cr_for_W(0.0,exclude=loo))
        cells.append(rW['cal']-r0['cal'])
    print(f'  {W:>5} {cells[0]:>+9.3f} {cells[1]:>+10.3f} {cells[2]:>+10.3f} {cells[3]:>+9.3f}',flush=True)
print(f'\n총 {time.time()-t0:.0f}s',flush=True)
