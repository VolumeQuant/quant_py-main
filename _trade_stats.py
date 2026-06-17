# -*- coding: utf-8 -*-
"""현재전략(_sp0b_co, corp-OFF, 7.4년) trade-level 다각도 통계.
episode = top3 진입(매수) → 6위밖 이탈 or 방어청산(매도). 수익=진입일종가→이탈일종가(ba보정, 비용前).
※ 순위궤적 기반 proxy(3슬롯/✅검증 미반영), per-position 수익(포트폴리오 가중 아님)."""
import sys,io,glob,os,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
import pandas as pd, numpy as np
PROJ=r'C:\dev'
def ba(s):
    r=s.pct_change(fill_method=None); ev=r[(r<-0.33)|(r>0.45)]; s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50: s2.loc[s2.index<d]*=f
    return s2
px=pd.read_parquet(sorted(glob.glob(PROJ+r'\data_cache\all_ohlcv_2017*_2026061*.parquet'))[-1]).replace(0,np.nan).apply(ba)
didx={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}; arr=px.values; cols={c:i for i,c in enumerate(px.columns)}
def ret(tk,d0,d1):
    ci=cols.get(tk); i0=didx.get(d0); i1=didx.get(d1)
    if ci is None or i0 is None or i1 is None: return None
    p0,p1=arr[i0,ci],arr[i1,ci]
    return (p1/p0-1) if (p0>0 and p1>0) else None
cr={}; nm={}
for f in sorted(glob.glob(PROJ+r'\_sp0b_co\ranking_*.json')):
    d=os.path.basename(f)[8:16]
    if d>='20190102':
        R=json.load(open(f,encoding='utf-8'))['rankings']
        cr[d]={x['ticker']:x.get('composite_rank',x['rank']) for x in R}
        for x in R: nm[x['ticker']]=x['name']
days=sorted(cr)
kc=pd.read_parquet(PROJ+r'\data_cache\kospi_yf.parquet').iloc[:,0]; kc.index=pd.to_datetime(kc.index)
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
reg={};md=True;stk=0;ss=None
for d in days:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
    s=bool(ma20[ts]>ma80[ts]); stk=stk+1 if s==ss else 1; ss=s
    if stk>=5 and md!=s: md=s
    reg[d]=md
wrrank={}
for i,d in enumerate(days):
    c0=cr[d]; p1={t:r for t,r in (cr[days[i-1]] if i>=1 else {}).items() if r<=20}; p2={t:r for t,r in (cr[days[i-2]] if i>=2 else {}).items() if r<=20}
    wr={t:c0[t]*0.4+p1.get(t,50)*0.35+p2.get(t,50)*0.25 for t in c0}
    wrrank[d]={t:k+1 for k,t in enumerate(sorted(wr,key=lambda x:wr[x]))}
hold={}; eps=[]
for i,d in enumerate(days):
    if not reg[d]:
        for tk in list(hold): eps.append((tk,hold[tk][0],d,'방어청산',hold[tk][1])); hold.pop(tk)
        continue
    wr=wrrank[d]
    for tk in list(hold):
        if wr.get(tk,999)>6: eps.append((tk,hold[tk][0],d,'6위이탈',hold[tk][1])); hold.pop(tk)
    for tk,rk in wr.items():
        if rk<=3 and tk not in hold: hold[tk]=(d,rk)
for tk in hold: eps.append((tk,hold[tk][0],days[-1],'보유중',hold[tk][1]))
# DataFrame
rows=[]
for tk,d0,d1,why,erank in eps:
    r=ret(tk,d0,d1); dur=days.index(d1)-days.index(d0)
    if r is not None: rows.append(dict(tk=tk,name=nm.get(tk,tk),d0=d0,d1=d1,dur=dur,ret=r,why=why,erank=erank,yr=d0[:4]))
df=pd.DataFrame(rows)
print(f"[현재전략 _sp0b_co {days[0]}~{days[-1]}] 총 {len(df)} episode (수익=진입→이탈 종가, 비용前)\n")
print("="*64)
print("① 보유기간 버킷별 수익률")
print(f"{'버킷':<12}{'건수':>5}{'평균':>9}{'중앙':>9}{'승률':>7}{'최악':>8}{'최고':>9}")
bins=[(0,2,'1-2일'),(3,5,'3-5일'),(6,10,'6-10일'),(11,20,'11-20일'),(21,40,'21-40일'),(41,60,'41-60일'),(61,9999,'60일+')]
for lo,hi,l in bins:
    s=df[(df.dur>=lo)&(df.dur<=hi)]
    if len(s): print(f"{l:<12}{len(s):>5}{s.ret.mean()*100:>+8.1f}%{s.ret.median()*100:>+8.1f}%{(s.ret>0).mean()*100:>6.0f}%{s.ret.min()*100:>+7.0f}%{s.ret.max()*100:>+8.0f}%")
print("\n"+"="*64)
print("② 승률·손익비·기대값")
w=df[df.ret>0]; l=df[df.ret<0]
print(f"  승률 {(df.ret>0).mean()*100:.0f}%  |  평균이익 {w.ret.mean()*100:+.1f}% (n={len(w)})  평균손실 {l.ret.mean()*100:+.1f}% (n={len(l)})")
print(f"  손익비(평균이익/평균손실) {abs(w.ret.mean()/l.ret.mean()):.2f}  |  기대값/거래 {df.ret.mean()*100:+.2f}%")
print(f"  Profit Factor(총이익/총손실) {w.ret.sum()/abs(l.ret.sum()):.2f}")
print("\n"+"="*64)
print("③ 수익 집중도 (소수 승자가 다 버나?)")
tot=df.ret.sum(); srt=df.ret.sort_values(ascending=False)
for pct in [0.05,0.1,0.2]:
    n=max(1,int(len(df)*pct)); print(f"  상위 {int(pct*100)}% 거래({n}건)가 전체 수익합의 {srt.head(n).sum()/tot*100:.0f}%")
print(f"  (전체 수익합 {tot*100:.0f}%p, 거래당 평균 {df.ret.mean()*100:+.2f}%)")
print("\n"+"="*64)
print("④ 연도별")
for yr,g in df.groupby('yr'):
    print(f"  {yr}: {len(g):>3}건  평균 {g.ret.mean()*100:>+6.1f}%  승률 {(g.ret>0).mean()*100:>3.0f}%")
print("\n"+"="*64)
print("⑤ 진입순위(1/2/3위)별")
for er in [1,2,3]:
    s=df[df.erank==er]
    if len(s): print(f"  {er}위 진입: {len(s):>3}건  평균 {s.ret.mean()*100:>+6.1f}%  승률 {(s.ret>0).mean()*100:>3.0f}%  중앙 {s.ret.median()*100:+.1f}%")
print("\n"+"="*64)
print("⑥ 이탈사유별")
for why,g in df.groupby('why'):
    print(f"  {why}: {len(g):>3}건  평균 {g.ret.mean()*100:>+6.1f}%  승률 {(g.ret>0).mean()*100:>3.0f}%  중앙보유 {g.dur.median():.0f}일")
print("\n"+"="*64)
print("⑦ 베스트 8 / 워스트 5")
for _,r in df.nlargest(8,'ret').iterrows(): print(f"  + {r['name']:<10} {r.d0}~{r.d1} {r.dur}일 {r.ret*100:+.0f}%")
print("  ---")
for _,r in df.nsmallest(5,'ret').iterrows(): print(f"  - {r['name']:<10} {r.d0}~{r.d1} {r.dur}일 {r.ret*100:+.0f}%")
