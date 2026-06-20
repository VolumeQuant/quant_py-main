# -*- coding: utf-8 -*-
"""적대검증: Dual-confirmation 조기 defense = MA크로스 + (HY 20일 상승 AND 브레드스 급락) 동시.
교집합(AND)이 단독 노이즈를 거른다는 주장 검증. _vcrash/_mcclellan 하니스 재사용."""
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
px=pd.read_parquet(os.path.join(PROJ,'data_cache','all_ohlcv_adj_20170601_20260619.parquet')).replace(0,np.nan).sort_index()
pxidx={d:pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]) for d in dates}
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0].sort_index()
hy=pd.read_parquet(os.path.join(PROJ,'data_cache','hy_spread.parquet')).iloc[:,0].sort_index()
ma20,ma80=kc.rolling(20).mean(),kc.rolling(80).mean()
CASH_D=1.03**(1/252)-1

# ===== 브레드스: 전종목 %above-MA200 + (신고가-신저가) =====
biz=px[px.notna().sum(axis=1)>=100]
ma200_all=biz.rolling(200).mean()
above200=(biz>ma200_all).sum(axis=1)/biz.notna().sum(axis=1)   # %above MA200
hi252=biz.rolling(252).max(); lo252=biz.rolling(252).min()
nethl=((biz>=hi252).sum(axis=1)-(biz<=lo252).sum(axis=1))/biz.notna().sum(axis=1)  # net new high ratio
ab_d=above200.diff(10)  # 10일 변화 (급락 감지)

didx=pd.to_datetime([pxidx[d] for d in dates])
hy_a=hy.reindex(didx,method='ffill'); hy20=((hy_a-hy_a.shift(20))*100)  # bp, z 대신 절대
ab_a=above200.reindex(didx,method='ffill'); abd_a=ab_d.reindex(didx,method='ffill')
nethl_a=nethl.reindex(didx,method='ffill')
# HY z-score (252일 rolling)
hy_z=((hy_a-hy_a.rolling(252).mean())/hy_a.rolling(252).std())

F=pd.DataFrame({'hy20':hy20.values,'hy_z':hy_z.values,'above200':ab_a.values,
                'abd':abd_a.values,'nethl':nethl_a.values},index=dates)

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
def wf(rets,lo,hi):
    sub=[rets[i] for i in range(len(rets)) if lo<=dates[i]<=hi]
    if len(sub)<40: return 0.0
    return metrics(np.array(sub))[2]

base=replay(BASE); bc=metrics(base)
print("="*92)
print(f"{'방법':<40}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}{'20코로나':>9}{'25-04':>8}{'22WF':>7}")
print("="*92)
def row(nm,r):
    c=metrics(r)
    print(f"{nm:<40}{c[2]:>8.3f}{c[0]:>7.0f}{c[1]:>7.1f}{wdd(r,'20200101','20200501'):>8.1f}%{wdd(r,'20250401','20250601'):>7.1f}%{wf(r,'20220101','20221231'):>7.2f}")
row('현행 (baseline)',base)

# ===== Dual-confirmation 조기 defense =====
# MA가 아직 boost여도, (HY 상승 AND 브레드스 급락) 동시면 조기 defense
def dualconf(hy_th, abd_th=None, nethl_th=None, use_z=False, clear_days=5):
    reg={};active=False;clear=0
    for d in dates:
        f=F.loc[d]
        hyhot = (f.hy_z>hy_th) if use_z else (f.hy20>hy_th)
        hyhot = bool(hyhot) and not pd.isna(f.hy_z if use_z else f.hy20)
        brk=False
        if abd_th is not None and not pd.isna(f.abd): brk = f.abd < abd_th
        if nethl_th is not None and not pd.isna(f.nethl): brk = brk or (f.nethl < nethl_th)
        trig = hyhot and brk
        if trig: active=True;clear=0
        elif active:
            calm = (not hyhot)
            if calm: clear+=1
            else: clear=0
            if clear>=clear_days: active=False
        reg[d]=BASE[d] and not active
    return reg

print("-"*92+"\n[Dual-conf: HY(절대bp 상승) AND 브레드스(%aboveMA200 10일변화) 급락]")
for hy_th,abd_th in [(50,-0.10),(50,-0.15),(100,-0.10),(100,-0.15),(150,-0.10)]:
    r=replay(dualconf(hy_th=hy_th,abd_th=abd_th))
    row(f'HY>+{hy_th}bp AND aboveMA200Δ10<{abd_th}',r)
print("-"*92+"\n[Dual-conf: HY z-score AND 브레드스 급락]")
for hyz,abd_th in [(1.0,-0.10),(1.5,-0.10),(1.0,-0.15),(2.0,-0.10)]:
    r=replay(dualconf(hy_th=hyz,abd_th=abd_th,use_z=True))
    row(f'HY z>{hyz} AND aboveMA200Δ10<{abd_th}',r)
print("-"*92+"\n[Dual-conf: HY AND net신고가신저가 음수 심화]")
for hy_th,nh in [(50,-0.05),(100,-0.05),(100,-0.10)]:
    r=replay(dualconf(hy_th=hy_th,nethl_th=nh))
    row(f'HY>+{hy_th}bp AND netHL<{nh}',r)

# 단독 비교 (AND가 정말 단독보다 나은지)
print("-"*92+"\n[단독 신호 — AND의 우위 입증용]")
def single(hy_th=None,abd_th=None,use_z=False):
    reg={}
    for d in dates:
        f=F.loc[d];trig=False
        if hy_th is not None:
            v=f.hy_z if use_z else f.hy20
            if not pd.isna(v) and v>hy_th: trig=True
        if abd_th is not None and not pd.isna(f.abd) and f.abd<abd_th: trig=True
        reg[d]=BASE[d] and not trig
    return reg
row('HY>+100bp 단독',replay(single(hy_th=100)))
row('aboveMA200Δ10<-0.10 단독',replay(single(abd_th=-0.10)))
print("="*92)
print(f"코로나 baseline MDD={wdd(base,'20200101','20200501'):.1f}% / 25-04={wdd(base,'20250401','20250601'):.1f}% / 22WF={wf(base,'20220101','20221231'):.2f}")
print("판정: Calmar baseline 유지(±0.10) + V자낙폭↓ + 22WF 안깨짐 = 진짜개선. 아니면 휩쏘세금.")
