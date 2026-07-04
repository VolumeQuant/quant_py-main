# -*- coding: utf-8 -*-
"""cr 빠른이탈 production-faithful 재검증 — send_telegram calc_system_returns 정확 복제.
저장 composite_rank + Top20 3일교집합 진입 + composite_rank 3일가중 이탈 + 브레드스 스케일.
이탈만 wr(3일가중) vs cr(당일) 분기."""
import sys,io,os,glob,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
import numpy as np,pandas as pd
R='C:/dev/claude-code/quant_py-main'
px=pd.read_parquet(R+'/data_cache/all_ohlcv_adj_20170601_20260629.parquet').replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(R+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
# state 로드: {date: {ticker: composite_rank}}
CR={};dts=[]
for f in sorted(glob.glob(R+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if not(dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi): continue
    r=json.load(open(f,encoding='utf-8'))['rankings']
    CR[dt]={x['ticker']: x.get('composite_rank', x.get('rank',999)) for x in r}
    dts.append(dt)
dts=sorted(dts)
# 브레드스 스케일
try:
    sys.path.insert(0,R); from breadth_diagnostic import breadth_scale_by_date as _bsbd
    BRD=_bsbd(list(dts)); print(f"브레드스 스케일 로드: {sum(1 for v in BRD.values() if v<1.0)}일 발동")
except Exception as e:
    BRD={}; print(f"브레드스 미로드({e}) — 스케일 1.0")
reg={};md=True;stk=0;ss=None
for dd in dts:
    ts=pd.Timestamp(dd[:4]+'-'+dd[4:6]+'-'+dd[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[dd]=md;continue
    s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
    if stk>=5 and md!=s: md=s
    reg[dd]=md
def pxv(t,d): return parr[tdi[d],pcol[t]] if (t in pcol and d in tdi) else None
def sim(exit_mode, exit_rank=6, use_breadth=True, sub=None):
    port=set(); prev=None; daily=[]
    for i,d0 in enumerate(dts):
        # 수익률 (전일 보유 → 오늘)
        avg=0.0
        if port and prev:
            rr=[pxv(t,d0)/pxv(t,prev)-1 for t in port if pxv(t,prev) and pxv(t,d0) and pxv(t,prev)>0 and pxv(t,d0)>0]
            avg=np.mean(rr) if rr else 0.0
        sc=BRD.get(d0,1.0) if use_breadth else 1.0
        daily.append((d0, avg*sc))
        if i<2: continue
        d1,d2=dts[i-1],dts[i-2]
        if not reg.get(d0,True):
            port=set(); prev=d0; continue
        if reg.get(dts[i-1],True)!=reg.get(d0,True): port.clear()  # 국면전환 청산
        a0,a1,a2=CR[d0],CR[d1],CR[d2]
        def wr(t):
            c0=a0.get(t,50); c1=a1.get(t,50); c2=a2.get(t,50)
            return c0*0.4+c1*0.35+c2*0.25
        def cr(t): return a0.get(t,50)
        # 이탈
        exitf = wr if exit_mode=='wr' else cr
        port={t for t in port if exitf(t)<=exit_rank}
        # 진입: Top20 3일 교집합 + wr top3
        t20=lambda a:{t for t,r in a.items() if r<=20}
        common=t20(a0)&t20(a1)&t20(a2)
        cand=sorted(common,key=wr)
        for t in cand:
            if len(port)>=3: break
            if wr(t)<=3: port.add(t)
        prev=d0
    a=np.array([r for dd,r in daily if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
P1=('20190102','20211231');P2=('20220101','20231231');P3=('20240101','20261231')
print("\n[production-faithful 재검증 — 브레드스 포함, 저장 composite_rank]")
print(f"  {'이탈방식':22s}{'전체':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}{'MDD':>7s}")
for mode,er,lbl in [('wr',6,'wr>6 (현행)'),('cr',6,'cr>6 (당일)'),('cr',5,'cr>5'),('cr',7,'cr>7'),('cr',8,'cr>8')]:
    c,m,cal=sim(mode,er); _,_,a=sim(mode,er,sub=P1); _,_,b=sim(mode,er,sub=P2); _,_,cc=sim(mode,er,sub=P3)
    print(f"  {lbl:22s}{cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}{m:>7.1f}")
print("\n[브레드스 OFF (순수 이탈효과)]")
for mode,er,lbl in [('wr',6,'wr>6'),('cr',6,'cr>6')]:
    c,m,cal=sim(mode,er,use_breadth=False)
    print(f"  {lbl:12s} 전체 {cal:.2f} MDD {m:.1f}")

# === 국면조건부 이탈: 브레드스 발동(약세신호)시 wr, 평시 cr ===
def sim_hybrid(exit_rank=6, cr_thresh=6, sub=None):
    port=set(); prev=None; daily=[]
    for i,d0 in enumerate(dts):
        avg=0.0
        if port and prev:
            rr=[pxv(t,d0)/pxv(t,prev)-1 for t in port if pxv(t,prev) and pxv(t,d0) and pxv(t,prev)>0 and pxv(t,d0)>0]
            avg=np.mean(rr) if rr else 0.0
        sc=BRD.get(d0,1.0); daily.append((d0,avg*sc))
        if i<2: continue
        d1,d2=dts[i-1],dts[i-2]
        if not reg.get(d0,True): port=set(); prev=d0; continue
        if reg.get(dts[i-1],True)!=reg.get(d0,True): port.clear()
        a0,a1,a2=CR[d0],CR[d1],CR[d2]
        def wr(t): return a0.get(t,50)*0.4+a1.get(t,50)*0.35+a2.get(t,50)*0.25
        def cr(t): return a0.get(t,50)
        weak = BRD.get(d0,1.0)<1.0  # 브레드스 발동 = 약세신호
        exitf = wr if weak else cr
        er = exit_rank if weak else cr_thresh
        port={t for t in port if exitf(t)<=er}
        t20=lambda a:{t for t,r in a.items() if r<=20}
        common=t20(a0)&t20(a1)&t20(a2)
        for t in sorted(common,key=wr):
            if len(port)>=3: break
            if wr(t)<=3: port.add(t)
        prev=d0
    a=np.array([r for dd,r in daily if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
print("\n[국면조건부 이탈 — 약세신호(브레드스 발동)시 wr, 평시 cr]")
print(f"  {'방식':24s}{'전체':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}{'MDD':>7s}")
c,m,cal=sim('wr',6); _,_,a=sim('wr',6,sub=P1); _,_,b=sim('wr',6,sub=P2); _,_,cc=sim('wr',6,sub=P3)
print(f"  {'wr>6 (현행 baseline)':24s}{cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}{m:>7.1f}")
for ct in [5,6]:
    c,m,cal=sim_hybrid(6,ct); _,_,a=sim_hybrid(6,ct,sub=P1); _,_,b=sim_hybrid(6,ct,sub=P2); _,_,cc=sim_hybrid(6,ct,sub=P3)
    print(f"  {'hybrid 평시cr>'+str(ct)+' 약세wr>6':24s}{cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}{m:>7.1f}")

# === 두 축 분리: 속도(wr/cr) × 엄격도(임계5/6) 2x2 ===
print("\n[2x2 분해 — 속도(가격민감도) × 엄격도(순위민감도)]")
print(f"  {'':12s}{'임계>6':>18s}{'임계>5':>18s}")
for mode,lbl in [('wr','wr=3일평균'),('cr','cr=당일')]:
    row=f"  {lbl:12s}"
    for er in [6,5]:
        c,m,cal=sim(mode,er); _,_,b=sim(mode,er,sub=P2)  # 전체, 약세
        row+=f"  전체{cal:5.2f}/약세{b:4.2f}"
    print(row)
print("\n  → 세로 비교(wr→cr)=순수 '가격민감도(속도)' 효과")
print("  → 가로 비교(6→5)=순수 '순위 엄격도' 효과 (가격과 무관)")

# === 이탈 임계 재최적화 (v80.24 재검증) — wr 고정, 임계 스윕 ===
print("\n[이탈 임계 스윕 — wr(3일평균) 고정, 브레드스 포함 faithful]")
print(f"  {'임계':8s}{'전체':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}{'MDD':>7s}")
for er in [3,4,5,6,7,8]:
    c,m,cal=sim('wr',er); _,_,a=sim('wr',er,sub=P1); _,_,b=sim('wr',er,sub=P2); _,_,cc=sim('wr',er,sub=P3)
    star=' ★' if er==6 else ''
    print(f"  wr>{er}{'':4s}{cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}{m:>7.1f}{star}")
print("  (★=현행 v80.24)")
# LOWO for wr>5
print("\n[wr>5 LOWO — 슈퍼위너 제외]")
def sim_ex(er,ex,sub=None):  # exclude 종목
    port=set(); prev=None; daily=[]
    for i,d0 in enumerate(dts):
        avg=0.0
        if port and prev:
            rr=[pxv(t,d0)/pxv(t,prev)-1 for t in port if pxv(t,prev) and pxv(t,d0) and pxv(t,prev)>0 and pxv(t,d0)>0]
            avg=np.mean(rr) if rr else 0.0
        daily.append((d0,avg*BRD.get(d0,1.0)))
        if i<2: continue
        d1,d2=dts[i-1],dts[i-2]
        if not reg.get(d0,True): port=set(); prev=d0; continue
        if reg.get(dts[i-1],True)!=reg.get(d0,True): port.clear()
        a0,a1,a2=CR[d0],CR[d1],CR[d2]
        wr=lambda t:a0.get(t,50)*0.4+a1.get(t,50)*0.35+a2.get(t,50)*0.25
        port={t for t in port if t!=ex and wr(t)<=er}
        t20=lambda a:{t for t,r in a.items() if r<=20}
        for t in sorted(t20(a0)&t20(a1)&t20(a2),key=wr):
            if len(port)>=3: break
            if t!=ex and wr(t)<=3: port.add(t)
        prev=d0
    a=np.array([r for dd,r in daily if (not sub or sub[0]<=dd<=sub[1])])
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
for ex,nm in [('000660','SK하이닉스'),('080220','제주반도체'),('089970','브이엠'),('042700','한미반도체')]:
    print(f"  −{nm:12s} wr>5 {sim_ex(5,ex):>6.2f}  wr>6 {sim_ex(6,ex):>6.2f}  Δ{sim_ex(5,ex)-sim_ex(6,ex):>+6.2f}")

# === E×X×S 전체 그리드 재최적화 (브레드스 faithful) ===
def sim2(entry_rank, exit_rank, max_slots, sub=None, exclude=None):
    port=set(); prev=None; daily=[]
    for i,d0 in enumerate(dts):
        avg=0.0
        if port and prev:
            rr=[pxv(t,d0)/pxv(t,prev)-1 for t in port if pxv(t,prev) and pxv(t,d0) and pxv(t,prev)>0 and pxv(t,d0)>0]
            avg=np.mean(rr) if rr else 0.0
        daily.append((d0,avg*BRD.get(d0,1.0)))
        if i<2: continue
        d1,d2=dts[i-1],dts[i-2]
        if not reg.get(d0,True): port=set(); prev=d0; continue
        if reg.get(dts[i-1],True)!=reg.get(d0,True): port.clear()
        a0,a1,a2=CR[d0],CR[d1],CR[d2]
        wr=lambda t:a0.get(t,50)*0.4+a1.get(t,50)*0.35+a2.get(t,50)*0.25
        port={t for t in port if t!=exclude and wr(t)<=exit_rank}
        t20=lambda a:{t for t,r in a.items() if r<=20}
        for t in sorted(t20(a0)&t20(a1)&t20(a2),key=wr):
            if len(port)>=max_slots: break
            if t!=exclude and wr(t)<=entry_rank: port.add(t)
        prev=d0
    a=np.array([r for dd,r in daily if (not sub or sub[0]<=dd<=sub[1])])
    if len(a)<20: return 0,0,0
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0)
print("\n[E×X×S 그리드 — 전체 Calmar 상위 (브레드스 faithful)]")
res=[]
for E in [2,3,4]:
    for X in [4,5,6,7]:
        for S in [2,3,4,5]:
            if X<E: continue
            _,m,cal=sim2(E,X,S)
            res.append((cal,m,E,X,S))
res.sort(reverse=True)
print(f"  {'순위':4s}{'E/X/S':10s}{'전체':>7s}{'MDD':>7s}")
for i,(cal,m,E,X,S) in enumerate(res[:10]):
    cur=' ← 현행' if (E,X,S)==(3,6,3) else ''
    print(f"  {i+1:3d}  E{E}X{X}S{S:<5d}{cal:>7.2f}{m:>7.1f}{cur}")
# 현행 위치
for i,(cal,m,E,X,S) in enumerate(res):
    if (E,X,S)==(3,6,3): print(f"  현행 E3X6S3 = {i+1}위 (Calmar {cal:.2f})")

# === 상위 후보 기간별 WF + 약세 방어 ===
print("\n[상위 후보 기간별 — 약세장 방어가 관문]")
print(f"  {'E/X/S':10s}{'전체':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}{'MDD':>7s}")
cands=[(3,4,5),(3,4,4),(3,5,3),(3,5,4),(3,5,5),(3,6,3),(3,4,3)]
for E,X,S in cands:
    c,m,cal=sim2(E,X,S); _,_,a=sim2(E,X,S,sub=P1); _,_,b=sim2(E,X,S,sub=P2); _,_,cc=sim2(E,X,S,sub=P3)
    cur=' ←현행' if (E,X,S)==(3,6,3) else ''
    flag=' ⚠약세' if b<0.80 else ''
    print(f"  E{E}X{X}S{S}{'':3s}{cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}{m:>7.1f}{cur}{flag}")
print("  (현행 약세 0.84 기준. ⚠=약세 0.80 미만 = 방어 약화)")

# === 브레드스 ON/OFF X스윕 — v80.24(X6) vs 현재(X5) 규명 ===
print("\n[브레드스 ON/OFF 이탈임계 스윕 — 왜 X6→X5 이동?]")
print(f"  {'임계':8s}{'브레드스ON':>12s}{'브레드스OFF':>12s}")
for er in [4,5,6,7]:
    _,_,on=sim('wr',er,use_breadth=True)
    _,_,off=sim('wr',er,use_breadth=False)
    print(f"  wr>{er}{'':4s}{on:>12.2f}{off:>12.2f}")
print("  → OFF에서 X6 최적이면 v80.24 재현(브레드스가 X5로 이동시킴 확인)")

# 인접 CV (X4~6, ON)
import statistics as st
vals=[sim('wr',er)[2] for er in [4,5,6]]
print(f"\n[인접 안정성 X4/5/6 (ON): {[round(v,2) for v in vals]}, CV={st.pstdev(vals)/st.mean(vals):.3f}]")
# 브레드스 OFF LOWO 교차확인 (X5 vs X6)
print("\n[브레드스 OFF LOWO — X5 우위가 브레드스 의존인지]")
def sim_ex_nb(er,ex):
    port=set(); prev=None; daily=[]
    for i,d0 in enumerate(dts):
        avg=0.0
        if port and prev:
            rr=[pxv(t,d0)/pxv(t,prev)-1 for t in port if pxv(t,prev) and pxv(t,d0) and pxv(t,prev)>0 and pxv(t,d0)>0]
            avg=np.mean(rr) if rr else 0.0
        daily.append((d0,avg))  # 브레드스 OFF
        if i<2: continue
        d1,d2=dts[i-1],dts[i-2]
        if not reg.get(d0,True): port=set(); prev=d0; continue
        if reg.get(dts[i-1],True)!=reg.get(d0,True): port.clear()
        a0,a1,a2=CR[d0],CR[d1],CR[d2]
        wr=lambda t:a0.get(t,50)*0.4+a1.get(t,50)*0.35+a2.get(t,50)*0.25
        port={t for t in port if t!=ex and wr(t)<=er}
        t20=lambda a:{t for t,r in a.items() if r<=20}
        for t in sorted(t20(a0)&t20(a1)&t20(a2),key=wr):
            if len(port)>=3: break
            if t!=ex and wr(t)<=3: port.add(t)
        prev=d0
    a=np.array([r for dd,r in daily])
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
for ex,nm in [('000660','SK하이닉스'),('080220','제주반도체'),('089970','브이엠')]:
    print(f"  −{nm:12s} X5 {sim_ex_nb(5,ex):>6.2f}  X6 {sim_ex_nb(6,ex):>6.2f}  Δ{sim_ex_nb(5,ex)-sim_ex_nb(6,ex):>+6.2f}")

# === 브레드스 규율 준수 여부에 따른 X5 vs X6 ===
print("\n[★브레드스 50% 지킬때 vs 안지킬때 — X5 vs X6]")
print(f"  {'':16s}{'전체':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}")
for ub,lbl in [(True,'ON(50%지킴)'),(False,'OFF(안지킴)')]:
    for er in [5,6]:
        c,m,cal=sim('wr',er,use_breadth=ub); _,_,a=sim('wr',er,use_breadth=ub,sub=P1); _,_,b=sim('wr',er,use_breadth=ub,sub=P2); _,_,cc=sim('wr',er,use_breadth=ub,sub=P3)
        print(f"  {lbl:10s}X{er}  {cal:>7.2f}{a:>7.2f}{b:>7.2f}{cc:>7.2f}")
    print()
