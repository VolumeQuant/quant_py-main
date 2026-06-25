# -*- coding: utf-8 -*-
"""sleeve(기대성장 비율) 좋아도 fwd_per 절대값<20이어야 잘 오르나? (사용자 감 검증)
fwd_per_proxy = 시총 / 미래TTM순이익 (look-ahead, 컨센 히스토리 없어 실적 proxy). 보유 top3 + 기대성장 상위 진입의 forward 수익률을 fwd_per 버킷별로."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
# 시총 = 가격 × 주식수. 주식수는 최신 market_cap로 근사(상장주식수 변동 작다 가정)
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh={t:mc.loc[t,'상장주식수'] for t in mc.index if t in mc.index}
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi:
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dts.append(dt)
dts=sorted(dts)
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
def px(t,d):
    if t not in pcol or d not in tdi: return None
    v=parr[tdi[d],pcol[t]]; return float(v) if v>0 else None
def fwd_ret(t,d,h):
    i=tdi[d]; d2=tdays[min(i+h,len(tdays)-1)]; p0=px(t,d); p1=px(t,d2)
    return (p1/p0-1)*100 if p0 and p1 else None
# 매월 1회: 기대성장 상위100 종목 수집 → 그 종목들의 fwd_per & forward수익률
rows=[]
curm=None; samp=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6]; i=tdi[d]; d1=tdays[min(i+250,len(tdays)-1)]; fg=[]
        for t in cache:
            p0=px(t,d)
            if p0 is None or t not in sh or not(sh[t]>0): continue
            e0=ttm(t,d); e1=ttm(t,d1)  # e1=현재시점 forward TTM순이익(억). 미래실적 proxy
            if e0 and e0>0 and e1 is not None and e1>0:
                grow=e1/e0
                fwdper=(p0*sh[t])/(e1*1e8)   # 시총/forwardTTM순이익
                fg.append((t,grow,fwdper))
        fg.sort(key=lambda z:-z[1]); samp=fg[:100]  # 기대성장 상위100
    # 이 달 상위100 종목의 forward 수익률 기록 (fwd_per 버킷)
    if samp and d==dts[[x[:6] for x in dts].index(curm)]:  # 달 첫날만 1회
        for t,grow,fwdper in samp:
            r20=fwd_ret(t,d,20); r60=fwd_ret(t,d,60)
            if r20 is not None and 0<fwdper<200:
                rows.append({'fwdper':fwdper,'grow':grow,'r20':r20,'r60':r60})
df=pd.DataFrame(rows)
print(f"[기대성장 상위100 종목의 fwd_per별 forward수익률 — look-ahead proxy, n={len(df)}]\n")
print("※ 전부 sleeve 우수(기대성장 상위100)인 종목들. 그 안에서 fwd_per 절대값만 다름.\n")
bins=[(0,10),(10,15),(15,20),(20,30),(30,50),(50,200)]
print(f"  {'fwd_per 구간':<14}{'n':>5}{'평균기대성장':>11}{'fwd20일':>9}{'fwd60일':>9}{'승률20':>8}")
for lo,hi in bins:
    s=df[(df['fwdper']>=lo)&(df['fwdper']<hi)]
    if len(s)>0:
        wr=(s['r20']>0).mean()*100
        print(f"  {f'{lo}~{hi}':<14}{len(s):>5}{s['grow'].mean():>10.2f}x{s['r20'].mean():>8.1f}%{s['r60'].mean():>8.1f}%{wr:>7.0f}%")
print(f"\n=== fwd_per<20 vs >=20 (sleeve 우수 종목 한정) ===")
lo20=df[df['fwdper']<20]; hi20=df[df['fwdper']>=20]
print(f"  fwd_per<20 : n={len(lo20):4d}  fwd20 {lo20['r20'].mean():+.1f}%  fwd60 {lo20['r60'].mean():+.1f}%  승률 {(lo20['r20']>0).mean()*100:.0f}%")
print(f"  fwd_per>=20: n={len(hi20):4d}  fwd20 {hi20['r20'].mean():+.1f}%  fwd60 {hi20['r60'].mean():+.1f}%  승률 {(hi20['r20']>0).mean()*100:.0f}%")
print(f"\n→ <20이 확실히 높으면 형 감 맞음(밸류 필터 추가 가치). 비슷하면 비율만으로 충분")
