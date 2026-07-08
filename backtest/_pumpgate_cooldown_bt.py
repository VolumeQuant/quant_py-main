# -*- coding: utf-8 -*-
"""펌프게이트 쿨다운 BT — 한번 게이트(이격도>1.4 & growth<1.3) 걸리면 이후 N거래일 억제 유지.
N=0 = 현행(트리거일만 차단). N=1/2/3/5/10 비교. production-faithful(recent_ca 주입, wr smoothing 엔진내장).
게이트 판정 = raw OHLCV 이격도(_pumpgate_overlay와 동일), 수익률 = back-adjusted."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); RC=0.3
PUMP_DISP=1.4; PUMP_GROWTH=1.3
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50:s2.loc[s2.index<d]*=f
    return s2
raw=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan)
prices=raw.apply(ba)
# ── raw 이격도 (production 게이트와 동일) ──
ne=raw.notna().sum(axis=1)>=(raw.shape[1]*0.5); biz=raw.loc[ne]
disp=(biz/biz.rolling(20).mean())
bidx={d:i for i,d in enumerate(biz.index.strftime('%Y%m%d'))}
bcol={c:j for j,c in enumerate(biz.columns)}; darr=disp.values
def disp_of(tk,d):
    i=bidx.get(d); j=bcol.get(tk)
    if i is None or j is None: return None
    v=darr[i,j]; return float(v) if v==v else None
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0];m20=kc.rolling(20).mean();m80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(m80.get(ts,np.nan)):reg[d]=md;continue
        s=bool(m20[ts]>m80[ts])
        if s==ss:stk+=1
        else:stk=1;ss=s
        if stk>=5 and md!=s:md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
ar_all={};dall=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':ar_all[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dall.append(dt)
dall=sorted(dall); didx={d:i for i,d in enumerate(dall)}
# ── 트리거 계산: 종목별 트리거 거래일 인덱스(dall 기준) ──
triggers={}  # tk -> sorted list of dall-index
for d in dall:
    i=didx[d]
    for r in ar_all[d]:
        tk=r['ticker']; gv=r.get('growth_s',0) or 0
        dv=disp_of(tk,d)
        if dv is not None and dv>PUMP_DISP and gv<PUMP_GROWTH:
            triggers.setdefault(tk,[]).append(i)
# ── 쿨다운 N → blocked 인덱스 집합(종목별) ──
def blocked_set(N):
    bs={}
    for tk,idxs in triggers.items():
        s=set()
        for t in idxs:
            for k in range(0,N+1):
                if t+k < len(dall): s.add(t+k)
        bs[tk]=s
    return bs
def patch(t,sd,bs=None):
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        i=didx.get(date)
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RC*float(s['recent_ca'])
            if bs is not None:
                blk=bs.get(s['ticker'])
                if blk and i in blk: arr[j]-=100.0
def run(N=None,exclude=None,sub=None):
    sub=sub or dall
    sd={d:[r for r in ar_all[d] if not exclude or r['ticker'] not in exclude] for d in sub}
    t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    bs=blocked_set(N) if N is not None else None
    patch(t,sd,bs)
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    f=list(t._cached_flat);reg=calc_reg(sub)
    r=_run_regime_inner(f,f,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
nogate=run(None)
print(f"[게이트 없음(순수 recent_ca만)] Calmar {nogate[0]:.3f} MDD {nogate[1]:.1f}% 누적 {nogate[2]:.0f}%")
print(f"트리거 발생 종목수 {len(triggers)}, 총 트리거일 {sum(len(v) for v in triggers.values())}\n")
print("[쿨다운 N 스윕 — Calmar (Δ vs N=0현행) / MDD / 차단stock-day]")
base0=None
for N in [0,1,2,3,5,10]:
    bs=blocked_set(N); blkdays=sum(len(v) for v in bs.values())
    c=run(N)
    if N==0: base0=c[0]
    star=' ★현행(쿨다운없음)' if N==0 else ''
    print(f"  N={N:>2}: Calmar {c[0]:.3f} (Δ{c[0]-base0:+.3f}) MDD {c[1]:.1f}% 누적 {c[2]:.0f}% 차단 {blkdays}{star}")
# ── WF 3블록 (N=3 후보 vs N=0) ──
print("\n[WF 3블록 — N=0 vs N=3]")
blocks=[('19-21','20190102','20211231'),('22-23약세','20220101','20231231'),('24-26','20240101','20261231')]
for nm,a,b in blocks:
    sub=[d for d in dall if a<=d<=b]
    c0=run(0,sub=sub); c3=run(3,sub=sub)
    print(f"  {nm:>8}: N0 {c0[0]:.3f} → N3 {c3[0]:.3f} (Δ{c3[0]-c0[0]:+.3f})")
print("\n[완료]")
