# -*- coding: utf-8 -*-
"""Step3b Tier2 — 이익 가속도(EAC: TTM 영업이익 2차미분, 매출floor 정규화) 신규계산 보너스 BT.
+ 인플렉션게이트(저후행성장 & 이익반등). 저장 안 됨 → 캐시서 계산해 overlay 주입(screen)."""
import sys, io, os, glob, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
ar={};dates=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dates.append(dt)
dates=sorted(dates)
def eac(t,base_ts):
    d=cache.get(t)
    if d is None or 'op' not in d: return None
    op=d['op'][1][d['op'][0]<=np.datetime64(base_ts)]
    rev=d['rev'][1][d['rev'][0]<=np.datetime64(base_ts)] if 'rev' in d else None
    if len(op)<6: return None
    ttm_n=op[-4:].sum(); ttm_p=op[-5:-1].sum(); ttm_p2=op[-6:-2].sum()
    dnow=ttm_n-ttm_p; dprev=ttm_p-ttm_p2
    floor=abs(rev[-4:].sum())*0.02 if (rev is not None and len(rev)>=4) else 1
    den=max(abs(ttm_p), floor, 1)
    return (dnow-dprev)/den
# EAC z (당일 종목 단면) 사전계산
eacz={}
for dt in dates:
    ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
    vals={r['ticker']:eac(r['ticker'],ts) for r in ar[dt]}
    v=np.array([x for x in vals.values() if x is not None])
    if len(v)>=20:
        m,s=np.median(v),(np.percentile(v,84)-np.percentile(v,16))/2 or 1  # robust
        eacz[dt]={tk:((x-m)/s if x is not None else 0.0) for tk,x in vals.items()}
        # clip
        eacz[dt]={tk:float(np.clip(z,-3,3)) for tk,z in eacz[dt].items()}
    else: eacz[dt]={}
print(f"[표본] EAC 산출일 {len(eacz)}/{len(dates)}, 평균 비결측 {np.mean([len([1 for r in ar[dt] if eacz.get(dt,{}).get(r['ticker'],0)!=0]) for dt in dates[::30]]):.0f}/72")
def runbt(sub, W, gate=False):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}; ez=eacz.get(d,{})
        def ov(tk):
            base=0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0)
            z=ez.get(tk,0.0)
            if gate and (fd[tk].get('growth_s') or 0)>1.5: z=0  # 이미 후행성장 높으면 마스킹(인플렉션만)
            return base + W*max(z,0)  # 양의 가속만 가산(boost)
        t._overlay_pre[d]=np.array([ov(tk) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('cagr',0)*100,r.get('mdd',0)*100
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]
def show(nm,W,gate=False):
    o=[runbt([d for d in dates if lo<=d<=hi],W,gate) for _,lo,hi in segs]
    print(f"  {nm:30s} 전체{o[0][0]:>5.2f} 19-21 {o[1][0]:>5.2f} 약세 {o[2][0]:>5.2f} 24-26 {o[3][0]:>6.2f}")
print(f"\n[Step3b BT: 이익가속도 EAC]\n  {'config':30s} {'전체':>7s} {'19-21':>8s} {'약세':>7s} {'24-26':>8s}")
show('baseline',0)
show('+EAC양가속 ×0.05',0.05)
show('+EAC양가속 ×0.10',0.10)
show('+EAC ×0.10 (저후행성장 게이트)',0.10,True)

# === Step3c: 하방 적용 — 고후행성장인데 이익 감속(EAC<0)=성장 꺼짐 함정 → 페널티 ===
def runbt_pen(sub, Wpen, gthr, ethr):
    reg=calc_reg(sub)
    orig={d:[(r.get('growth_s')or 0.0) for r in ar[d]] for d in sub}
    # growth_s 직접 수정(페널티) → use_stored_growth
    for d in sub:
        ez=eacz.get(d,{})
        for j,r in enumerate(ar[d]):
            g=orig[d][j]; z=ez.get(r['ticker'],0.0)
            r['growth_s']= g*Wpen if (g>gthr and z<ethr) else g  # 고성장+감속 → 성장 깎음
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    for d in sub:  # 복원
        for j,r in enumerate(ar[d]): r['growth_s']=orig[d][j]
    return r.get('calmar',0),r.get('cagr',0)*100,r.get('mdd',0)*100
def showp(nm,Wpen,gthr,ethr):
    o=[runbt_pen([d for d in dates if lo<=d<=hi],Wpen,gthr,ethr) for _,lo,hi in segs]
    print(f"  {nm:32s} 전체{o[0][0]:>5.2f} 19-21 {o[1][0]:>5.2f} 약세 {o[2][0]:>5.2f} 24-26 {o[3][0]:>6.2f} MDD{o[0][2]:>6.1f}%")
print(f"\n[Step3c: 성장꺼짐 하방페널티 (고성장+이익감속)]\n  {'config':32s} {'전체':>7s} {'19-21':>8s} {'약세':>7s} {'24-26':>8s}")
showp('baseline',1.0,99,-99)
showp('고growth>1.0 & EAC<-0.5 → ×0.5',0.5,1.0,-0.5)
showp('고growth>1.0 & EAC<0 → ×0.5',0.5,1.0,0.0)
showp('고growth>1.5 & EAC<-0.3 → ×0.3',0.3,1.5,-0.3)
