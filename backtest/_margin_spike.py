# -*- coding: utf-8 -*-
"""마진 급등 일회성 필터 연구. v80.24 baseline(E3/X6/S3, W0.2).
신호: 최근 분기 영업이익률 / 과거 4분기 중앙 영업이익률 = spike. 높으면 일회성 의심.
삼지전자: 17.5%/~4% ≈ 4.4x. PIT(rcept_dt) 준수."""
import sys, json, glob, bisect, time
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()
DATA=Path('data_cache'); PEG=Path('backtest/state_peg_bt'); PENALTY=50;TOP_N=20;W=0.2; EB,XB,SLOTS=3,6,3

# ── 종목별 마진 spike 시계열 (rcept_dt 기준 PIT) ──
print('영업이익률 spike 시계열 구축...',flush=True)
spike_series={}  # tk -> list of (avail_date 'YYYYMMDD', spike_ratio, latest_margin)
for f in glob.glob('data_cache/fs_dart_*.parquet'):
    tk=f.split('_')[-1].replace('.parquet','')
    try:
        d=pd.read_parquet(f, columns=['계정','기준일','값','rcept_dt'])
        d['기준일']=pd.to_datetime(d['기준일']); d['rcept_dt']=pd.to_datetime(d['rcept_dt'])
        rev=d[d['계정']=='매출액'].sort_values('기준일').drop_duplicates('기준일',keep='last').set_index('기준일')
        op=d[d['계정']=='영업이익'].sort_values('기준일').drop_duplicates('기준일',keep='last').set_index('기준일')
        common=rev.index.intersection(op.index)
        if len(common)<5: continue
        common=sorted(common)
        margins=[]; rcepts=[]
        for q in common:
            rv=rev.at[q,'값']; opv=op.at[q,'값']
            if rv and rv>0:
                margins.append(opv/rv); rcepts.append(rev.at[q,'rcept_dt'])
            else:
                margins.append(np.nan); rcepts.append(rev.at[q,'rcept_dt'])
        ser=[]
        for i in range(4,len(margins)):
            m=margins[i]; hist=[x for x in margins[i-4:i] if not np.isnan(x)]
            if np.isnan(m) or len(hist)<2: continue
            hm=np.median(hist)
            # spike: 현재마진/과거중앙. 과거가 0근처면 차이(%p)로 보강
            if hm>0.005:
                spike=m/hm
            else:
                spike=1.0 + (m-hm)*20  # 저마진 기저: %p 차이 스케일
            rc=rcepts[i]
            if pd.notna(rc):
                ser.append((pd.Timestamp(rc).strftime('%Y%m%d'), float(spike), float(m)))
        ser.sort()
        if ser: spike_series[tk]=ser
    except Exception: pass
print(f'  {len(spike_series)} 종목, {time.time()-t0:.0f}s',flush=True)
def spike_asof(tk,ds):
    s=spike_series.get(tk)
    if not s: return None
    i=bisect.bisect_right([x[0] for x in s],ds)-1
    return (s[i][1],s[i][2]) if i>=0 else None  # (spike, margin)

# 삼지/에스에이엠티 확인
for tk,nm in [('037460','삼지전자'),('031330','에스에이엠티'),('000660','SK하이닉스'),('089970','브이엠')]:
    r=spike_asof(tk,'20260605')
    print(f'  {nm}: spike={r[0]:.1f}x, 마진={r[1]*100:.1f}%' if r else f'  {nm}: 데이터없음')

ohlcv=pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*_*.parquet'))[-1]).replace(0,np.nan); ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(str(DATA/'kospi_yf.parquet'))['close'].sort_index()
RAW={}
for f in sorted(PEG.glob('ranking_*.json')):
    ds=f.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8 and '20190102'<=ds<='20260605'): continue
    rows=json.load(open(f,encoding='utf-8')).get('rankings',[])
    if rows: RAW[ds]=[(str(r['ticker']).zfill(6),(r.get('score',0.0)or 0.0)+W*(r.get('overheat_pen',0.0)or 0.0)) for r in rows]
AD=sorted(RAW)
def reg_f():
    sma=kospi.rolling(20).mean();lma=kospi.rolling(80).mean();r={};md=False;stk=0;ss=None
    for d in AD:
        ts=pd.Timestamp(d);sv=sma.get(ts);lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): r[d]=md;continue
        s=sv>lv; stk=stk+1 if s==ss else 1; ss=s
        if stk>=5 and md!=s: md=s
        r[d]=md
    return r
reg=reg_f()
def gp(d,tk):
    ts=pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx=ohlcv.index.searchsorted(ts)
        if idx>=len(ohlcv): return None
        ts=ohlcv.index[idx]
    v=ohlcv.at[ts,tk] if tk in ohlcv.columns else None
    return v if (v is not None and pd.notna(v) and v>0) else None
def keep(d,tk,thr,minmargin=0.08):
    if thr is None: return True
    r=spike_asof(tk,d)
    if r is None: return True  # 데이터없으면 통과
    spike,margin=r
    # 마진이 의미있게 높고(>8%) AND spike 크면 제외 (저마진 노이즈 회피)
    return not (spike>=thr and margin>=minmargin)
def run(thr,exclude=None,sub=None,minm=0.08):
    crc={}
    for d,rows in RAW.items():
        items=sorted([(tk,sc) for (tk,sc) in rows if keep(d,tk,thr,minm) and not(exclude and tk in exclude)],key=lambda x:-x[1])
        crc[d]={tk:i+1 for i,(tk,_) in enumerate(items)}
    pf={};eq=1.0;eh={}
    rng=AD if sub is None else [d for d in AD if sub[0]<=d<=sub[1]]
    for i,d in enumerate(rng):
        ib=reg.get(d,True);er=EB if ib else 0;xr=XB if ib else 8
        if i>=1 and pf:
            rs=[gp(d,tk)/gp(rng[i-1],tk)-1 for tk in pf if gp(rng[i-1],tk) and gp(d,tk)]
            if rs: eq*=(1+np.mean(rs)*len(pf)/SLOTS)
        eh[d]=eq
        if i>=1 and reg.get(rng[i-1],True)!=ib: pf.clear()
        if not ib: continue
        cr0=crc.get(d,{});cr1=crc.get(rng[i-1],{}) if i>=1 else {};cr2=crc.get(rng[i-2],{}) if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N};t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c in cr0.items()}
        for tk in list(pf.keys()):
            if wr.get(tk,999)>xr: del pf[tk]
        for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:er]:
            if tk in pf or len(pf)>=SLOTS: continue
            if gp(d,tk): pf[tk]=gp(d,tk)
    ea=np.array(list(eh.values()))
    if len(ea)<30: return 0,0,0
    cagr=(ea[-1]**(252/len(ea))-1)*100;p=np.maximum.accumulate(ea);mdd=-((ea-p)/p).min()*100
    return cagr/mdd if mdd>0 else 0,cagr,mdd
base=run(None)
print(f'\nbaseline E3/X6/S3: Cal {base[0]:.3f} MDD {base[2]:.2f}%')
print('마진급등 제외 (spike>=N배 & 마진>=8%):')
print(f'{"임계":>10}{"Cal":>8}{"Δ":>8}{"MDD":>8}')
for thr in [2,2.5,3,4,5]:
    c,cg,m=run(thr)
    fl=' ★' if c-base[0]>0.10 else (' +' if c>base[0] else '')
    print(f'  spike>={thr}{c:>8.3f}{c-base[0]:>+8.3f}{m:>7.2f}%{fl}')
print(f'\n총 {time.time()-t0:.0f}s')
