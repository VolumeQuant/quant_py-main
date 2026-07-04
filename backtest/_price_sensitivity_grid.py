# -*- coding: utf-8 -*-
"""순위 가격민감도 실험 — 가격 팩터 10+ 종류를 production top후보 재정렬로 BT.
production score에 w×가격팩터z 가산 → top3 재선택 → Calmar(국면 방어). baseline 대비."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
# 시장수익 (RS용)
kret={}
kv=kc.values; kidx=[d.strftime('%Y%m%d') for d in kc.index]; kmap={d:i for i,d in enumerate(kidx)}
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi:
        rk=sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99))
        ar[dt]=[(x['ticker'],x.get('score',0)) for x in rk[:10]]; dts.append(dt)
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
def pxv(t,d):
    if t not in pcol or d not in tdi: return None
    v=parr[tdi[d],pcol[t]]; return float(v) if v>0 else None
def ret_n(t,d,n):
    i=tdi.get(d);
    if i is None or i<n: return None
    p0=parr[i-n,pcol[t]] if t in pcol else None; p1=parr[i,pcol[t]] if t in pcol else None
    return (p1/p0-1) if (p0 and p1 and p0>0 and p1>0) else None
def ma_dev(t,d,n):  # 이격도
    i=tdi.get(d)
    if i is None or i<n or t not in pcol: return None
    w=parr[i-n:i,pcol[t]]; w=w[w>0]; cur=parr[i,pcol[t]]
    return (cur/np.mean(w)-1) if (len(w)>=n//2 and cur>0) else None
def high_near(t,d,n):  # 신고가 근접
    i=tdi.get(d)
    if i is None or i<n or t not in pcol: return None
    w=parr[i-n:i+1,pcol[t]]; w=w[w>0]; cur=parr[i,pcol[t]]
    return (cur/np.max(w)) if (len(w)>=n//2 and cur>0) else None
def vol_n(t,d,n):
    i=tdi.get(d)
    if i is None or i<n+1 or t not in pcol: return None
    w=parr[i-n:i+1,pcol[t]]; r=np.diff(w)/w[:-1]; r=r[np.isfinite(r)]
    return np.std(r) if len(r)>2 else None
def kret_n(d,n):
    ki=kmap.get(d)
    if ki is None or ki<n: return None
    return kv[ki]/kv[ki-n]-1 if kv[ki-n]>0 else None
# 가격 팩터들
FACTORS={
 'mom5': lambda t,d: ret_n(t,d,5),
 'mom10': lambda t,d: ret_n(t,d,10),
 'mom20': lambda t,d: ret_n(t,d,20),
 'mom60': lambda t,d: ret_n(t,d,60),
 'ilgak20': lambda t,d: ma_dev(t,d,20),
 'accel': lambda t,d: (ret_n(t,d,10) or 0)-(ret_n(t,d,20) or 0),  # 가속(단기>중기)
 'RS20': lambda t,d: (ret_n(t,d,20) or 0)-(kret_n(d,20) or 0),  # 상대강도
 'highnear60': lambda t,d: high_near(t,d,60),
 'voladj_mom': lambda t,d: ((ret_n(t,d,20) or 0)/(vol_n(t,d,20) or 1)) if vol_n(t,d,20) else None,
 'ilgak_over': lambda t,d: -(ma_dev(t,d,20) or 0),  # 과열 감점(급등하면↓)
 'mom20_neg': lambda t,d: -(ret_n(t,d,20) or 0),  # 역모멘텀(하락우대)
}
def sim(fac, w):
    fn=FACTORS[fac]; held=[];daily=[];prev=None
    for d in dts:
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[]
        else:
            cand=ar[d]
            if w==0: held=[t for t,_ in cand[:3]]
            else:
                # score z + w×factor z
                fvals=[fn(t,d) for t,_ in cand]; valid=[v for v in fvals if v is not None]
                if len(valid)>=3:
                    fm=np.mean(valid); fs=np.std(valid) or 1
                    scored=[]
                    for (t,sc),fv in zip(cand,fvals):
                        fz=(fv-fm)/fs if fv is not None else 0
                        scored.append((t, sc+w*fz))
                    held=[t for t,_ in sorted(scored,key=lambda z:-z[1])[:3]]
                else: held=[t for t,_ in cand[:3]]
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr, mdd, (cagr/abs(mdd) if mdd<0 else 0)
c,m,base=sim('mom5',0)
print(f"[가격 민감도 실험 — production top10 재정렬, 7.4년 Calmar]")
print(f"baseline(가격팩터 없음): {base:.2f} (CAGR {c:.0f}% MDD {m:.1f}%)\n")
print(f"  {'팩터':14s}{'w0.1':>8s}{'w0.2':>8s}{'w0.3':>8s}{'w0.5':>8s}")
best=None
for fac in FACTORS:
    row=f"  {fac:14s}"
    for w in [0.1,0.2,0.3,0.5]:
        _,_,cal=sim(fac,w); row+=f"{cal:>8.2f}"
        if best is None or cal>best[0]: best=(cal,fac,w)
    print(row)
print(f"\n★ 최고: {best[1]} w{best[2]} Calmar {best[0]:.2f} (baseline {base:.2f}, {'+' if best[0]>base else ''}{best[0]-base:.2f})")

# === Step 2: mom5 기간별 WF + 인접 안정성 ===
def sim_sub(fac,w,sub):
    fn=FACTORS[fac]; held=[];out=[];prev=None
    for d in dts:
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        out.append((d,ret))
        if not reg.get(d,True): held=[]
        else:
            cand=ar[d]
            if w==0: held=[t for t,_ in cand[:3]]
            else:
                fvals=[fn(t,d) for t,_ in cand]; valid=[v for v in fvals if v is not None]
                if len(valid)>=3:
                    fm=np.mean(valid); fs=np.std(valid) or 1
                    scored=[(t, sc+w*((fv-fm)/fs if fv is not None else 0)) for (t,sc),fv in zip(cand,fvals)]
                    held=[t for t,_ in sorted(scored,key=lambda z:-z[1])[:3]]
                else: held=[t for t,_ in cand[:3]]
        prev=d
    return out
def cal_of(out,sub=None):
    a=np.array([r for d,r in out if (not sub or sub[0]<=d<=sub[1])])
    if len(a)<20: return 0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
P1=('20190102','20211231');P2=('20220101','20231231');P3=('20240101','20261231')
print("\n[Step 2: 기간별 Calmar (전체/강세19-21/약세22-23/최근24-26)]")
print(f"  {'설정':18s}{'전체':>8s}{'강세':>8s}{'약세':>8s}{'최근':>8s}")
for fac,w in [('mom5',0),('mom5',0.05),('mom5',0.1),('mom5',0.15),('mom60',0.2),('highnear60',0.1)]:
    o=sim_sub(fac,w,None)
    lbl=f'{fac} w{w}' if w else 'baseline'
    print(f"  {lbl:18s}{cal_of(o):>8.2f}{cal_of(o,P1):>8.2f}{cal_of(o,P2):>8.2f}{cal_of(o,P3):>8.2f}")
print("  → 전 기간 baseline 넘어야 robust. 특정기간만이면 과적합")

# === Step 3: LOWO + 인접 w 정밀 ===
def sim_ex(fac,w,exclude):
    fn=FACTORS[fac]; held=[];daily=[];prev=None
    for d in dts:
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[]
        else:
            cand=[(t,s) for t,s in ar[d] if t!=exclude]
            if w==0: held=[t for t,_ in cand[:3]]
            else:
                fvals=[fn(t,d) for t,_ in cand]; valid=[v for v in fvals if v is not None]
                if len(valid)>=3:
                    fm=np.mean(valid); fs=np.std(valid) or 1
                    scored=[(t, sc+w*((fv-fm)/fs if fv is not None else 0)) for (t,sc),fv in zip(cand,fvals)]
                    held=[t for t,_ in sorted(scored,key=lambda z:-z[1])[:3]]
                else: held=[t for t,_ in cand[:3]]
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
print("\n[Step 3a: 인접 w 안정성 (mom5)]")
for w in [0.06,0.08,0.10,0.12,0.14]:
    _,_,c=sim('mom5',w); print(f"  w{w}: {c:.2f}")
print("\n[Step 3b: LOWO — 슈퍼위너 제외해도 mom5 w0.1 우위 유지?]")
print(f"  {'제외종목':14s}{'baseline':>9s}{'mom5 w0.1':>10s}{'Δ':>7s}")
for ex,nm in [('000660','SK하이닉스'),('080220','제주반도체'),('089970','브이엠'),('036930','주성엔지'),('042700','한미반도체'),('039030','이오테크닉스')]:
    b=sim_ex('mom5',0,ex); m=sim_ex('mom5',0.1,ex)
    print(f"  −{nm:12s}{b:>9.2f}{m:>10.2f}{m-b:>+7.2f}")

# === Step 4: 조합 + 초단기 + 갭 ===
def gap(t,d):  # 당일 시가갭 대용 불가 → 1일 수익률(초단기 반응)
    return ret_n(t,d,1)
def mom3(t,d): return ret_n(t,d,3)
FACTORS['mom3']=mom3; FACTORS['gap1']=gap
def sim_combo(specs):  # specs=[(fac,w),...]
    held=[];daily=[];prev=None
    for d in dts:
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[]
        else:
            cand=ar[d]
            scored=[]
            for t,sc in cand:
                add=0
                for fac,w in specs:
                    fvals=[FACTORS[fac](tt,d) for tt,_ in cand]; valid=[v for v in fvals if v is not None]
                    if len(valid)>=3:
                        fm=np.mean(valid);fs=np.std(valid) or 1;fv=FACTORS[fac](t,d)
                        add+=w*((fv-fm)/fs if fv is not None else 0)
                scored.append((t,sc+add))
            held=[t for t,_ in sorted(scored,key=lambda z:-z[1])[:3]]
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
print("\n[Step 4: 조합/초단기/갭]")
for lbl,specs in [
  ('mom3 w0.1',[('mom3',0.1)]),('gap1 w0.1',[('gap1',0.1)]),
  ('mom5 w0.1',[('mom5',0.1)]),
  ('mom5+mom60',[('mom5',0.08),('mom60',0.1)]),
  ('mom5+highnear',[('mom5',0.08),('highnear60',0.06)]),
  ('mom5+RS20',[('mom5',0.08),('RS20',0.06)]),
  ('mom5+ilgak_over',[('mom5',0.1),('ilgak_over',0.05)]),
]:
    print(f"  {lbl:18s}{sim_combo(specs):.2f}")
