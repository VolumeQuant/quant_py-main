# -*- coding: utf-8 -*-
"""종목선택에 밸류(trailing PER, 전종목) 반영 방향탐색 — production top후보 중 PER 재정렬 효과.
과열캡 강화 = 비싼 종목 더 빼기가 forward수익 올리나? look-ahead 아님(trailing PER은 PIT)."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh={t:mc.loc[t,'상장주식수'] for t in mc.index}
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi:
        ar[dt]=sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99));dts.append(dt)
dts=sorted(dts)
def reg_s():
    reg={};md=True;stk=0;ss=None
    for d in dts:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_s()
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
def px(t,d):
    if t not in pcol or d not in tdi: return None
    v=parr[tdi[d],pcol[t]]; return float(v) if v>0 else None
# trailing PER (전종목, PIT) 월별 캐시
permap={};curm=None;cp={}
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];cp={}
        for t in cache:
            p0=px(t,d); e0=ttm(t,d)
            if p0 and t in sh and sh[t]>0 and e0 and e0>0: cp[t]=(p0*sh[t])/(e0*1e8)
    permap[d]=cp
def sim(per_pen_w, pool):
    """production top<pool> 후보 중, rank점수에 trailing PER 페널티 추가 → top3 재선택."""
    held=[];daily=[];prev=None
    for d in dts:
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[]
        else:
            cand=ar[d][:pool]; pm=permap.get(d,{})
            # 후보 PER z (비싼 양수). 점수 = -rank - W×per_z (rank낮을수록·PER쌀수록 우선)
            pers=[pm.get(c['ticker']) for c in cand]; valid=[p for p in pers if p and p<300]
            if valid and per_pen_w>0:
                mu=np.mean([np.log(p) for p in valid]); sd=np.std([np.log(p) for p in valid]) or 1
                def sc(c,i):
                    p=pm.get(c['ticker']); z=(np.log(p)-mu)/sd if (p and p<300) else 0
                    return -(i) - per_pen_w*z  # i=순위(작을수록↑), per비싸면 감점
                order=sorted(enumerate(cand),key=lambda x:-sc(x[1],x[0]))
                held=[c['ticker'] for _,c in order[:3]]
            else:
                held=[c['ticker'] for c in cand[:3]]
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
print("[종목선택에 trailing PER 반영 방향탐색 — 보유 z재배열 근사, PIT]\n")
print("※ production top<pool> 후보에서 PER 비싼 종목 감점 → top3 재선택. W=페널티 강도.\n")
for pool in [6,10]:
    print(f"  ── 후보 pool=top{pool} ──")
    print(f"  {'PER페널티 W':<14}{'CAGR':>7}{'MDD':>8}{'Calmar':>8}")
    for w in [0.0,0.3,0.5,1.0,2.0]:
        c,m,cal=sim(w,pool); tag='현행(반영X)' if w==0 else f'W={w}'
        print(f"  {tag:<14}{c:>6.0f}%{m:>7.1f}%{cal:>8.2f}")
    print()
print("→ W>0이 현행 넘으면 종목선택에 PER 반영 가치(컨센불필요·전종목). 풀재생성으로 확정필요")
