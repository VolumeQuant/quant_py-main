# -*- coding: utf-8 -*-
"""개선포인트① 슬롯비중 — 동일가중(33/33/33) vs rank가중(40/40/20 등). 커스텀 일별 시뮬.
entry rank<=3, exit rank>6, 3슬롯, defense=cash. adj 가격, recent_ca는 rank에 이미 반영(state)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values;pdate={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
files=sorted(f for f in glob.glob(P+'/state/ranking_*.json') if os.path.basename(f)[8:16]>='20190102')
dates=[os.path.basename(f)[8:16] for f in files]
rankmap={}
for f,d in zip(files,dates):
    rankmap[d]={x['ticker']:x.get('rank',99) for x in json.load(open(f,encoding='utf-8'))['rankings']}
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
def close(tk,d):
    if tk not in pcol or d not in pdate: return None
    v=parr[pdate[d],pcol[tk]]; return v if v>0 else None
def sim(weights, sub):
    # weights: list 길이3, held를 rank순 정렬해 배분 (적으면 renormalize)
    held={}  # tk->entry, prevclose
    daily=[]
    prev=None
    for d in sub:
        # 1) 오늘 수익 (어제 close→오늘 close), 어제 정한 비중
        ret=0.0
        if held and prev:
            order=sorted(held.keys(), key=lambda tk: held[tk]['rk'])
            ws=weights[:len(order)]; sw=sum(ws); ws=[w/sw for w in ws]
            for tk,w in zip(order,ws):
                pc=close(tk,prev); nc=close(tk,d)
                if pc and nc: ret+=w*(nc/pc-1)
        daily.append(ret)
        # 2) 리밸런스 (오늘 close, 오늘 rank)
        rk=rankmap.get(d,{})
        if not reg.get(d,True):
            held={}
        else:
            # 이탈 rank>6
            held={tk:v for tk,v in held.items() if rk.get(tk,99)<=6}
            # 진입 rank<=3, 3슬롯
            cand=sorted([tk for tk in rk if rk[tk]<=3], key=lambda t:rk[t])
            for tk in cand:
                if len(held)>=3: break
                if tk not in held and close(tk,d): held[tk]={'rk':rk[tk]}
            # rk 갱신
            for tk in held: held[tk]['rk']=rk.get(tk,99)
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]
def show(nm,w):
    o=[sim(w,[d for d in dates if lo<=d<=hi]) for _,lo,hi in segs]
    print(f"  {nm:14s} 전체 {o[0][0]:>5.2f}  19-21 {o[1][0]:>5.2f}  약세 {o[2][0]:>5.2f}  24-26 {o[3][0]:>6.2f}  MDD {o[0][2]:>6.1f}%  CAGR {o[0][1]:.0f}%")
print(f"[개선포인트① 슬롯비중] {dates[0]}~{dates[-1]} (커스텀 일별 시뮬)\n")
print(f"  {'config':14s} {'Cal전체':>7s}  {'19-21':>7s}  {'약세':>6s}  {'24-26':>7s}  {'MDD':>8s}")
show('동일 33/33/33',[1/3,1/3,1/3])
show('40/40/20',[0.4,0.4,0.2])
show('40/35/25',[0.4,0.35,0.25])
show('50/30/20',[0.5,0.3,0.2])
show('45/35/20',[0.45,0.35,0.20])
