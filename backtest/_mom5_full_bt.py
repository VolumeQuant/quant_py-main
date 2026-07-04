# -*- coding: utf-8 -*-
"""mom_5 full 근사 BT: production state top65 전체 + 주입 mom_5_z(전체유니버스 μ,σ) → score 재정렬 → top3.
오버레이(top10)보다 정확. w 스윕 + 기간별 WF + LOWO. 원본 state 불변(메모리 주입만)."""
import sys,io,os,glob,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
import numpy as np,pandas as pd
R='C:/dev/claude-code/quant_py-main'
ohlcv=pd.read_parquet(R+'/data_cache/all_ohlcv_20170601_20260629.parquet').replace(0,np.nan)
px=pd.read_parquet(R+'/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0,np.nan)  # 수익률용(수정주가)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(R+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
# mom_5_z 캐시 (날짜별 전체유니버스 z)
ohv=ohlcv.values; ohc={c:i for i,c in enumerate(ohlcv.columns)}; ohd=[d.strftime('%Y%m%d') for d in ohlcv.index]; ohdi={d:i for i,d in enumerate(ohd)}
def mom5_z(dt):
    i=ohdi.get(dt)
    if i is None: 
        # 가장 가까운 이전 거래일
        cand=[d for d in ohd if d<=dt]; 
        if not cand: return {}
        i=ohdi[cand[-1]]
    sub=ohv[:i+1]
    mask=np.array([np.isfinite(sub[r]).sum()>=sub.shape[1]*0.5 for r in range(max(0,i-8),i+1)])
    rows=list(range(max(0,i-8),i+1)); rows=[r for r,m in zip(rows,mask) if m]
    if len(rows)<6: return {}
    last=sub[rows[-1]]; prev=sub[rows[-6]]
    raw=last/prev-1; raw=np.where(np.isfinite(raw),raw,np.nan)
    m=np.nanmean(raw); s=np.nanstd(raw)
    if not s>0: return {}
    z=(raw-m)/s
    return {c:z[ohc[c]] for c in ohlcv.columns if np.isfinite(z[ohc[c]])}
# state 로드 (top65 전체 + score)
ar={};dts=[]
for f in sorted(glob.glob(R+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi:
        rk=json.load(open(f,encoding='utf-8'))['rankings']
        z5=mom5_z(dt)
        ar[dt]=[(x['ticker'],x.get('score',0),z5.get(x['ticker'],0.0)) for x in rk]; dts.append(dt)
dts=sorted(dts)
reg={};md=True;stk=0;ss=None
for d in dts:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
    s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
    if stk>=5 and md!=s: md=s
    reg[d]=md
def sim(w,exclude=None,sub=None):
    held=[];out=[];prev=None
    for d in dts:
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        out.append((d,ret))
        if not reg.get(d,True): held=[]
        else:
            cand=[(t,sc,z) for t,sc,z in ar[d] if t!=exclude]
            scored=[(t, sc+w*z) for t,sc,z in cand]
            held=[t for t,_ in sorted(scored,key=lambda z:-z[1])[:3]]
        prev=d
    a=np.array([r for dd,r in out if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
P1=('20190102','20211231');P2=('20220101','20231231');P3=('20240101','20261231')
print("[mom_5 full 근사 BT — top65 재정렬, 전체유니버스 z]")
bc,bm,bb=sim(0)
print(f"baseline(w=0): Calmar {bb:.2f} (CAGR {bc:.0f}% MDD {bm:.1f}%)\n")
print(f"  {'w':>6s}{'전체':>8s}{'강세':>8s}{'약세':>8s}{'최근':>8s}{'MDD':>8s}")
for w in [0.03,0.05,0.08,0.1,0.15,0.2]:
    c,m,cal=sim(w); _,_,c1=sim(w,sub=P1); _,_,c2=sim(w,sub=P2); _,_,c3=sim(w,sub=P3)
    print(f"  {w:>6.2f}{cal:>8.2f}{c1:>8.2f}{c2:>8.2f}{c3:>8.2f}{m:>8.1f}")
print(f"  (baseline 기간별: 강세 {sim(0,sub=P1)[2]:.2f} 약세 {sim(0,sub=P2)[2]:.2f} 최근 {sim(0,sub=P3)[2]:.2f})")

# === w 정밀 + LOWO ===
print("\n[w 정밀 (full근사)]")
for w in [0.01,0.02,0.03,0.04,0.05,0.06]:
    _,m,cal=sim(w); print(f"  w{w}: Calmar {cal:.2f} MDD {m:.1f}")
print("\n[LOWO — 슈퍼위너 제외, w0.03]")
print(f"  {'제외':14s}{'base':>8s}{'w0.03':>8s}{'Δ':>7s}")
for ex,nm in [('000660','SK하이닉스'),('080220','제주반도체'),('089970','브이엠'),('042700','한미반도체'),('039030','이오테크닉스'),('353200','에스앤에스텍')]:
    _,_,b=sim(0,exclude=ex); _,_,m=sim(0.03,exclude=ex)
    print(f"  −{nm:12s}{b:>8.2f}{m:>8.2f}{m-b:>+7.2f}")

# === wr 기반 BT (production 매매룰 E3X6S3, 3일 가중순위) ===
import bisect
def cr_ranks(w):
    """날짜별 {ticker: cr} — score+w*mom5z 재정렬 순위(1부터)"""
    out={}
    for d in dts:
        sc=[(t, s+w*z) for t,s,z in ar[d]]
        sc.sort(key=lambda x:-x[1])
        out[d]={t:i+1 for i,(t,_) in enumerate(sc)}
    return out
def sim_wr(w,exclude=None,sub=None):
    cr=cr_ranks(w); held=[];out=[];prev=None
    for k,d in enumerate(dts):
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        out.append((d,ret))
        if not reg.get(d,True): held=[]; prev=d; continue
        # wr = 0.4*cr_d0 + 0.35*cr_d1 + 0.25*cr_d2 (Top20 밖 PENALTY 50)
        def crv(t,idx):
            if idx<0: return 50.0
            dd=dts[idx]; r=cr.get(dd,{}).get(t,999); return r if r<=20 else 50.0
        allt=set(cr[d].keys())
        if exclude: allt.discard(exclude)
        wr={}
        for t in allt:
            if cr[d].get(t,999)>50: continue
            wr[t]=0.4*crv(t,k)+0.35*crv(t,k-1)+0.25*crv(t,k-2)
        ranked=sorted(wr.items(),key=lambda x:x[1])
        wrrank={t:i+1 for i,(t,_) in enumerate(ranked)}
        # 이탈: wr rank>6
        held=[t for t in held if wrrank.get(t,999)<=6]
        # 진입: wr rank<=3, 빈 슬롯
        for t,_ in ranked:
            if len(held)>=3: break
            if wrrank[t]<=3 and t not in held: held.append(t)
        prev=d
    a=np.array([r for dd,r in out if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
print("\n[wr 기반 BT — production 매매룰 E3X6S3, 3일 가중]")
bc,bm,bb=sim_wr(0)
print(f"baseline(w=0): Calmar {bb:.2f} (CAGR {bc:.0f}% MDD {bm:.1f}%)")
print(f"  {'w':>6s}{'전체':>8s}{'강세':>8s}{'약세':>8s}{'최근':>8s}{'MDD':>8s}")
for w in [0.02,0.03,0.04,0.05]:
    c,m,cal=sim_wr(w); _,_,c1=sim_wr(w,sub=P1); _,_,c2=sim_wr(w,sub=P2); _,_,c3=sim_wr(w,sub=P3)
    print(f"  {w:>6.2f}{cal:>8.2f}{c1:>8.2f}{c2:>8.2f}{c3:>8.2f}{m:>8.1f}")
print(f"  (baseline 기간별: 강세 {sim_wr(0,sub=P1)[2]:.2f} 약세 {sim_wr(0,sub=P2)[2]:.2f} 최근 {sim_wr(0,sub=P3)[2]:.2f})")
