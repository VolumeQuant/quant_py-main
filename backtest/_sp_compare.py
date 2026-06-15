# -*- coding: utf-8 -*-
"""USE_SELF_PER 0(pykrx 연간) vs 1(DART TTM) 표본 BT 비교.
각 폴더(_sp0/_sp1)의 cr 랭킹 → wr(3일가중,Top20 penalty) → 포트폴리오 시뮬(boost E3/X6/S3).
Calmar/CAGR/MDD/회전 비교 + 에이피알 평균순위."""
import sys, json, glob, os
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
DATA='data_cache'
oh=pd.read_parquet(sorted(glob.glob(f'{DATA}/all_ohlcv_*_2026061*.parquet'))[0]).replace(0,np.nan)
oh.index=pd.to_datetime(oh.index)
def ba(s):
    r=s.pct_change(fill_method=None); ev=r[(r<-0.33)|(r>0.45)]; s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50: s2.loc[s2.index<d]*=f
    return s2
ADJ={tk:ba(oh[tk]) for tk in oh.columns if oh[tk].dropna().shape[0]>30}
kospi=pd.read_parquet(f'{DATA}/kospi_yf.parquet')['close'].sort_index(); kospi.index=pd.to_datetime(kospi.index)
def regime_cross(ds_list):
    sma=kospi.rolling(20).mean(); lma=kospi.rolling(80).mean(); reg={}; md=False; stk=0; ss=None
    for d in ds_list:
        ts=pd.Timestamp(d); sv=sma.get(ts); lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d]=md; continue
        s=sv>lv
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
def gp(d,tk):
    ts=pd.Timestamp(d)
    if tk not in ADJ: return None
    s=ADJ[tk]
    if ts not in s.index:
        idx=s.index.searchsorted(ts)
        if idx>=len(s): return None
        ts=s.index[idx]
    v=s.get(ts)
    return v if (v is not None and pd.notna(v) and v>0) else None

def load_folder(folder):
    cr={}  # ds -> {tk: composite_rank}
    for f in sorted(glob.glob(f'{folder}/ranking_*.json')):
        ds=os.path.basename(f)[8:16]
        if not(ds.isdigit() and len(ds)==8): continue
        d=json.load(open(f,encoding='utf-8'))
        cr[ds]={str(x['ticker']).zfill(6):int(x.get('composite_rank',x['rank'])) for x in d['rankings']}
    return cr

def run(cr, EB=3, XB=6, SLOTS=3, TOPN=20, PEN=50):
    dates=sorted(cr.keys()); reg=regime_cross(dates)
    pf={}; eq=1.0; eh={}; turn=0
    def pen(c): return c if c<=TOPN else PEN
    for i,ds in enumerate(dates):
        ib=reg.get(ds,True); er=EB if ib else 0; xr=XB if ib else 8
        if i>=1 and pf:
            rs=[]
            for tk in pf:
                pp=gp(dates[i-1],tk); cp=gp(ds,tk)
                if pp and cp: rs.append(cp/pp-1)
            if rs: eq*=(1+np.mean(rs)*len(pf)/SLOTS)
        eh[ds]=eq
        if i>=1 and reg.get(dates[i-1],True)!=ib: pf.clear()
        if not ib: continue
        c0=cr.get(ds,{}); c1=cr.get(dates[i-1],{}) if i>=1 else {}; c2=cr.get(dates[i-2],{}) if i>=2 else {}
        wr={tk:c*0.4+pen(c1.get(tk,PEN))*0.35+pen(c2.get(tk,PEN))*0.25 for tk,c in c0.items()}
        for tk in list(pf):
            if wr.get(tk,999)>xr: del pf[tk]; turn+=1
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf: continue
            if len(pf)>=SLOTS: break
            cp=gp(ds,tk)
            if cp: pf[tk]=cp; turn+=1
    ea=np.array(list(eh.values()))
    if len(ea)<2: return None
    cagr=(ea[-1]**(252/len(ea))-1)*100
    p=np.maximum.accumulate(ea); mdd=-((ea-p)/p).min()*100
    cal=cagr/mdd if mdd>0 else 0
    return cal,cagr,mdd,turn,ea[-1]

print(f'{"":12}{"Calmar":>8}{"CAGR":>9}{"MDD":>7}{"회전":>6}{"최종배수":>9}')
res={}
for lbl,folder in [('0:pykrx연간','_sp0'),('1:DART TTM','_sp1')]:
    cr=load_folder(folder)
    r=run(cr)
    res[lbl]=r
    if r: print(f'{lbl:12}{r[0]:>8.2f}{r[1]:>8.1f}%{r[2]:>6.1f}%{r[3]:>6}{r[4]:>9.2f}')
    else: print(f'{lbl}: 데이터부족 ({len(cr)}일)')
# 에이피알 평균 cr (얼마나 구제됐나)
print('\n에이피알(278470) 평균 당일순위 (낮을수록 상위):')
for lbl,folder in [('0:pykrx연간','_sp0'),('1:DART TTM','_sp1')]:
    cr=load_folder(folder)
    ranks=[d.get('278470') for d in cr.values() if '278470' in d]
    inn=len([1 for d in cr.values() if '278470' in d]); tot=len(cr)
    print(f'  {lbl}: 랭킹 등장 {inn}/{tot}일, 평균cr {np.mean(ranks):.0f}' if ranks else f'  {lbl}: 등장 0일')
