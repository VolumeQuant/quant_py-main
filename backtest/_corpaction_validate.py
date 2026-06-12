# -*- coding: utf-8 -*-
"""권리락 보정 #2 넓은 검증: 보정 전후로 매수(top3 wr)/이탈경계가 바뀐 날 있나.
4/28~6/11 전 영업일. 각 날 보정 cr → 보정 wr → top3/top6 set 비교."""
import pandas as pd, numpy as np, glob, json, os
from scipy.stats import norm
oh_raw=pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2019*_*.parquet'))[-1]).replace(0,np.nan)
oh_raw.index=pd.to_datetime(oh_raw.index)
out=open('_caval.txt','w',encoding='utf-8')

def backadjust(s):
    r=s.pct_change(fill_method=None); ev=r[(r<-0.33)|(r>0.45)]
    if ev.empty: return s
    s2=s.copy()
    for d,ret in ev.items():
        f=1+ret
        if 0.05<abs(f)<10: s2.loc[s2.index<d]*=f
    return s2
ADJ={tk:backadjust(oh_raw[tk]) for tk in oh_raw.columns if oh_raw[tk].dropna().shape[0]>=260}

L12=252; VF=15.0
def vm(s, asof):
    s=s[s.index<=asof].dropna()
    if len(s)<L12+1: return np.nan
    cur=s.iloc[-1]; st=s.iloc[-(L12+1)]
    if not(st>0 and cur>0): return np.nan
    ret=(cur/st-1)*100
    dr=s.iloc[-(L12+1):].pct_change(fill_method=None).iloc[1:]
    return ret/max(dr.std()*np.sqrt(252)*100, VF)
def blom(x):
    n=len(x); r=x.rank(method='average'); u=((r-0.375)/(n+0.25)).clip(0.001,0.999); return pd.Series(norm.ppf(u),index=x.index)
def secz(raw, sec, ms=10):
    s=pd.Series(raw); se=pd.Series({k:sec.get(k,'?') for k in raw}); z=blom(s)
    for sn in se.unique():
        m=se==sn
        if m.sum()>=ms: z[m]=blom(s[m])
    return z

def corrected_cr(ds):
    f=f'state/ranking_{ds}.json'
    if not os.path.exists(f): return None
    rk=json.load(open(f,encoding='utf-8')); elig={str(x['ticker']).zfill(6):x for x in rk['rankings']}
    asof=pd.Timestamp(ds); sec={tk:elig[tk].get('sector','?') for tk in elig}
    mw={tk:vm(oh_raw[tk],asof) for tk in elig if tk in oh_raw.columns}
    mr={tk:vm(ADJ[tk],asof) for tk in elig if tk in ADJ}
    mw={k:v for k,v in mw.items() if pd.notna(v)}; mr={k:v for k,v in mr.items() if pd.notna(v)}
    zw=secz(mw,sec); zr=secz(mr,sec)
    rows=[]
    for tk in elig:
        sc=elig[tk].get('score',0); d=(zr[tk]-zw[tk]) if (tk in zw.index and tk in zr.index) else 0.0
        rows.append((tk, elig[tk]['name'], sc, sc+0.30*d))
    crold={t:i+1 for i,(t,_,_,_) in enumerate(sorted(rows,key=lambda x:-x[2]))}
    crnew={t:i+1 for i,(t,_,_,_) in enumerate(sorted(rows,key=lambda x:-x[3]))}
    nm={t:n for t,n,_,_ in rows}
    return crold, crnew, nm

# 윈도우 영업일
allf=sorted(glob.glob('state/ranking_2026*.json'))
days=[os.path.basename(f)[8:16] for f in allf]
days=[d for d in days if '20260428'<=d<='20260611']
CRO={}; CRN={}; NM={}
for ds in days:
    r=corrected_cr(ds)
    if r: CRO[ds],CRN[ds],nm=r; NM.update(nm)
print(f'{len(CRO)}일 계산',flush=True)

def pen(c): return c if c<=20 else 50
def wr_set(CR, ds, idx_days):
    # CR: dict ds->{tk:cr}; idx_days=[t0,t1,t2]
    t0,t1,t2=idx_days
    c0=CR.get(t0,{});
    if not c0: return None
    wr={}
    for tk,c in c0.items():
        wr[tk]=c*0.4+pen(CR.get(t1,{}).get(tk,50))*0.35+pen(CR.get(t2,{}).get(tk,50))*0.25
    order=sorted(wr,key=lambda t:wr[t])
    return order

out.write('=== 보정 전후 매수 top3(wr) / 이탈경계(top6) 비교 ===\n')
out.write(f"{'날짜':<9}{'top3 보정전':>22}{'top3 보정후':>22}{'바뀜?':>7}\n")
diff_days=0
dd=sorted(CRO.keys())
for i in range(2,len(dd)):
    d3=[dd[i],dd[i-1],dd[i-2]]
    oo=wr_set(CRO,dd[i],d3); nn=wr_set(CRN,dd[i],d3)
    if oo is None or nn is None: continue
    t3o=[NM.get(t,t) for t in oo[:3]]; t3n=[NM.get(t,t) for t in nn[:3]]
    t6o=set(oo[:6]); t6n=set(nn[:6])
    chg = (oo[:3]!=nn[:3]) or (t6o!=t6n)
    if chg: diff_days+=1
    mark='★변경' if (oo[:3]!=nn[:3]) else ('(6위셋만)' if t6o!=t6n else '')
    if chg:
        out.write(f"{dd[i][4:]:<9}{'/'.join(t3o):>22}{'/'.join(t3n):>22}{mark:>7}\n")
out.write(f'\n총 {len(dd)-2}일 중 매수/이탈경계 바뀐 날: {diff_days}일\n')
if diff_days==0:
    out.write('→ 권리락 버그가 매수/이탈 결정을 바꾼 적 없음 (표시·watchlist만 왜곡). 보정은 안전.\n')
out.close(); print('done')
