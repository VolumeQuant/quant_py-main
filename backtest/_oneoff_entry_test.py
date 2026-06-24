# -*- coding: utf-8 -*-
"""결판 테스트: 7.4년 rank<=3 진입 전부 → 진입시점 lumpiness 지표 vs 실제 fwd20/60 수익률.
일회성 진입이 정말 더 망하나? 망하면 필터 가치 有, 아니면 못 거름 확정."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_202606*.parquet')))[-1]).replace(0,np.nan).apply(ba)
pidx = {d.strftime('%Y%m%d'): i for i,d in enumerate(prices.index)}
parr = prices.values; pcols = {c:i for i,c in enumerate(prices.columns)}
# 진입 이벤트 수집 (rank<=3)
events=[]  # (date, ticker)
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if not(dt.isdigit() and len(dt)==8 and dt>='20190102'): continue
    for r in json.load(open(f,encoding='utf-8'))['rankings']:
        if r.get('rank',99)<=3: events.append((dt, r['ticker']))
print(f"진입 이벤트(rank<=3) {len(events)}건", flush=True)
# 분기 재무 캐시 (매출/영업이익) for 진입 티커
tks=sorted(set(t for _,t in events))
qrev={}; qop={}
for tk in tks:
    p=os.path.join(PROJ,'data_cache',f'fs_dart_{tk}.parquet')
    if not os.path.exists(p): continue
    d=pd.read_parquet(p).rename(columns={'공시구분':'g','rcept_dt':'rc'})
    d['rc']=pd.to_datetime(d['rc'],errors='coerce')
    for acct,store in [('매출액',qrev),('영업이익',qop)]:
        q=d[(d['g']=='q')&(d['계정']==acct)].dropna(subset=['rc']).sort_values('rc')
        if len(q)>=8: store[tk]=(q['rc'].values, q['값'].astype(float).values)
def fwd_ret(tk, dt, h):
    if tk not in pcols or dt not in pidx: return np.nan
    i=pidx[dt]; ci=pcols[tk]
    if i+h>=len(parr): return np.nan
    p0=parr[i,ci]; p1=parr[i+h,ci]
    if not(p0>0 and p1>0): return np.nan
    return p1/p0-1
def metr(tk, dt):
    base=np.datetime64(pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:]))
    out={}
    s=qrev.get(tk)
    if s is not None:
        v=s[1][s[0]<=base]
        if len(v)>=8 and (v[-8:]>0).all():
            v8=v[-8:]; v4=v[-4:]
            out['minmax']=v4.min()/v4.max()
            out['cv']=v8.std()/v8.mean()
            out['spike']=v8[-1]/np.median(v8)
    o=qop.get(tk)
    if o is not None:
        ov=o[1][o[0]<=base]
        if len(ov)>=8:
            o8=ov[-8:]; o4=ov[-4:]
            out['op_loss_q']=int((o8<0).sum())  # 적자분기 수
            ttm=o4.sum()
            out['opC']=(o4.max()/ttm) if ttm>0 else np.nan  # 한분기 쏠림
    return out
rows=[]
for dt,tk in events:
    m=metr(tk,dt)
    if not m: continue
    rows.append({'dt':dt,'tk':tk,'f20':fwd_ret(tk,dt,20),'f60':fwd_ret(tk,dt,60),**m})
df=pd.DataFrame(rows)
print(f"재무지표 산출 가능 진입 {len(df)}건 (전체평균 fwd20={df['f20'].mean()*100:+.2f}% fwd60={df['f60'].mean()*100:+.2f}%)\n", flush=True)
def split(col, thr, low_is_bad=True):
    a=df.dropna(subset=[col,'f20','f60'])
    if low_is_bad: flagged=a[a[col]<thr]; clean=a[a[col]>=thr]
    else: flagged=a[a[col]>thr]; clean=a[a[col]<=thr]
    def stat(x): return (len(x), x['f20'].mean()*100, x['f60'].mean()*100, (x['f20']>0).mean()*100)
    fn,ff20,ff60,fwr=stat(flagged); cn,cf20,cf60,cwr=stat(clean)
    print(f"  {col}{'<' if low_is_bad else '>'}{thr}: 함정후보 n={fn:>4} fwd20={ff20:+.2f}% fwd60={ff60:+.2f}% 승률{fwr:.0f}%  |  나머지 n={cn:>4} fwd20={cf20:+.2f}% fwd60={cf60:+.2f}% 승률{cwr:.0f}%  Δfwd60={ff60-cf60:+.2f}%p")
print("[일회성 의심 진입 vs 나머지 — fwd 수익률 비교]")
split('minmax',0.35,True)
split('minmax',0.25,True)
split('cv',0.6,False)
split('spike',1.6,False)
split('op_loss_q',0,False)   # 적자분기 1개 이상
split('opC',0.7,False)       # 영업이익 한분기 쏠림
# 상관 (IC)
print("\n[Spearman IC: 지표 vs fwd60]")
for c in ['minmax','cv','spike','op_loss_q','opC']:
    a=df.dropna(subset=[c,'f60'])
    if len(a)>30:
        ic=a[c].corr(a['f60'],method='spearman')
        print(f"  {c}: IC={ic:+.3f} (n={len(a)})")
