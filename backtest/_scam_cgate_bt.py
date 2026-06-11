# -*- coding: utf-8 -*-
"""일회성이익 페널티 7.4년 BT (v80.23 baseline, production-replay).
플래그 = PIT accruals B=(NI-CFO)/asset(TTM) & C=maxQ_OP/TTM_OP. rcept_dt<=기준일만 사용.
모드: baseline / soft(G*0.7) / hard(제외). 임계 (B,C) 변형. + 표본검증.
재사용: _peg_bt_maexit.py 엔진. state_peg_bt cr(W=0.2).
"""
import sys, json, time, glob, os
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt')
PENALTY=50; TOP_N=20; EB=3; SLOTS=3; XB=6; W=0.2; GW=0.55  # XB=6: v80.24 현 production 이탈선
OP='영업이익';NI='당기순이익';CFO='영업활동으로인한현금흐름';AST='자산'
ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)

# ---- ranking 로드 (score + growth_s) ----
RAW={}
for f in sorted(PEG.glob('ranking_*.json')):
    ds=f.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8 and '20190102'<=ds<='20260605'): continue
    d=json.load(open(f,encoding='utf-8')); rows=d.get('rankings',[])
    if not rows: continue
    RAW[ds]=[(str(r['ticker']).zfill(6),(r.get('score',0.0) or 0.0)+W*(r.get('overheat_pen',0.0) or 0.0),(r.get('growth_s',0.0) or 0.0)) for r in rows]
ADATES=sorted(RAW.keys())
univ=sorted({tk for d in RAW for tk,_,_ in RAW[d]})
print(f'{len(ADATES)}일, 유니버스 {len(univ)}종목 로드 {time.time()-t0:.0f}s',flush=True)

# ---- PIT 일회성 플래그: ticker -> [(rcept_dt 'YYYYMMDD', B, C)] (보고시점마다) ----
def parse_fs(tk):
    f=f'data_cache/fs_dart_{tk}.parquet'
    if not os.path.exists(f): return None
    raw=pd.read_parquet(f)
    if raw.shape[1]<5: return None
    acct,period,val=raw.iloc[:,0],raw.iloc[:,1],raw.iloc[:,2]
    qcol=rcol=None
    pser=pd.to_datetime(period,errors='coerce')
    import re
    DATE_RE=re.compile(r'^\d{4}-\d{2}-\d{2}')
    for j in range(3,raw.shape[1]):
        col=raw.iloc[:,j]; sv=col.astype(str)
        if qcol is None and sv.isin(['q','y','a','h']).any() and col.nunique()<8: qcol=col;continue
        # rcept: YYYY-MM-DD 패턴 + 다수 고유값(종목코드 uniq=1 배제)
        if rcol is None and sv.str.match(DATE_RE).mean()>0.7 and col.nunique()>4:
            rcol=pd.to_datetime(col,errors='coerce')
    if qcol is None: return None
    if rcol is None: rcol=pser+pd.Timedelta(days=45)  # 폴백: 분기말+45d
    df=pd.DataFrame({'acct':acct.values,'period':pser.values,'val':val.values,'q':qcol.values,'rcept':rcol.values})
    df=df[df['q']=='q'].dropna(subset=['period'])
    return df

def flag_steps(tk):
    df=parse_fs(tk)
    if df is None or df.empty: return []
    steps=[]
    rcepts=sorted(df['rcept'].dropna().unique())
    for rc in rcepts:
        avail=df[df['rcept']<=rc]
        piv=avail.pivot_table(index='period',columns='acct',values='val',aggfunc='last').sort_index()
        if OP not in piv or NI not in piv: continue
        op=piv[OP].dropna();ni=piv[NI].dropna()
        cf=piv[CFO].dropna() if CFO in piv else pd.Series(dtype=float)
        ast=piv[AST].dropna() if AST in piv else pd.Series(dtype=float)
        if len(op)<8 or len(ni)<4 or len(cf)<4 or len(ast)<1: continue
        ot=op.iloc[-4:].sum();nt=ni.iloc[-4:].sum();ct=cf.iloc[-4:].sum()
        if ot<=0:
            steps.append((pd.Timestamp(rc).strftime('%Y%m%d'),0.0,0.0)); continue
        B=(nt-ct)/ast.iloc[-1]*100; C=op.iloc[-4:].max()/ot
        steps.append((pd.Timestamp(rc).strftime('%Y%m%d'),float(B),float(C)))
    return steps

print('PIT 플래그 계산중...',flush=True)
FLAGS={tk:flag_steps(tk) for tk in univ}
def get_BC(tk,ds):
    st=FLAGS.get(tk)
    if not st: return None
    best=None
    for rc,B,C in st:
        if rc<=ds: best=(B,C)
        else: break
    return best
print(f'플래그 완료 {time.time()-t0:.0f}s',flush=True)

# ---- 표본검증 ----
print('\n=== 표본검증: 핵심종목 B/C (PIT, 2026-06-05 기준) ===')
for tk,nm in [('031330','SAMT스캠'),('037460','삼지스캠'),('080220','제주반도체win'),('092870','엑시콘win'),('000660','SK하이닉스win')]:
    bc=get_BC(tk,'20260605')
    print(f'  {nm}({tk}): {("B=%.1f C=%.2f"%bc) if bc else "데이터없음"}')

# ---- BT ----
import importlib.util
def regime_cross(ds_list,kospi):
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
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
reg=regime_cross(ADATES,kospi)
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    v=ohlcv.at[ts,tk] if tk in ohlcv.columns else None
    return v if (v is not None and pd.notna(v) and v>0) else None

def build_crc(mode,bT,cT,drop=(),mult=0.7):
    crc={}
    for d in ADATES:
        scored=[]
        for tk,sc,gs in RAW[d]:
            if tk in drop: continue
            bc=get_BC(tk,d)
            flagged = bc is not None and bc[0]>bT and bc[1]>cT
            if flagged and mode=='hard': continue
            s=sc
            if flagged and mode=='soft' and gs>0: s=sc-(1-mult)*GW*gs  # G*mult
            scored.append((tk,s))
        crc[d]={tk:i+1 for i,(tk,_) in enumerate(sorted(scored,key=lambda x:-x[1]))}
    return crc

def run(crc, block=False, bT=25, cT=0.7):
    pf={};eq=1.0;eh={};turn=0;samt_ent=0
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
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk];turn+=1
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if len(pf)>=SLOTS: break
            if block:
                bc=get_BC(tk,d)
                if bc is not None and bc[0]>bT and bc[1]>cT: continue  # 일회성 플래그 → 신규진입 차단
            cp=gp(d,tk)
            if cp:
                pf[tk]=cp;turn+=1
                if tk=='031330': samt_ent+=1
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
    return cal,cagr,mdd,(min(wf) if wf else 0),turn,eh,samt_ent

import numpy as _np
def yearly(eh):
    es=pd.Series(eh); out={}
    for y in ['2019','2020','2021','2022','2023','2024','2025','2026']:
        sub=es[(es.index>=y+'0101')&(es.index<=y+'1231')]
        if len(sub)<20: continue
        # 직전 연말 기준
        prev=es[es.index<y+'0101']
        base=prev.iloc[-1] if len(prev) else 1.0
        out[y]=(sub.iloc[-1]/base-1)*100
    return out
def wf_blocks(eh):
    es=pd.Series(eh); out={}
    for nm,st,ed in [('19','20190102','20191231'),('20-21','20200101','20211231'),('22-23','20220101','20231231'),('24-26','20240101','20260605')]:
        sub=es[(es.index>=st)&(es.index<=ed)]
        if len(sub)<50: out[nm]=None; continue
        sr=(sub.iloc[-1]/sub.iloc[0])**(252/len(sub))-1
        sp=_np.maximum.accumulate(sub.values);sd=-((sub.values-sp)/sp).min()
        out[nm]=(sr/sd) if sd>0 else 0
    return out

LAST=ADATES[-1]
def rk(crc,tk): return crc.get(LAST,{}).get(tk,'권외')
print('\n=== C게이트 스윕 (bT=25, G×0.24 production 고정) — 성호(B29/C0.45) 잡고 winner 보존? ===')
print('B/C 표본: ', {nm: get_BC(t,"20260605") for t,nm in [("043260","성호"),("080220","제주"),("008060","대덕"),("000660","SK")]})
cb,cgb,mb,wfb,tnb,ehb,_=run(build_crc('none',999,999)); yb=yearly(ehb)
print(f'{"config":<14}{"Cal":>7}{"CAGR":>7}{"WFmin":>7}{"2022":>7}{"2026":>7}{"turn":>6} | {"SAMT":>5}{"성호":>5}{"제주":>5}{"삼지":>5}')
def line(tag,crc,c,cg,wf,y,tn):
    print(f'{tag:<14}{c:>7.3f}{cg:>6.1f}%{wf:>7.3f}{y.get("2022",0):>+6.1f}%{y.get("2026",0):>+6.1f}%{tn:>6} | {str(rk(crc,"031330")):>5}{str(rk(crc,"043260")):>5}{str(rk(crc,"080220")):>5}{str(rk(crc,"037460")):>5}',flush=True)
line('baseline',build_crc('none',999,999),cb,cgb,wfb,yb,tnb)
for cT in [0.7,0.5,0.3,0.0]:
    crc=build_crc('soft',25,cT,mult=0.24)
    c,cg,m,wf,tn,eh,se=run(crc); y=yearly(eh)
    line(f'cT={cT}',crc,c,cg,wf,y,tn)
print('\n=== LOWO (−SK하이닉스 −제룡전기): cT=0.7(현행) vs cT=0.0(B단독) ===')
for tag,cT in [('cT=0.7',0.7),('cT=0.0',0.0)]:
    crc=build_crc('soft',25,cT,drop=('000660','033100'),mult=0.24)
    c,cg,m,wf,tn,eh,se=run(crc); y=yearly(eh)
    print(f'  LOWO {tag:<8} Cal={c:.3f} CAGR={cg:.1f}% WFmin={wf:.3f} 2022={y.get("2022",0):+.1f}%',flush=True)
cD,cgD,_,wfD,_,_,_=run(build_crc('none',999,999,drop=('000660','033100')))
print(f'  LOWO baseline Cal={cD:.3f} CAGR={cgD:.1f}% WFmin={wfD:.3f}',flush=True)
print(f'\n총 {time.time()-t0:.0f}s')
