# -*- coding: utf-8 -*-
"""sleeve confirm 자격을 forward PER<20으로 재정의 (기대성장 비율 상위100 폐기).
비중 = forward PER 낮을수록↑. vs 현행(grow비율 상위100). 강세·최근 쪼개서. look-ahead 상한."""
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
growrank={};fwm={};curm=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];fg=[];cf={}
        for t in cache:
            p0=px(t,d); e0=ttm(t,d); e1=ttm(t,d1)
            if p0 and t in sh and sh[t]>0:
                if e1 and e1>0: cf[t]=(p0*sh[t])/(e1*1e8)
                if e0 and e0>0 and e1 is not None: fg.append((t,e1/e0))
        fg.sort(key=lambda z:-z[1]);cur_gr={t:r+1 for r,(t,_) in enumerate(fg)};cur_gv={t:g for t,g in fg};cur_f=cf
    growrank[d]=(cur_gr,cur_gv);fwm[d]=cur_f
CAP=5.0
def sim(mode, thr=20):
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
                f=fp.get(t);g=gv.get(t);rk=gr.get(t,99999)
                if mode=='grow100':   # 현행: 기대성장 비율 상위100 confirm, grow비례
                    isc=(rk<=100) and (g is not None)
                    w=min(1.0+2.0*max((g or 1.0)-1.0,0.0),CAP) if isc else 1.0
                elif mode=='fwd_confirm':  # ★신: forward PER<thr confirm, PER 낮을수록 비중
                    isc=(f is not None and f<thr)
                    w=min(max(thr/f,1.0),CAP) if isc else 1.0   # fp 낮을수록↑ (thr/fp)
                elif mode=='fwd_x_grow':   # forward PER<thr confirm AND grow비례 (둘다)
                    isc=(f is not None and f<thr and g is not None)
                    w=min(1.0+2.0*max((g or 1.0)-1.0,0.0),CAP) if isc else 1.0
                pw[t]=w
        prev=d
    return out
def cal(out,sub=None):
    a=np.array([r for d,r in out if (not sub or sub[0]<=d<=sub[1])])
    if len(a)<20: return 0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
P1=('20190102','20211231');P3=('20240101','20261231')
print("[sleeve confirm 자격 재정의 — 강세19-21 / 최근24-26]\n")
print(f"  {'방식':<30}{'전체':>8}{'강세':>9}{'최근':>9}")
o=sim('grow100');print(f"  {'현행:기대성장비율 상위100':<30}{cal(o):>8.2f}{cal(o,P1):>9.2f}{cal(o,P3):>9.2f}")
for thr in [15,20,25]:
    o=sim('fwd_confirm',thr);print(f"  {'★fwPER<'+str(thr)+' confirm,PER낮을수록비중':<30}{cal(o):>8.2f}{cal(o,P1):>9.2f}{cal(o,P3):>9.2f}")
for thr in [20,25]:
    o=sim('fwd_x_grow',thr);print(f"  {'fwPER<'+str(thr)+'&grow비례(둘다)':<30}{cal(o):>8.2f}{cal(o,P1):>9.2f}{cal(o,P3):>9.2f}")
print("\n→ forward PER confirm이 강세·최근 둘 다 현행 넘으면 = 자격을 PER로 정하는 게 맞음")

# === 자격 임계 스윕 (forward PER<thr 게이트 + grow비례) ===
print("\n[자격 임계 스윕 — forward PER<thr 게이트 + 기대성장 비례, 강세/최근]\n")
print(f"  {'자격 thr':<14}{'전체':>8}{'강세19-21':>11}{'최근24-26':>11}{'min(강,최)':>11}")
best=None
for thr in [10,15,20,25,30,35,40,999]:
    o=sim('fwd_x_grow',thr)
    ce,c1,c3=cal(o),cal(o,P1),cal(o,P3)
    lbl=f'fwPER<{thr}' if thr<999 else '게이트없음'
    mn=min(c1,c3)
    print(f"  {lbl:<14}{ce:>8.2f}{c1:>11.2f}{c3:>11.2f}{mn:>11.2f}")
    if best is None or mn>best[0]: best=(mn,thr,ce,c1,c3)
print(f"\n★ 강세·최근 동시 최선(min 최대): fwPER<{best[1]} (전체{best[2]:.2f} 강세{best[3]:.2f} 최근{best[4]:.2f})")
print("→ min(강세,최근) 최대인 thr = 두 기간 다 안전한 자격 컷. 직감 아닌 데이터")
