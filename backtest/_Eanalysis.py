# -*- coding: utf-8 -*-
"""E(고모멘텀 V면제) 분석 — state_Cfull(필터OFF 전체) 재필터링 → baseline vs E.
① E코호트(V<-1.5 고모멘텀) forward ② 3슬롯 replay BT(전체+WF+LOWO). 재생성 완료 후 실행."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P='C:/dev'
SD=P+'/state_Cfull'
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan);px=px.dropna(how='all')
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
def fwd(t,d,h):
    if t not in pcol or d not in tdi: return None
    i=tdi[d];d2=tdays[min(i+h,len(tdays)-1)];p0=parr[i,pcol[t]];p1=parr[tdi[d2],pcol[t]]
    return (p1/p0-1)*100 if p0>0 and p1>0 else None
# 로드
days=[];RK={}
for f in sorted(glob.glob(SD+'/ranking_*.json')):
    d=os.path.basename(f)[8:16]
    if d in tdi:
        RK[d]=json.load(open(f,encoding='utf-8'))['rankings'];days.append(d)
days=sorted(days)
print(f"mode C 로드: {len(days)}일 ({days[0]}~{days[-1]})")
F=['value_s','momentum_s','quality_s','growth_s']
def ok(x): return all(isinstance(x.get(k),(int,float)) for k in F+['score'])
def base_pass(x): return x['value_s']>=-1.5 and x['quality_s']>=-1.5 and x['growth_s']>=-1.5 and x['momentum_s']>=-1.5
def E_pass(x): return x['quality_s']>=-1.5 and x['growth_s']>=-1.5 and x['momentum_s']>=-1.5 and (x['value_s']>=-1.5 or x['momentum_s']>=1.0)
def ranked(d,passfn):
    xs=[x for x in RK[d] if ok(x) and passfn(x)]
    xs.sort(key=lambda z:-z['score']);return [x['ticker'] for x in xs]
# === ① E 코호트 forward ===
ecoh=[];kept=[]
for d in days[:-1]:
    if tdi[d]>len(tdays)-61: continue
    for x in RK[d]:
        if not ok(x): continue
        r=fwd(x['ticker'],d,60)
        if r is None: continue
        if x['value_s']<-1.5 and x['momentum_s']>=1.0 and x['quality_s']>=-1.5 and x['growth_s']>=-1.5: ecoh.append(r)
        elif base_pass(x): kept.append(r)
print(f"\n[① E 코호트 forward60 — {len(days)}일]")
for a,nm in [(ecoh,'★E가 살리는 코호트(고모멘텀 비싼)'),(kept,'baseline 통과(정상)')]:
    a=np.array(a)
    if len(a)>=5: print(f"  {nm:30s} n={len(a):5d} 평균{a.mean():+.1f}% 승률{(a>0).mean()*100:.0f}% 중앙{np.median(a):+.1f}%")
# === ② 3슬롯 replay BT ===
reg={};md=True;stk=0;ss=None
for d in days:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
    s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
    if stk>=5 and md!=s: md=s
    reg[d]=md
def sim(passfn,lo=None,hi=None,excl=None):
    held=[];a=[];prev=None
    for d in days:
        ins=(lo is None) or (lo<=d<=hi);ret=0.0
        if held and prev and ins:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        if ins: a.append(ret)
        if not reg.get(d,True): held=[]
        else:
            rk=[t for t in ranked(d,passfn) if t!=excl]
            held=[t for t in held if t in rk[:6]]
            for t in rk[:3]:
                if len(held)>=3: break
                if t not in held: held.append(t)
        prev=d
    a=np.array(a);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
segs=[('전체',None,None),('19-21',days[0],'20211231'),('약세22-23','20220101','20231231'),('24-26','20240101',days[-1])]
print(f"\n[② 3슬롯 BT — baseline vs E]")
print(f"  {'':14s}{'Calmar':>8s}{'CAGR':>7s}{'MDD':>8s}")
for nm,pf in [('baseline',base_pass),('E(고모멘텀V면제)',E_pass)]:
    c,cg,m=sim(pf);print(f"  {nm:14s}{c:>8.2f}{cg:>6.0f}%{m:>7.1f}%")
print(f"\n  [기간별 Calmar]{'':6s}"+"".join(f"{s[0]:>10s}" for s in segs))
for nm,pf in [('baseline',base_pass),('E',E_pass)]:
    print(f"  {nm:18s}"+"".join(f"{sim(pf,s[1],s[2])[0]:>10.2f}" for s in segs))
print(f"\n  [LOWO Calmar]{'':8s}{'baseline':>10s}{'E':>8s}")
for nm,ex in [('-브이엠','089970'),('-제룡전기','033100'),('-SK하이닉스','000660')]:
    print(f"  {nm:16s}{sim(base_pass,excl=ex)[0]:>10.2f}{sim(E_pass,excl=ex)[0]:>8.2f}")
