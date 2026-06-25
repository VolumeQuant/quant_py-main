# -*- coding: utf-8 -*-
"""이탈룰이 못 막은 실현 큰손실 — 급락(갭) vs 느린decay 구분 → 이탈룰 개선 레버."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pidx={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)};parr=prices.values;pcol={c:i for i,c in enumerate(prices.columns)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
files=sorted(f for f in glob.glob(P+'/state/ranking_*.json') if os.path.basename(f)[8:16]>='20190102')
dates=[os.path.basename(f)[8:16] for f in files]; dpos={d:i for i,d in enumerate(dates)}
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
def px(tk,d):
    if tk not in pcol or d not in pidx: return None
    return parr[pidx[d],pcol[tk]]
df=pd.read_parquet(P+'/backtest/_trap_entries.parquet')
out=[]
for tk,d0,nm in zip(df['tk'],df['d'],df['nm']):
    p0=px(tk,d0); s=dpos.get(d0)
    if not(p0 and p0>0) or s is None: continue
    path=[]; exit_ret=None; held=0; minp=p0
    for j in range(s+1,len(dates)):
        d=dates[j]; held=j-s
        p=px(tk,d)
        if p and p>0: minp=min(minp,p)
        rk=rankmap.get(d,{}).get(tk,99)
        if rk>6 or not reg.get(d,True):
            if p and p>0: exit_ret=(p/p0-1)*100
            break
    if exit_ret is None: continue
    firstday=(px(tk,dates[s+1])/p0-1)*100 if s+1<len(dates) and px(tk,dates[s+1]) else None
    maxdd=(minp/p0-1)*100
    out.append({'d':d0,'nm':nm,'realized':exit_ret,'held':held,'firstday':firstday,'maxdd_inhold':maxdd})
o=pd.DataFrame(out)
bad=o[o['realized']<-15].sort_values('realized')
print(f"실현손실 <-15% (이탈룰 못막음): {len(bad)}건 / 전체진입 {len(o)}건\n")
print("=== 급락(갭) vs 느린decay 분류 ===")
gap=bad[bad['firstday']<-8]  # 진입 다음날 -8%↓ = 급락/갭
print(f"  진입직후 급락(다음날<-8%): {len(gap)}건 (이탈 신호 전에 이미 무너짐=구조적 불가피)")
slow=bad[(bad['firstday']>=-8)&(bad['held']>=5)]
print(f"  느린decay(첫날 양호+5일↑보유): {len(slow)}건 (이탈룰이 늦게 발동=개선여지)")
print(f"\n  {'날짜':9s}{'종목':10s}{'실현':>7s}{'첫날':>7s}{'보유':>5s}{'보유中최저':>9s}")
for _,x in bad.head(15).iterrows():
    print(f"  {x['d']:9s}{x['nm'][:9]:10s}{x['realized']:>+6.0f}%{x['firstday']:>+6.0f}%{int(x['held']):>4}일{x['maxdd_inhold']:>+8.0f}%")
