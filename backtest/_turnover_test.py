import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
val=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_volume_*.parquet'))[-1])  # 거래대금(원)
vd=[d.strftime('%Y%m%d') for d in val.index];vdi={d:i for i,d in enumerate(vd)};vval=val.values;vcol={c:i for i,c in enumerate(val.columns)}
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh={t:mc.loc[t,'상장주식수'] for t in mc.index}
nm=json.load(open(P+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
def nameof(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in nm: return nm[k].get('shortName',t)
    return t
def metrics(t,d):  # (거래대금억, 거래량주, 회전율%) 20일평균
    if t not in vcol or t not in pcol or t not in sh or not sh[t]>0: return None
    dd=d if d in vdi else max([x for x in vd if x<=d],default=None)
    if not dd: return None
    i=vdi[dd];tv=vval[max(0,i-19):i+1,vcol[t]];tv=tv[tv>0]
    if len(tv)<5: return None
    td_won=np.nanmean(tv)  # 거래대금 원
    j=tdi.get(dd);p=parr[j,pcol[t]] if j else None
    if not p or p<=0: return None
    vol_sh=td_won/p           # 거래량 주
    turn=vol_sh/sh[t]*100     # 회전율 %
    return td_won/1e8, vol_sh, turn
print("[패자 vs 승자 — 거래대금/거래량/회전율 (최근 20일평균)]\n")
print(f"  {'종목':12s}{'거래대금':>9s}{'거래량(만주)':>11s}{'회전율%':>8s}")
print("  --- 사용자가 막으려는 패자 ---")
for t in ['037460','187870','058610','265740']:  # 삼지,디바이스,아이티센?,265740
    m=metrics(t,'20260622')
    if m: print(f"  {nameof(t)[:12]:12s}{m[0]:>8.0f}억{m[1]/1e4:>10.0f}{m[2]:>7.2f}%")
print("  --- 막으면 안되는 승자 ---")
for t in ['089970','080220','031330','065650','069080']:  # 브이엠,제주,에스에이엠티,?,웹젠?
    m=metrics(t,'20260622')
    if m: print(f"  {nameof(t)[:12]:12s}{m[0]:>8.0f}억{m[1]/1e4:>10.0f}{m[2]:>7.2f}%")
# 코호트: 신규 top3 진입 회전율·거래량별 forward
rows=[];prev=set()
def fwd(t,d,h):
    if t not in pcol or d not in tdi: return None
    i=tdi[d];d2=tdays[min(i+h,len(tdays)-1)];p0=parr[i,pcol[t]];p1=parr[tdi[d2],pcol[t]]
    return (p1/p0-1)*100 if p0>0 and p1>0 else None
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    d=os.path.basename(f)[8:16]
    if not(d.isdigit() and d>='20190102' and d in tdi): continue
    held=[x['ticker'] for x in sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99))[:3]]
    for t in held:
        if t in prev: continue
        m=metrics(t,d);r60=fwd(t,d,60)
        if m and r60 is not None: rows.append({'turn':m[2],'r60':r60})
    prev=set(held)
o=pd.DataFrame(rows)
print(f"\n[신규 top3 진입 {len(o)}건 — 회전율별 forward60]")
for lo,hi,nm2 in [(0,1,'<1%(저회전)'),(1,3,'1~3%'),(3,6,'3~6%'),(6,15,'6~15%'),(15,100,'>15%(과열)')]:
    s=o[(o['turn']>=lo)&(o['turn']<hi)]
    if len(s)>0: print(f"  {nm2:14s} n={len(s):4d}  fwd60 {s['r60'].mean():+.0f}%  승률 {(s['r60']>0).mean()*100:.0f}%  큰손실<-20% {(s['r60']<-20).mean()*100:.0f}%")
print(f"\n  회전율 IC(Spearman vs fwd60): {o['turn'].corr(o['r60'],method='spearman'):+.3f}")
