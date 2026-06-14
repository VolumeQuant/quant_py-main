# -*- coding: utf-8 -*-
"""전문가 제안 검증 (2026-06-14): 변동성타겟팅 / vol정규화 낙폭속도 / HY / breadth.
production wr full-config replay 기반. 핵심: V자 낙폭 줄이되 CAGR/Calmar 보존되나."""
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
hy=pd.read_parquet(os.path.join(PROJ,'data_cache','hy_spread.parquet')).iloc[:,0].sort_index()
ma20,ma80=kc.rolling(20).mean(),kc.rolling(80).mean()
CASH_D=1.03**(1/252)-1

didx=pd.to_datetime([pxidx[d] for d in dates])
kc_a=kc.reindex(didx,method='ffill'); hy_a=hy.reindex(didx,method='ffill')
kret=kc_a.pct_change()
ewma_vol=kret.abs().ewm(halflife=20).mean()
vel5=(kc_a/kc_a.shift(5)-1)
velnorm=(vel5/(ewma_vol.values*np.sqrt(5)))
hy20=(hy_a-hy_a.shift(20))*100  # bp
F=pd.DataFrame({'kc':kc_a.values,'velnorm':velnorm.values,'hy20':hy20.values,
                'ma20':ma20.reindex(didx,method='ffill').values,
                'ma80':ma80.reindex(didx,method='ffill').values},index=dates)

def ma_reg():
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
BASE=ma_reg()
def ret1(tk,d,dn):
    if tk not in px.columns: return None
    s=px[tk];a,b=s.get(pxidx[d]),s.get(pxidx[dn])
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a<=0: return None
    r=b/a-1; return None if abs(r)>0.35 else r
def replay(reg):
    hold=set();rets=[]
    for i in range(len(dates)-1):
        d,dn=dates[i],dates[i+1]
        if not reg[d]: hold=set();rets.append(0.0);continue
        rank=rk[d]; hold={t for t in hold if rank.get(t,9999)<=6}
        if len(hold)<3:
            for t in sorted([t for t in rank if rank[t]<=3 and t not in hold],key=lambda t:rank[t]):
                if len(hold)>=3:break
                hold.add(t)
        pr=[ret1(t,d,dn) for t in hold];pr=[r for r in pr if r is not None]
        rets.append(float(np.mean(pr)) if pr else 0.0)
    return np.array(rets)
def metrics(r):
    eq=np.cumprod(1+r);n=len(r);cagr=(eq[-1]**(252/max(n,1))-1)*100
    peak=np.maximum.accumulate(np.concatenate([[1.0],eq]));mdd=abs(((np.concatenate([[1.0],eq])-peak)/peak).min())*100
    return cagr,mdd,(cagr/mdd if mdd>0 else 0)
def wdd(rets,lo,hi):
    sub=[rets[i] for i in range(len(rets)) if lo<=dates[i]<=hi]
    if not sub: return 0.0
    eq=np.cumprod(1+np.array(sub));peak=np.maximum.accumulate(eq);return abs(((eq-peak)/peak).min())*100

base=replay(BASE); bc=metrics(base)
print("="*74)
print(f"{'방법':<34}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}{'20코로나':>9}{'25-04':>8}")
print("="*74)
print(f"{'현행 (baseline)':<34}{bc[2]:>8.3f}{bc[0]:>7.0f}{bc[1]:>7.1f}{wdd(base,'20200101','20200501'):>8.1f}%{wdd(base,'20250401','20250601'):>7.1f}%")

# ===== 변동성 타겟팅 (전략수익 기준, 1일 lag, band) =====
def voltarget(br, downside=False, target_pct=50, cap=1.0, band=0.05):
    n=len(br); rv=np.full(n,np.nan)
    for t in range(20,n):
        w=br[t-20:t]
        if downside:
            neg=w[w<0]; rv[t]=(np.std(neg) if len(neg)>=3 else np.std(w))*np.sqrt(252)
        else: rv[t]=np.std(w)*np.sqrt(252)
    target=np.nanpercentile(rv,target_pct)
    out=np.zeros(n); pe=1.0
    for t in range(n):
        rvl=rv[t-1] if t>0 else np.nan
        e=1.0 if (np.isnan(rvl) or rvl<=0) else min(cap,target/rvl)
        if abs(e-pe)<band: e=pe
        out[t]=e*br[t]+(1-e)*CASH_D; pe=e
    return out
print("-"*74+"\n[변동성 타겟팅 — 타이밍없이 익스포저만 연속조절]")
for nm,kw in [('vol-target σ50 cap1.0',dict(target_pct=50)),
              ('vol-target σ65 cap1.0',dict(target_pct=65)),
              ('vol-target σ65 cap1.5',dict(target_pct=65,cap=1.5)),
              ('하방vol σ65 cap1.0',dict(target_pct=65,downside=True)),
              ('하방vol σ65 cap1.5',dict(target_pct=65,downside=True,cap=1.5))]:
    r=voltarget(base,**kw);c=metrics(r)
    print(f"{nm:<34}{c[2]:>8.3f}{c[0]:>7.0f}{c[1]:>7.1f}{wdd(r,'20200101','20200501'):>8.1f}%{wdd(r,'20250401','20250601'):>7.1f}%")

# ===== 회로차단기형 (regime 수정 후 replay) =====
def cb(velnorm_th=None,hy_th=None,exit_hys=3):
    reg={};active=False;clear=0
    for d in dates:
        f=F.loc[d];trig=False
        if velnorm_th and not pd.isna(f.velnorm) and f.velnorm<velnorm_th and f.kc<f.ma20: trig=True
        if hy_th and not pd.isna(f.hy20) and f.hy20>hy_th: trig=True
        if trig: active=True;clear=0
        elif active:
            ok=(pd.isna(f.velnorm) or f.velnorm>-0.5) and f.kc>f.ma20 if velnorm_th else (pd.isna(f.hy20) or f.hy20<50)
            if ok: clear+=1
            else: clear=0
            if clear>=exit_hys: active=False
        reg[d]=BASE[d] and not active
    return reg
print("-"*74+"\n[똑똑한 회로차단기 — vol정규화 낙폭속도 / HY급변]")
for nm,kw in [('vol정규화 낙폭<-2.5+추세',dict(velnorm_th=-2.5)),
              ('vol정규화 낙폭<-3.0+추세',dict(velnorm_th=-3.0)),
              ('HY 20일>+100bp',dict(hy_th=100)),
              ('HY 20일>+150bp',dict(hy_th=150))]:
    r=replay(cb(**kw));c=metrics(r)
    print(f"{nm:<34}{c[2]:>8.3f}{c[0]:>7.0f}{c[1]:>7.1f}{wdd(r,'20200101','20200501'):>8.1f}%{wdd(r,'20250401','20250601'):>7.1f}%")
print("="*74)
print("판정: V자낙폭 ↓ + Calmar/CAGR baseline 유지(노이즈 ±0.10)면 진짜 개선")
