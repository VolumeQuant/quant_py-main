# -*- coding: utf-8 -*-
"""초단기 V자 급락(2020코로나·2025-04) 회로차단기 연구 (2026-06-14).
느린 MA20/80 대신 빠른 트리거(VIX·KOSPI 급락속도)로 잡을 수 있나 full-config 검증.
회로차단기 = MA국면 OR 빠른위험 → 현금. 트리거 풀리면 즉시 복귀(fast-in-fast-out).
"""
import sys, io, os, glob, json
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

rk = {}
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_2019*.json'))
              + glob.glob(os.path.join(PROJ,'state','ranking_202[0-6]*.json'))):
    dt = os.path.basename(f).replace('ranking_','').replace('.json','')
    if dt < '20190102': continue
    try:
        d = json.load(open(f, encoding='utf-8'))
        rk[dt] = {x['ticker']: x['weighted_rank'] for x in d['rankings']}
    except Exception: pass
dates = sorted(rk)
px = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_*.parquet')),
                            key=lambda f: f.split('_')[-1])[-1]).replace(0,np.nan).sort_index()
pxidx = {d: pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]) for d in dates}

kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0].sort_index()
vix = pd.read_parquet(os.path.join(PROJ,'data_cache','vix_yf_full.parquet')).iloc[:,0].sort_index()
ma20, ma80 = kc.rolling(20).mean(), kc.rolling(80).mean()

# 트레이딩 날짜별 빠른 위험피처
didx = pd.to_datetime([pxidx[d] for d in dates])
kc_a = kc.reindex(didx, method='ffill')
vix_a = vix.reindex(didx, method='ffill')
ret5  = (kc_a / kc_a.shift(5) - 1) * 100
ret10 = (kc_a / kc_a.shift(10) - 1) * 100
dd20  = (kc_a / kc_a.rolling(20).max() - 1) * 100
feat = pd.DataFrame({'kc':kc_a.values,'vix':vix_a.values,'ret5':ret5.values,
                     'ret10':ret10.values,'dd20':dd20.values}, index=dates)

def ma_reg():
    md=True; stk=0; ss=None; reg={}
    for d in dates:
        ts=pxidx[d]
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md; continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
BASE = ma_reg()

def ret1(tk,d,dn):
    if tk not in px.columns: return None
    s=px[tk]; a,b=s.get(pxidx[d]),s.get(pxidx[dn])
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a<=0: return None
    r=b/a-1
    return None if abs(r)>0.35 else r

def replay(reg):
    hold=set(); rets=[]
    for i in range(len(dates)-1):
        d,dn=dates[i],dates[i+1]
        if not reg[d]: hold=set(); rets.append(0.0); continue
        rank=rk[d]
        hold={t for t in hold if rank.get(t,9999)<=6}
        if len(hold)<3:
            for t in sorted([t for t in rank if rank[t]<=3 and t not in hold], key=lambda t: rank[t]):
                if len(hold)>=3: break
                hold.add(t)
        pr=[ret1(t,d,dn) for t in hold]; pr=[r for r in pr if r is not None]
        rets.append(float(np.mean(pr)) if pr else 0.0)
    return np.array(rets)

def metrics(r):
    eq=np.cumprod(1+r); n=len(r)
    cagr=(eq[-1]**(252/max(n,1))-1)*100
    peak=np.maximum.accumulate(np.concatenate([[1.0],eq]))
    mdd=abs(((np.concatenate([[1.0],eq])-peak)/peak).min())*100
    return cagr,mdd,(cagr/mdd if mdd>0 else 0)

def cb_reg(vix_th=None, ret5_th=None, dd20_th=None, cooldown=0):
    """MA국면 OR 빠른위험 → 현금. 트리거 풀리면 즉시 복귀(+쿨다운)."""
    reg={}; cd=0
    for d in dates:
        f=feat.loc[d]; trig=False
        if vix_th and not pd.isna(f.vix) and f.vix>vix_th: trig=True
        if ret5_th and not pd.isna(f.ret5) and f.ret5<ret5_th: trig=True
        if dd20_th and not pd.isna(f.dd20) and f.dd20<dd20_th: trig=True
        if trig: cd=cooldown
        elif cd>0: cd-=1; trig=True
        reg[d] = BASE[d] and not trig
    return reg

def dd_window(rets, lo, hi):
    """특정 구간 전략 낙폭"""
    sub=[(dates[i],rets[i]) for i in range(len(rets)) if lo<=dates[i]<=hi]
    if not sub: return 0.0
    eq=np.cumprod(1+np.array([r for _,r in sub]))
    peak=np.maximum.accumulate(eq)
    return abs(((eq-peak)/peak).min())*100

print("="*70)
print("【1】 V자 급락 때 데이터가 어떻게 움직였나 (트리거 가능성)")
print("="*70)
for nm,lo,hi in [('2020 코로나','20200201','20200401'),('2025-04','20250401','20250520')]:
    sub=feat[(feat.index>=lo)&(feat.index<=hi)]
    print(f"\n● {nm} ({lo}~{hi})")
    print(f"   VIX 최고 {sub.vix.max():.0f} / KOSPI 5일최저수익 {sub.ret5.min():+.1f}% / 20일고점대비 최저 {sub.dd20.min():+.1f}%")

print("\n"+"="*70)
print("【2】 회로차단기 full-config 검증 (트리거별)")
print("="*70)
base=replay(BASE); bc=metrics(base)
bd20=dd_window(base,'20200101','20200501'); bd25=dd_window(base,'20250401','20250601')
print(f"{'국면 룰':<30}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}{'20코로나낙폭':>11}{'25-04낙폭':>10}")
print(f"{'MA만 (현행)':<30}{bc[2]:>8.3f}{bc[0]:>7.0f}{bc[1]:>7.1f}{bd20:>10.1f}%{bd25:>9.1f}%")
variants=[
 ('MA + VIX>40', dict(vix_th=40)),
 ('MA + VIX>36', dict(vix_th=36)),
 ('MA + VIX>30', dict(vix_th=30)),
 ('MA + KOSPI5일<-8%', dict(ret5_th=-8)),
 ('MA + KOSPI5일<-10%', dict(ret5_th=-10)),
 ('MA + 20일고점대비<-10%', dict(dd20_th=-10)),
 ('MA + 20일고점대비<-12%', dict(dd20_th=-12)),
 ('MA + VIX>36 +쿨다운5', dict(vix_th=36,cooldown=5)),
 ('MA + VIX>36 OR 5일<-8%', dict(vix_th=36,ret5_th=-8)),
 ('MA + VIX>40 OR 20일<-12%', dict(vix_th=40,dd20_th=-12)),
]
for nm,kw in variants:
    r=replay(cb_reg(**kw)); c=metrics(r)
    d20=dd_window(r,'20200101','20200501'); d25=dd_window(r,'20250401','20250601')
    print(f"{nm:<30}{c[2]:>8.3f}{c[0]:>7.0f}{c[1]:>7.1f}{d20:>10.1f}%{d25:>9.1f}%")
print("\n(낙폭 작아질수록 V자 방어 성공. Calmar/CAGR이 baseline보다 안 떨어져야 채택가치)")
