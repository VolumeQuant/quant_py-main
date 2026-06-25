# -*- coding: utf-8 -*-
"""sleeve 컷오프(상위N) 기간별 검증 — 없음/30/50/100/200. 강세·최근 각각. + forward PER 비중 결합.
sleeve = 보유 top3 비중조절. look-ahead 상한이나 상대비교·기간robust 확인."""
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
# 월별: 기대성장 랭킹 + forward PER
growrank={};fwm={};curm=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];fg=[];cf={}
        for t in cache:
            p0=px(t,d); e0=ttm(t,d); e1=ttm(t,d1)
            if p0 and t in sh and sh[t]>0:
                if e1 and e1>0: cf[t]=(p0*sh[t])/(e1*1e8)
                if e0 and e0>0 and e1 is not None: fg.append((t,e1/e0))
        fg.sort(key=lambda z:-z[1]); gr={t:r+1 for r,(t,_) in enumerate(fg)}; gv={t:g for t,g in fg}
        cur_gr=gr;cur_gv=gv;cur_f=cf
    growrank[d]=(cur_gr,cur_gv);fwm[d]=cur_f
K,CAP=2.0,5.0
def fpmult(fp):
    if fp is None: return 1.0
    if fp<15: return 1.2
    if fp<20: return 1.0
    if fp<25: return 0.6
    return 0.3
def sim(cutN, use_fp):
    held=[];out=[];prev=None;pw={}
    for d in dts:
        ret=0.0
        if held and prev:
            num=0;den=0
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    w=pw.get(t,1.0);num+=w*(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1);den+=w
            ret=num/den if den>0 else 0.0
        out.append((d,ret))
        if not reg.get(d,True): held=[];pw={}
        else:
            held=[x['ticker'] for x in ar[d][:3]]
            gr,gv=growrank.get(d,({},{}));fp=fwm.get(d,{});pw={}
            for t in held:
                g=gv.get(t);rk=gr.get(t,99999)
                isc=(cutN is None) or (rk<=cutN)  # cutN=None=컷없음(컨센 있으면 다)
                if g is None or not (t in gv): isc=False  # 컨센/기대성장 없으면 미확인
                if isc:
                    base=min(1.0+K*max((g or 1.0)-1.0,0.0),CAP)
                    w=min(1.0+(base-1.0)*(fpmult(fp.get(t)) if use_fp else 1.0),CAP)
                else: w=1.0
                pw[t]=w
        prev=d
    return out
def cal(out,sub=None):
    a=np.array([r for d,r in out if (not sub or sub[0]<=d<=sub[1])])
    if len(a)<20: return 0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
P1=('20190102','20211231');P3=('20240101','20261231')
print("[sleeve 컷오프 기간별 — 강세19-21 / 최근24-26 (약세 제외=defense), grow비례만]\n")
print(f"  {'컷오프':<14}{'전체':>8}{'강세19-21':>11}{'최근24-26':>11}")
for cutN in [30,50,100,200,None]:
    o=sim(cutN,False);lbl=f'상위{cutN}' if cutN else '컷없음'
    print(f"  {lbl:<14}{cal(o):>8.2f}{cal(o,P1):>11.2f}{cal(o,P3):>11.2f}")
print("\n[+ forward PER 비중결합 (위 최적 컷 기준)]")
print(f"  {'컷오프+fwPER':<14}{'전체':>8}{'강세19-21':>11}{'최근24-26':>11}")
for cutN in [100,200,None]:
    o=sim(cutN,True);lbl=f'상위{cutN}+fp' if cutN else '컷없음+fp'
    print(f"  {lbl:<14}{cal(o):>8.2f}{cal(o,P1):>11.2f}{cal(o,P3):>11.2f}")
print("\n→ 강세·최근 둘 다 높은 컷 = robust 채택. 한쪽만이면 기각")
