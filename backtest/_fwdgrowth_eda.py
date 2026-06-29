# -*- coding: utf-8 -*-
"""네 가설 검증 — 선행이익성장(PER/fwdPER-1 ≈ 실현 12m EPS성장)이 수익 예측하나.
+ 후행성장이 못잡는 '인플렉션'(저후행+고선행)이 진짜 알파인가. look-ahead=전제검증(배포불가)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
files=sorted(f for f in glob.glob(P+'/state/ranking_*.json') if os.path.basename(f)[8:16]>='20190102')
dates=[os.path.basename(f)[8:16] for f in files]
def reg_s(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_s(dates)
# 샘플: boost일 rank<=15, 5일마다 (속도)
rows=[]
for i,(f,d) in enumerate(zip(files,dates)):
    if i%5!=0 or not reg.get(d,True): continue
    r=json.load(open(f,encoding='utf-8'))['rankings']
    for x in r:
        if x.get('rank',99)<=15: rows.append((d,x['ticker'],x.get('growth_s') or 0))
print(f"샘플 {len(rows)}건 (boost rank<=15, 5일간격)")
# fs EPS 시리즈 캐시 (지배주주당기순이익 분기, rcept)
tks=set(t for _,t,_ in rows); epscache={}
for t in tks:
    p=P+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(p): continue
    fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    q=fs[(fs['공시구분']=='q')&(fs['계정']=='지배주주당기순이익')&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
    if len(q)>=8: epscache[t]=(q['rcept_dt'].values,q['값'].astype(float).values)
def ttm(t,ts):  # rcept<=ts 최근4분기 합
    s=epscache.get(t)
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(ts)]
    return v[-4:].sum() if len(v)>=4 else None
def fwd(t,d,h):
    if t not in pcol or d not in pdi: return None
    i=pdi[d];ci=pcol[t]
    if i+h>=len(parr): return None
    p0,p1=parr[i,ci],parr[i+h,ci]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
def fdate(d,h):  # d+h거래일의 날짜
    if d not in pdi: return None
    i=pdi[d]
    if i+h>=len(parr): return None
    return px.index[i+h].strftime('%Y%m%d')
out=[]
for d,t,g in rows:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    e0=ttm(t,ts)
    d1=fdate(d,250)
    if d1 is None or e0 is None or e0<=0: continue
    ts1=pd.Timestamp(d1[:4]+'-'+d1[4:6]+'-'+d1[6:])
    e1=ttm(t,ts1)
    if e1 is None: continue
    fg=(e1/e0-1)*100  # 실현 선행 12m 이익성장
    out.append({'d':d,'t':t,'g':g,'fwd_eg':fg,'r250':fwd(t,d,250),'r120':fwd(t,d,120)})
o=pd.DataFrame(out).dropna(subset=['r250'])
print(f"유효 {len(o)}건 (선행이익성장 산출+미래수익 가용)\n")
print("=== 선행 12m 이익성장 분위별 미래 주가수익 (네 가설 직접검증) ===")
o['eq']=pd.qcut(o['fwd_eg'].clip(-200,500),5,labels=['Q1최저','Q2','Q3','Q4','Q5최고'],duplicates='drop')
for q,gg in o.groupby('eq',observed=True):
    print(f"  {q}: n={len(gg):>4} 선행이익성장 중앙{gg['fwd_eg'].median():>+6.0f}% → 미래250일 {gg['r250'].mean():>+6.1f}% 승률{(gg['r250']>0).mean()*100:.0f}%")
# 후행성장 × 선행성장 2x2 (인플렉션 = 저후행+고선행)
gm=o['g'].median(); em=o['fwd_eg'].median()
print(f"\n=== 후행성장(growth_s) × 선행이익성장 2x2 (인플렉션 탐색) ===")
def c(nm,m):
    gg=o[m]; print(f"  {nm:26s} n={len(gg):>4} 미래250일 {gg['r250'].mean():>+6.1f}% 승률{(gg['r250']>0).mean()*100:.0f}%")
c('고후행+고선행',(o['g']>=gm)&(o['fwd_eg']>=em))
c('고후행+저선행',(o['g']>=gm)&(o['fwd_eg']<em))
c('저후행+고선행 (인플렉션)',(o['g']<gm)&(o['fwd_eg']>=em))
c('저후행+저선행',(o['g']<gm)&(o['fwd_eg']<em))
