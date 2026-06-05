"""대기 중 탐색: 여러 괴리/과열 정의 빠른 BT 비교 (기존 state, production-replay).
변형: PER과열 / PBR과열 / PSR과열 / 가격이격도과열 / ey교체 / PEG(성장조건부 과열).
각 변형을 W=0.1,0.2에서 Cal/MDD/WFmin 비교 → 승자 deep-dive.
"""
import sys, json, time, glob, bisect
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()
DATA=Path('data_cache'); STATE=Path('state')
PENALTY=50; TOP_N=20; EB=3; SLOTS=3; XB=4; DEF_EB=0; DEF_XB=8
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
ma60=ohlcv.rolling(60,min_periods=30).mean()
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
mc_files={f.split('_')[-1].replace('.parquet',''):f for f in glob.glob('data_cache/market_cap_ALL_*.parquet')}
mc_keys=sorted(mc_files.keys()); _mcc={}
def mc_asof(ds):
    i=bisect.bisect_right(mc_keys,ds)-1
    if i<0: return None
    k=mc_keys[i]
    if k not in _mcc: _mcc[k]=pd.read_parquet(mc_files[k])['시가총액'].to_dict()
    return _mcc[k]

# TTM(NI,매출) + latest(자본) 시계열
def build_series(accts_ttm, acct_stock):
    ttm={a:{} for a in accts_ttm}; stk={}
    for f in glob.glob('data_cache/fs_dart_*.parquet'):
        tk=f.split('_')[-1].replace('.parquet','')
        try:
            d=pd.read_parquet(f); d['기준일']=pd.to_datetime(d['기준일']); d['rcept_dt']=pd.to_datetime(d['rcept_dt'])
            for a in accts_ttm:
                pref='지배주주당기순이익' if a=='당기순이익' else None
                sub=d[d['계정']==a]
                if pref is not None:
                    p=d[d['계정']==pref]
                    if p['기준일'].nunique()>=sub['기준일'].nunique()*0.6 and not p.empty: sub=p
                if sub.empty: continue
                q=sub.sort_values('기준일').drop_duplicates('기준일',keep='last')
                if len(q)<4: continue
                vals=q['값'].values; rcs=q['rcept_dt'].values; ser=[]
                for i in range(3,len(q)): ser.append((pd.Timestamp(rcs[i]).strftime('%Y%m%d'),vals[i-3:i+1].sum()))
                ser.sort()
                if ser: ttm[a][tk]=ser
            sub=d[d['계정']==acct_stock]
            if not sub.empty:
                q=sub.sort_values('기준일').drop_duplicates('기준일',keep='last')
                ser=[(pd.Timestamp(r).strftime('%Y%m%d'),v) for r,v in zip(q['rcept_dt'].values,q['값'].values)]
                ser.sort()
                if ser: stk[tk]=ser
        except Exception: pass
    return ttm, stk
print('재무 시계열 구축...',flush=True)
ttm, stk = build_series(['당기순이익','매출액'], '자본')
def asof(ser_map,tk,ds):
    s=ser_map.get(tk)
    if not s: return None
    i=bisect.bisect_right([x[0] for x in s],ds)-1
    return s[i][1] if i>=0 else None
print(f'  NI {len(ttm["당기순이익"])} 매출 {len(ttm["매출액"])} 자본 {len(stk)} 종목, {time.time()-t0:.0f}s',flush=True)

def zser(dic):
    s=pd.Series(dic); le=np.log(s[s>0]);
    if len(le)<20 or le.std()==0: return {}
    m,sd=le.mean(),le.std()
    return {tk:(np.log(s[tk])-m)/sd for tk in s.index if s[tk]>0}

print('state 로드 + 신호 계산...',flush=True)
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
    ts=pd.Timestamp(ds)
    ma_row=ma60.loc[ts] if ts in ma60.index else (ma60.iloc[ma60.index.searchsorted(ts)] if ma60.index.searchsorted(ts)<len(ma60) else None)
    ey={};by={};sy={};disp={};gz={}
    recs=[]
    for r in rows:
        tk=str(r['ticker']).zfill(6); sc=r.get('score',0.0) or 0.0; vs=r.get('value_s',0.0) or 0.0; g=r.get('growth_s',0.0) or 0.0
        recs.append([tk,sc,vs,g])
        mcap=mc.get(tk,0)
        if not mcap or mcap<=0: continue
        ni=asof(ttm['당기순이익'],tk,ds); rev=asof(ttm['매출액'],tk,ds); eq=asof(stk,tk,ds)
        if ni and ni>0: ey[tk]=(ni*1e8)/mcap
        if eq and eq>0: by[tk]=(eq*1e8)/mcap
        if rev and rev>0: sy[tk]=(rev*1e8)/mcap
        if ma_row is not None and tk in ohlcv.columns:
            p=r.get('price'); mav=ma_row.get(tk)
            if p and mav and mav>0: disp[tk]=p/mav   # >1 = 가격 과열
        gz[tk]=g
    # z & pen
    z_ey=zser(ey); z_by=zser(by); z_sy=zser(sy)
    # disparity z (높을수록 과열 → 양수, pen=음수쪽 아니라 과열은 양수이므로 -z의 음수클립)
    dser=pd.Series(disp)
    z_disp={}
    if len(dser)>=20 and dser.std()>0:
        m,sd=dser.mean(),dser.std()
        z_disp={tk:(dser[tk]-m)/sd for tk in dser.index}   # 과열=양수
    # growth median for PEG
    gvals=pd.Series(gz); gmed=gvals.median() if len(gvals) else 0
    for rec in recs:
        tk=rec[0]
        rec.append(min(z_ey.get(tk,0.0),0.0))      # 4 pen_per (싼=양수, 비싼=음수클립→감점)
        rec.append(min(z_by.get(tk,0.0),0.0))      # 5 pen_pbr
        rec.append(min(z_sy.get(tk,0.0),0.0))      # 6 pen_psr
        rec.append(-max(z_disp.get(tk,0.0),0.0))   # 7 pen_disp (과열=양수 → 음수 감점)
        rec.append(z_ey.get(tk,0.0))               # 8 ey_full (교체용, 클립X)
        # 9 pen_peg: 성장 중앙값 이하 종목만 PER 과열 감점 (성장으로 정당화 안 되는 과열)
        rec.append(min(z_ey.get(tk,0.0),0.0) if rec[3]<gmed else 0.0)
    RAW[ds]=recs
ADATES=sorted(RAW.keys())
print(f'  {len(ADATES)}일, {time.time()-t0:.0f}s',flush=True)

def regime_cross(dates,short=20,lp=80,cf=5):
    sma=kospi.rolling(short).mean();lma=kospi.rolling(lp).mean();reg={};md=False;stk=0;ss=None
    for d in dates:
        tsd=pd.Timestamp(d);sv=sma.get(tsd);lv=lma.get(tsd)
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
def cr_signal(W, sigidx, replace=False):
    crc={}
    for d,rows in RAW.items():
        if replace:  # score - 0.15*value_s + 0.15*ey_full
            items=[(r[0], r[1]-0.15*r[2]+W*r[sigidx]) for r in rows]
        else:
            items=[(r[0], r[1]+W*r[sigidx]) for r in rows]
        items.sort(key=lambda x:-x[1])
        crc[d]={tk:i+1 for i,(tk,_) in enumerate(items)}
    return crc
def run(dates,regime,crc):
    pf={};eq=1.0;eh={}
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
            if wr.get(tk,999)>xr: del pf[tk]
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if len(pf)>=SLOTS: break
            cp=gp(d,tk)
            if cp: pf[tk]=cp
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
    return cal,cagr,mdd,(min(wf) if wf else 0)
reg=regime_cross(ADATES)
VARIANTS=[('baseline',None,None),('PER과열',4,False),('PBR과열',5,False),('PSR과열',6,False),
          ('가격이격도과열',7,False),('PEG성장조건부',9,False),('ey교체(밸류대체)',8,True)]
print(f'\n=== 변형 비교 (production-replay 7.4년) ===',flush=True)
print(f'{"변형":<18}{"W":>5}{"Cal":>8}{"CAGR":>7}{"MDD":>7}{"WFmin":>7}',flush=True)
b=run(ADATES,reg,cr_signal(0,4))
print(f'{"baseline":<18}{"-":>5}{b[0]:>8.3f}{b[1]:>6.1f}%{b[2]:>6.2f}%{b[3]:>7.3f}',flush=True)
for name,idx,rep in VARIANTS:
    if idx is None: continue
    for W in [0.1,0.2]:
        r=run(ADATES,reg,cr_signal(W,idx,rep))
        print(f'{name:<18}{W:>5}{r[0]:>8.3f}{r[1]:>6.1f}%{r[2]:>6.2f}%{r[3]:>7.3f}',flush=True)
print(f'\n총 {time.time()-t0:.0f}s',flush=True)
