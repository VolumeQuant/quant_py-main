# -*- coding: utf-8 -*-
"""lumpiness(CV) 페널티 검증. 방향무관 분기매출 변동성(CV) 큰 종목 growth_s ×penalty.
production(계절성 'curr')에 ADD. baseline vs sweep + 디바이스(187870)/제주반도체(080220) 진단.
빠른 경로: 저장 growth_s 직접 수정(=FG 페널티와 동일, _use_stored_growth=True)."""
import sys, io, os, glob, json, time, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_202606*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={}; md=True; stk=0; ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md; continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
# ---- state 로드 (dict 보존, orig growth_s 기록) ----
print("state 로드 중...", flush=True)
t0=time.time()
ar={}; dates=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
dates=sorted(dates)
orig_g={dt:[ (r.get('growth_s') or 0.0) for r in ar[dt]] for dt in dates}
print(f"  {len(dates)}일 로드 {time.time()-t0:.1f}s", flush=True)
# ---- 분기 매출 시리즈 (550 ticker) ----
tks=pickle.load(open(os.path.join(PROJ,'_lump_tickers.pkl'),'rb'))
print(f"분기매출 로드 ({len(tks)}종목)...", flush=True); t0=time.time()
qser={}
for tk in tks:
    p=os.path.join(PROJ,'data_cache',f'fs_dart_{tk}.parquet')
    if not os.path.exists(p): continue
    d=pd.read_parquet(p)
    q=d[(d['공시구분']=='q')&(d['계정']=='매출액')].copy()
    q['rcept_dt']=pd.to_datetime(q['rcept_dt'],errors='coerce')
    q['기준일']=pd.to_datetime(q['기준일'],errors='coerce')
    q=q.dropna(subset=['rcept_dt']).sort_values('rcept_dt')
    if len(q)>=8: qser[tk]=(q['rcept_dt'].values, q['값'].astype(float).values)
print(f"  {len(qser)}종목 분기시리즈 {time.time()-t0:.1f}s", flush=True)
def lump_flag(tk, base_ts, cv_thr, mm_thr):
    s=qser.get(tk)
    if s is None: return False
    rc, vals = s
    mask = rc <= np.datetime64(base_ts)
    v = vals[mask]
    if len(v) < 8: return False
    v = v[-8:]
    if (v <= 0).any(): return False
    cv = v.std()/v.mean()
    if cv <= cv_thr: return False
    last4 = v[-4:]
    if mm_thr > 0 and last4.min()/last4.max() > mm_thr: return False  # 면제
    return True
def build_flags(cv_thr, mm_thr):
    flags={}
    for dt in dates:
        ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
        fset=set()
        for r in ar[dt]:
            if lump_flag(r['ticker'], ts, cv_thr, mm_thr): fset.add(r['ticker'])
        flags[dt]=fset
    return flags
def apply_pen(flags, penalty):
    for dt in dates:
        og=orig_g[dt]; fs=flags.get(dt,set()) if flags else set()
        for j,r in enumerate(ar[dt]):
            r['growth_s'] = og[j]*penalty if r['ticker'] in fs else og[j]
def runbt(sub, reg):
    t=TurboSimulator({d:ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
def metrics(rets):
    a=np.asarray(rets,float); n=len(a); eq=np.cumprod(1+a)
    cagr=(eq[-1]**(252/max(n,1))-1)*100; peak=np.maximum.accumulate(eq); mdd=((eq-peak)/peak).min()*100
    return (cagr/abs(mdd) if mdd<0 else 0), cagr, mdd
def entry_days(tk):
    # 현재 ar 상태(penalty 반영 후)로 재랭킹한 rank<=3 일수 — TurboSim 내부 랭킹과 별개라 근사용으로 stored 사용 불가.
    # 대신 penalty 적용 후 멀티팩터 재계산 rank 사용
    cnt=0; tot=0
    for dt in dates:
        rows=ar[dt]
        sc=[]
        for r in rows:
            g=r['growth_s']
            s=0.15*(r.get('value_s') or 0)+0.0*(r.get('quality_s') or 0)+0.55*g+0.30*(r.get('mom_12m_s') or r.get('momentum_s') or 0)
            s+=0.2*(r.get('overheat_pen') or 0)+0.05*(r.get('mom_10_z') or 0)+0.06*(r.get('vol_low_z') or 0)
            sc.append((s,r['ticker']))
        sc.sort(reverse=True)
        for rk,(s,t) in enumerate(sc[:3],1):
            if t==tk: cnt+=1
        if any(t==tk for _,t in sc): tot+=1
    return cnt,tot
# 순수 min/max(최근4분기 매출) < T 페널티 (CV 무관, EDA 최고 분리지표)
def lump_flag_mm(tk, base_ts, T):
    s=qser.get(tk)
    if s is None: return False
    rc, vals = s
    v = vals[rc <= np.datetime64(base_ts)]
    if len(v) < 8: return False
    if (v[-8:] <= 0).any(): return False
    last4 = v[-4:]
    return last4.min()/last4.max() < T
def build_flags_mm(T):
    flags={}
    for dt in dates:
        ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
        flags[dt]=set(r['ticker'] for r in ar[dt] if lump_flag_mm(r['ticker'],ts,T))
    return flags
reg=calc_reg(dates)
import sys as _s
print(f"\n[{dates[0]}~{dates[-1]} {len(dates)}일] lumpiness 페널티 — production(계절성 curr)에 ADD\n",flush=True)
apply_pen(None,1.0)
rb=runbt(dates,reg); mb=metrics(rb['_daily_rets'])
dB=entry_days('187870'); jB=entry_days('080220')
print(f"  {'config':34s}{'Calmar':>8s}{'CAGR':>7s}{'MDD':>8s}  디바이스  제주  브이엠",flush=True)
print(f"  {'baseline(현행)':34s}{mb[0]:>8.2f}{mb[1]:>6.0f}%{mb[2]:>7.1f}%   {dB[0]:>3}일  {jB[0]:>3}일  {entry_days('089970')[0]:>3}일",flush=True)
PEN=0.3
print("  -- 날카로운 순수 min/max(최근4분기) < T 페널티 --",flush=True)
for T in [0.20,0.22,0.25,0.28]:
    flags=build_flags_mm(T); nf=sum(len(v) for v in flags.values())
    apply_pen(flags,PEN); r=runbt(dates,reg); m=metrics(r['_daily_rets'])
    dd=entry_days('187870'); jj=entry_days('080220'); vv=entry_days('089970')
    print(f"  min/max<{T} ×{PEN}  (flag{nf:>5}){m[0]:>8.2f}{m[1]:>6.0f}%{m[2]:>7.1f}%   {dd[0]:>3}일  {jj[0]:>3}일  {vv[0]:>3}일",flush=True)
# 하드컷(진입차단) 버전도 — 가장 강하게
print("  -- min/max<0.25 하드(growth ×0.05, 사실상 제외) --",flush=True)
for T in [0.22,0.25]:
    flags=build_flags_mm(T); nf=sum(len(v) for v in flags.values())
    apply_pen(flags,0.05); r=runbt(dates,reg); m=metrics(r['_daily_rets'])
    dd=entry_days('187870'); jj=entry_days('080220'); vv=entry_days('089970')
    print(f"  min/max<{T} ×0.05 (flag{nf:>5}){m[0]:>8.2f}{m[1]:>6.0f}%{m[2]:>7.1f}%   {dd[0]:>3}일  {jj[0]:>3}일  {vv[0]:>3}일",flush=True)
apply_pen(None,1.0)
