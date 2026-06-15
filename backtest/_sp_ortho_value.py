# -*- coding: utf-8 -*-
"""신선하되 직교하는 밸류 검증 (2026-06-15 야간, 사용자 "안해본거 다 해봐").
저장 z-score를 TurboSim에 주입(재생성 없이) → value_s를 변형해 BT.
변형: ①평균회귀(자기 과거 대비) ②G/M 잔차 ③과열캡(overheat_pen) 잔차 ④winsor.
질문: 어떤 fresh-orthogonal 밸류가 annual baseline 3.79를 이기나?
usage: python backtest/_sp_ortho_value.py"""
import sys, io, os, glob, json, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
class _Tee:
    def __init__(self,*fs): self.fs=fs
    def write(self,x):
        for f in self.fs:
            try: f.write(x); f.flush()
            except Exception: pass
    def flush(self):
        for f in self.fs:
            try: f.flush()
            except Exception: pass
_rf=open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'_sp_ortho_value_result.txt'),'w',encoding='utf-8')
sys.stdout=_Tee(sys.stdout,_rf)
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r=s.pct_change(fill_method=None); ev=r[(r<-0.33)|(r>0.45)]; s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50: s2.loc[s2.index<d]*=f
    return s2
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
def calc_reg(dsub):
    reg={};md=True;stk=0;ss=None
    for d in dsub:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def load(folder):
    ar,dates={},[]
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and '20190102'<=dt<='20261231':
            ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
    return ar,sorted(dates)
def zc(a):  # 단면 z-score
    a=np.asarray(a,dtype=float); m=np.nanmean(a); s=np.nanstd(a)
    return (a-m)/s if s>0 else a*0
def transform_value(ar,dates,mode):
    """ar의 각 종목 value_s를 mode대로 변형(in-place 복사본). 반환: 새 ar."""
    ar=copy.deepcopy(ar)
    if mode=='orig': return ar
    # 종목별 value_s 시계열 (평균회귀용)
    if mode=='meanrev':
        hist={}  # ticker -> list of (date, value_s)
        for d in dates:
            for x in ar[d]:
                hist.setdefault(x['ticker'],[]).append((d,x.get('value_s')))
        # 종목별 60일 rolling mean
        mrmap={}  # (date,ticker)->mr
        for tk,seq in hist.items():
            vals=[v for _,v in seq]
            for i,(d,v) in enumerate(seq):
                if v is None: continue
                w=[x for x in vals[max(0,i-60):i] if x is not None]
                if len(w)>=20: mrmap[(d,tk)]=v-np.mean(w)  # 자기 과거 대비 싼가
        for d in dates:
            raw=[mrmap.get((d,x['ticker'])) for x in ar[d]]
            valid=[r for r in raw if r is not None]
            z=zc([r if r is not None else np.nan for r in raw])
            for j,x in enumerate(ar[d]):
                x['value_s']=float(z[j]) if not np.isnan(z[j]) else 0.0
        return ar
    # 단면 잔차 (G/M 또는 overheat)
    for d in dates:
        r=ar[d]
        v=np.array([x.get('value_s') or 0.0 for x in r])
        if mode=='resid_gm':
            g=np.array([x.get('growth_s') or 0.0 for x in r]); m=np.array([x.get('momentum_s') or 0.0 for x in r])
            X=np.column_stack([np.ones(len(v)),g,m])
        elif mode=='resid_oh':
            oh=np.array([x.get('overheat_pen') or 0.0 for x in r])
            X=np.column_stack([np.ones(len(v)),oh])
        elif mode=='winsor':
            for x in r:
                x['value_s']=float(np.clip(x.get('value_s') or 0.0,-1.0,1.0))
            continue
        try:
            beta,_,_,_=np.linalg.lstsq(X,v,rcond=None); res=v-X@beta
            res=zc(res)
            for j,x in enumerate(r): x['value_s']=float(res[j])
        except Exception: pass
    return ar
def regbt(tsim,dates,reg,v,q,g,m):
    tsim._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(tsim._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,dates,tsim._price_arr,tsim._bench_arr,
        tsim._has_bench,tsim._date_row_indices,len(dates),None,None,None,None,
        stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
combos=[(v,q,g,100-v-q-g) for v in range(0,45,5) for q in range(0,45,5) for g in range(10,75,5) if 10<=100-v-q-g<=60]
# 베이스: annual(state) + TTM(_sp3, 균등+overheat 저장됨)
base={}
for folder in ['state','_sp3']:
    if glob.glob(os.path.join(PROJ,folder,'ranking_*.json')): base[folder]=load(folder)
print(f"annual baseline = 3.79 (과열0.2 V15Q0G55M30)\n")
# annual 원본 검증
ar,dates=base['state']; reg=calc_reg(dates)
t=TurboSimulator(ar,dates,prices,overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
b=max([(*c,regbt(t,dates,reg,*c).get('calmar',0)) for c in combos],key=lambda x:x[4])
print(f"[검증] annual 원본 best: V{b[0]}Q{b[1]}G{b[2]}M{b[3]} Cal {b[4]:.3f} (3.79 재현되면 하니스 OK)\n")
# TTM(_sp3) value 변형 실험
ar3,dates3=base['_sp3']; reg3=calc_reg(dates3)
print("[TTM(_sp3) value 변형 — 과열캡0.2, 멀티팩터 풀그리드 best]")
for mode,lbl in [('orig','원본 균등TTM'),('meanrev','평균회귀(자기과거대비)'),
                 ('resid_gm','G/M 잔차(직교화)'),('resid_oh','과열캡 잔차(직교화)'),('winsor','winsor ±1')]:
    art=transform_value(ar3,dates3,mode)
    t=TurboSimulator(art,dates3,prices,overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    res=[(*c,regbt(t,dates3,reg3,*c).get('calmar',0)) for c in combos]
    b=max(res,key=lambda x:x[4])
    print(f"  {lbl:<22}: best V{b[0]}Q{b[1]}G{b[2]}M{b[3]} Cal {b[4]:.3f}")
print(f"\n→ 3.79 넘는 변형 있으면 형이 옳음(fresh-orthogonal 밸류 작동). 없으면 기각 확정.")
