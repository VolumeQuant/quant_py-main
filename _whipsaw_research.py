# -*- coding: utf-8 -*-
"""단기 휩쏘 회피 연구 1단계: 휩쏘(≤3일 이탈) vs 견조(>10일 보유)가 진입시점에 구별되나?
구별되면 필터 가능, 같으면 분리불가(미국 시스템 결론). _sp0b_co 현재전략."""
import sys,io,glob,os,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
import numpy as np, pandas as pd
PROJ=r'C:\dev'
def ba(s):
    r=s.pct_change(fill_method=None); ev=r[(r<-0.33)|(r>0.45)]; s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50: s2.loc[s2.index<d]*=f
    return s2
px=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
didx={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}; arr=px.values; cols={c:i for i,c in enumerate(px.columns)}
def ret(tk,d0,d1):
    ci=cols.get(tk); i0=didx.get(d0); i1=didx.get(d1)
    if ci is None or i0 is None or i1 is None: return None
    p0,p1=arr[i0,ci],arr[i1,ci]
    return (p1/p0-1) if (p0>0 and p1>0) else None
RANK={}; FEAT={}
for f in sorted(glob.glob(os.path.join(PROJ,'_sp0b_co','ranking_*.json'))):
    d=os.path.basename(f)[8:16]
    if d>='20190102':
        R=json.load(open(f,encoding='utf-8'))['rankings']
        RANK[d]={x['ticker']:x.get('composite_rank',x['rank']) for x in R}
        FEAT[d]={x['ticker']:x for x in R}
days=sorted(RANK)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]; kc.index=pd.to_datetime(kc.index)
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
reg={};md=True;stk=0;ss=None;dsb={}  # dsb=days since boost start
bstart=0
for i,d in enumerate(days):
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts in kc.index and not pd.isna(ma80.get(ts,np.nan)):
        s=bool(ma20[ts]>ma80[ts]); stk=stk+1 if s==ss else 1; ss=s
        if stk>=5 and md!=s: md=s; bstart=i
    reg[d]=md; dsb[d]=i-bstart
wrrank={}; wrval={}
for i,d in enumerate(days):
    c0=RANK[d]; p1={t:r for t,r in (RANK[days[i-1]] if i>=1 else {}).items() if r<=20}; p2={t:r for t,r in (RANK[days[i-2]] if i>=2 else {}).items() if r<=20}
    wr={t:c0[t]*0.4+p1.get(t,50)*0.35+p2.get(t,50)*0.25 for t in c0}
    order=sorted(wr,key=lambda x:wr[x]); wrrank[d]={t:k+1 for k,t in enumerate(order)}; wrval[d]=wr
# 상태머신 + 진입특성 기록
hold={}; eps=[]
for i,d in enumerate(days):
    if not reg[d]:
        for tk in list(hold): hold.pop(tk)
        continue
    wr=wrrank[d]
    for tk in list(hold):
        if wr.get(tk,999)>6: eps.append((tk,hold[tk],d)); hold.pop(tk)
    for tk,rk in wr.items():
        if rk<=3 and tk not in hold:
            # 진입특성
            wv=wrval[d]; order=sorted(wv,key=lambda x:wv[x])
            gap4=(wv[order[3]]-wv[tk]) if len(order)>3 else 0  # #4와의 wr격차(클수록 견고한 top3)
            ft=FEAT[d].get(tk,{})
            hold[tk]=dict(d0=d,rk=rk,score=ft.get('score'),mom=ft.get('momentum_s'),mom10=ft.get('mom_10_z'),
                          gro=ft.get('growth_s'),val=ft.get('value_s'),oh=ft.get('overheat_pen'),gap4=gap4,dsb=dsb[d])
rows=[]
for tk,h,d1 in eps:
    r=ret(tk,h['d0'],d1); dur=days.index(d1)-days.index(h['d0'])
    if r is not None: rows.append({**h,'dur':dur,'ret':r,'tk':tk})
df=pd.DataFrame(rows)
df['grp']=np.where(df.dur<=3,'휩쏘(≤3일)',np.where(df.dur>10,'견조(>10일)','중간'))
print(f"episode {len(df)}개\n")
print(f"{'특성':<16}{'휩쏘(≤3일)':>14}{'견조(>10일)':>14}{'중간':>12}")
for col,lbl in [('rk','진입순위'),('score','당일점수'),('mom','모멘텀_s'),('mom10','mom10_z'),('gro','성장_s'),('val','밸류_s'),('oh','과열캡'),('gap4','#4와wr격차'),('dsb','boost경과일')]:
    r=df.groupby('grp')[col].mean()
    print(f"{lbl:<16}{r.get('휩쏘(≤3일)',np.nan):>14.2f}{r.get('견조(>10일)',np.nan):>14.2f}{r.get('중간',np.nan):>12.2f}")
print(f"\n건수: " + ' '.join(f"{k} {v}" for k,v in df.grp.value_counts().items()))
print("\n→ 휩쏘와 견조의 진입특성이 뚜렷이 다르면(특히 점수·gap4·mom10) 필터 가능. 비슷하면 분리불가.")
