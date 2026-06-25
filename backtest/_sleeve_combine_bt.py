# -*- coding: utf-8 -*-
"""결합 sleeve BT — 기대성장 비율 + fwd_per(낮을수록) 결합 가중. 현행(비율만) 대비. look-ahead 상한."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from scipy.stats import spearmanr
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
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dts.append(dt)
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
# 월별: 기대성장 + fwd_per (보유종목용 lookup)
gm={};fm={};cutm={};curm=None;cg={};cf={};cc=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];fg=[]
        cg={};cf={}
        for t in cache:
            p0=px(t,d)
            if p0 is None or t not in sh or not(sh[t]>0): continue
            e0=ttm(t,d);e1=ttm(t,d1)
            if e0 and e0>0 and e1 is not None and e1>0:
                cg[t]=e1/e0; cf[t]=(p0*sh[t])/(e1*1e8); fg.append((t,e1/e0))
        fg.sort(key=lambda z:-z[1]); cc=fg[99][1] if len(fg)>=100 else (fg[-1][1] if fg else 0)
    gm[d]=cg;fm[d]=cf;cutm[d]=cc
K,CAP=2.0,5.0
def fwdper_mult(fp,mode):
    """fwd_per 가중 multiplier (낮을수록↑, >25 꺾임)."""
    if fp is None: return 1.0
    if mode=='none': return 1.0
    if mode=='step':   # <20 유지, 20~25 감, >25 강감
        return 1.0 if fp<20 else (0.6 if fp<25 else 0.3)
    if mode=='smooth': # 연속: fp 10→1.2, 20→1.0, 30→0.5
        return float(np.clip(1.4-0.03*fp,0.25,1.4))
    if mode=='gate20': # <20만 sleeve, >=20 비중 1배
        return 1.0 if fp<20 else 0.0  # 0=확신가중 무효(grow가중 안받음)
def sim(mode):
    held=[];daily=[];prev=None;pw={}
    for d in dts:
        ret=0.0
        if held and prev:
            num=0;den=0
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    w=pw.get(t,1.0); num+=w*(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1); den+=w
            ret=num/den if den>0 else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[];pw={}
        else:
            held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3]]
            g=gm.get(d,{});fp=fm.get(d,{});cut=cutm.get(d,0);pw={}
            for t in held:
                gv=g.get(t)
                if gv is None: pw[t]=1.0; continue
                base=min(1.0+K*max(gv,0),CAP) if gv>=cut else 1.0  # 현행 grow게이트비례
                if mode=='none': pw[t]=base
                else:
                    fpv=fp.get(t); mult=fwdper_mult(fpv,mode)
                    if mode=='gate20':  # fwd_per<20만 grow비례, 아니면 1배
                        pw[t]=base if (fpv is not None and fpv<20) else 1.0
                    else:
                        pw[t]=1.0+(base-1.0)*mult  # grow 초과분에 fwd_per 가중
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
# IC 재계산 (nan 제거)
g=pd.read_pickle(P+'/backtest/_sleeve_eda_df.pkl').dropna(subset=['r60'])
print(f"[IC 재계산 (nan제거, n={len(g)})]")
gz=(g['grow']-g['grow'].mean())/g['grow'].std(); fz=(np.log(g['fwdper'])-np.log(g['fwdper']).mean())/np.log(g['fwdper']).std()
print(f"  기대성장 단독 IC={spearmanr(g['grow'],g['r60'])[0]:+.4f}")
print(f"  fwd_per(낮을수록) IC={spearmanr(-g['fwdper'],g['r60'])[0]:+.4f}")
for w in [0,0.5,1.0,1.5,2.0]:
    print(f"  결합 성장z-{w}×fwdper_z IC={spearmanr(gz-w*fz,g['r60'])[0]:+.4f}")
print(f"\n[결합 sleeve BT — 보유 top3 가중, look-ahead 상한]")
print(f"  {'방식':<30}{'CAGR':>7}{'MDD':>8}{'Calmar':>8}")
for nm,md in [('★현행: grow비례만(fwd_per무시)','none'),
              ('+ fwd_per step(<20유지/>25강감)','step'),
              ('+ fwd_per smooth(연속)','smooth'),
              ('+ fwd_per gate20(<20만 sleeve)','gate20')]:
    c,m,cal=sim(md); print(f"  {nm:<30}{c:>6.0f}%{m:>7.1f}%{cal:>8.2f}")
