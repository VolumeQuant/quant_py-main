# -*- coding: utf-8 -*-
"""단계적 청산(50%→나머지 50%) vs 현행 전량청산 검증 (2026-06-14).
stage1=현행 MA20<MA80(5일) → 50% 청산. stage2(더 심각) → 나머지 50%.
stage2 후보: KOSPI<MA200(지속하락) / 고점대비 낙폭 / 방어 지속일수."""
import sys, io, os, glob, json
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rk={}
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_2019*.json'))
              + glob.glob(os.path.join(PROJ,'state','ranking_202[0-6]*.json'))):
    dt=os.path.basename(f).replace('ranking_','').replace('.json','')
    if dt<'20190102': continue
    try:
        d=json.load(open(f,encoding='utf-8')); rk[dt]={x['ticker']:x['weighted_rank'] for x in d['rankings']}
    except Exception: pass
dates=sorted(rk)
px=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_*.parquet')),
                          key=lambda f:f.split('_')[-1])[-1]).replace(0,np.nan).sort_index()
pxidx={d:pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]) for d in dates}
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0].sort_index()
ma20,ma80,ma200=kc.rolling(20).mean(),kc.rolling(80).mean(),kc.rolling(200).mean()
CASH_D=1.03**(1/252)-1
didx=pd.to_datetime([pxidx[d] for d in dates])
kc_a=kc.reindex(didx,method='ffill')
F=pd.DataFrame({'kc':kc_a.values,'ma200':ma200.reindex(didx,method='ffill').values,
                'dd250':(kc_a/kc_a.rolling(250).max()-1).values*100},index=dates)

def base_reg():
    md=True;stk=0;ss=None;reg={}
    for d in dates:
        ts=pxidx[d]
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
BASE=base_reg()
def ret1(tk,d,dn):
    if tk not in px.columns: return None
    s=px[tk];a,b=s.get(pxidx[d]),s.get(pxidx[dn])
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a<=0: return None
    r=b/a-1; return None if abs(r)>0.35 else r
def replay_exp(exp):
    hold=set();rets=[]
    for i in range(len(dates)-1):
        d,dn=dates[i],dates[i+1]
        e=exp[d]
        if e<=0: hold=set();rets.append(0.0);continue
        rank=rk[d]; hold={t for t in hold if rank.get(t,9999)<=6}
        if len(hold)<3:
            for t in sorted([t for t in rank if rank[t]<=3 and t not in hold],key=lambda t:rank[t]):
                if len(hold)>=3:break
                hold.add(t)
        pr=[ret1(t,d,dn) for t in hold];pr=[r for r in pr if r is not None]
        port=float(np.mean(pr)) if pr else 0.0
        rets.append(e*port+(1-e)*CASH_D)
    return np.array(rets)
def metrics(r):
    eq=np.cumprod(1+r);n=len(r);cagr=(eq[-1]**(252/max(n,1))-1)*100
    peak=np.maximum.accumulate(np.concatenate([[1.0],eq]));mdd=abs(((np.concatenate([[1.0],eq])-peak)/peak).min())*100
    return cagr,mdd,(cagr/mdd if mdd>0 else 0)
def wret(rets,lo,hi):
    sub=[rets[i] for i in range(len(rets)) if lo<=dates[i]<=hi]
    return (np.prod([1+x for x in sub])-1)*100 if sub else 0.0

def phased(stage2='ma200',dd_th=-15,days_th=15,mild=0.5):
    exp={};dc=0
    for d in dates:
        if BASE[d]: exp[d]=1.0;dc=0
        else:
            dc+=1;f=F.loc[d];sev=False
            if stage2=='ma200': sev=(not pd.isna(f.ma200)) and f.kc<f.ma200
            elif stage2=='dd': sev=(not pd.isna(f.dd250)) and f.dd250<dd_th
            elif stage2=='days': sev=dc>=days_th
            exp[d]=0.0 if sev else mild
    return exp

# baseline (전량청산 = mild 0)
b=replay_exp({d:(1.0 if BASE[d] else 0.0) for d in dates}); bc=metrics(b)
print("="*78)
print(f"{'방법':<30}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}{'2022약세장':>11}{'25-04후60일':>12}")
print("="*78)
print(f"{'현행 전량청산(100%)':<30}{bc[2]:>8.3f}{bc[0]:>7.0f}{bc[1]:>7.1f}{wret(b,'20211201','20221231'):>10.1f}%{wret(b,'20250417','20250717'):>11.1f}%")
print("-"*78)
for nm,kw in [('단계 50%→MA200깨면 전량',dict(stage2='ma200')),
              ('단계 50%→고점-15%면 전량',dict(stage2='dd',dd_th=-15)),
              ('단계 50%→고점-20%면 전량',dict(stage2='dd',dd_th=-20)),
              ('단계 50%→방어15일지속 전량',dict(stage2='days',days_th=15)),
              ('단계 50%→방어30일지속 전량',dict(stage2='days',days_th=30)),
              ('단순 50%만(2단계 없음)',dict(stage2='none',mild=0.5))]:
    r=replay_exp(phased(**kw));c=metrics(r)
    print(f"{nm:<30}{c[2]:>8.3f}{c[0]:>7.0f}{c[1]:>7.1f}{wret(r,'20211201','20221231'):>10.1f}%{wret(r,'20250417','20250717'):>11.1f}%")
print("="*78)
print("2022약세장: 높을수록(덜 마이너스) 보호 약화. 25-04후: 높을수록 헛방어 회복 잘잡음.")
print("판정: Calmar baseline 유지(±0.10) + 2022 보호 안깨지면서 25-04 개선이면 채택가치.")
