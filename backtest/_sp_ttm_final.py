# -*- coding: utf-8 -*-
"""TTM 최종 공정비교 (2026-06-15): annual(state) vs 균등TTM(_sp3).
완전 최적화: 과열캡 {0.2,0.0} × 멀티팩터 풀그리드 → best → 그 best에 진입/이탈/슬롯 스윕.
질문: 모든 걸 TTM에 맞춰 최적화하면 baseline(annual 3.79)을 이기나?
usage: python backtest/_sp_ttm_final.py"""
import sys, io, os, glob, json
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
_rf=open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'_sp_ttm_final_result.txt'),'w',encoding='utf-8')
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
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_*_2026061*.parquet')))[0]).replace(0,np.nan).apply(ba)
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
def regbt(tsim,dates,reg,v,q,g,m,oe=3,ox=6,os_=3):
    tsim._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(tsim._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,oe,ox,os_,reg,dates,tsim._price_arr,tsim._bench_arr,
        tsim._has_bench,tsim._date_row_indices,len(dates),None,None,None,None,
        stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
combos=[(v,q,g,100-v-q-g) for v in range(0,45,5) for q in range(0,45,5) for g in range(10,75,5) if 10<=100-v-q-g<=60]
CONFIGS=[('state','annual(현행)'),('_sp3','균등TTM')]
results={}
for folder,lbl in CONFIGS:
    if not glob.glob(os.path.join(PROJ,folder,'ranking_*.json')):
        print(f'[{lbl}] {folder} 없음 — 스킵'); continue
    ar,dates=load(folder); reg=calc_reg(dates)
    print(f'\n{"="*60}\n[{lbl}] {dates[0]}~{dates[-1]} {len(dates)}일\n{"="*60}')
    for ow in [0.2,0.0]:
        t=TurboSimulator(ar,dates,prices,overheat_w=ow); t._use_overlay=True; t._use_stored_growth=True
        res=[]
        for v,q,g,m in combos:
            r=regbt(t,dates,reg,v,q,g,m); res.append((v,q,g,m,r.get('calmar',0),r.get('cagr',0)))
        res.sort(key=lambda x:-x[4]); b=res[0]
        print(f'  과열캡={ow}: 멀티팩터 best V{b[0]}Q{b[1]}G{b[2]}M{b[3]} Cal {b[4]:.3f} (CAGR {b[5]:.0f})')
        results[(folder,ow)]=(b,t,dates,reg,ar)
# 균등TTM 최고 멀티팩터 config에 진입/이탈/슬롯 스윕
print(f'\n{"="*60}\n[균등TTM] 최고 config에 진입/이탈/슬롯 풀스윕\n{"="*60}')
ttm_keys=[k for k in results if k[0]=='_sp3']
if ttm_keys:
    bestk=max(ttm_keys,key=lambda k:results[k][0][4])
    b,t,dates,reg,ar=results[bestk]
    v,q,g,m=b[:4]; ow=bestk[1]
    print(f'  기준: 균등TTM 과열캡{ow} V{v}Q{q}G{g}M{m} (멀티팩터best Cal {b[4]:.3f})')
    exs=[]
    for oe in [2,3,4]:
        for ox in [4,6,8]:
            for oss in [2,3,4]:
                r=regbt(t,dates,reg,v,q,g,m,oe,ox,oss)
                exs.append((oe,ox,oss,r.get('calmar',0),r.get('cagr',0)))
    exs.sort(key=lambda x:-x[3])
    print('  진입/이탈/슬롯 best 5:')
    for oe,ox,oss,cal,cg in exs[:5]:
        print(f'    E{oe}X{ox}S{oss}: Cal {cal:.3f} (CAGR {cg:.0f})')
    ttm_final=exs[0][3]
else:
    ttm_final=0
# 연도별 (best config)
print(f'\n{"="*60}\n결론\n{"="*60}')
print(f'  annual 현행 baseline: Cal 3.79 (과열캡0.2 V15Q0G55M30 E3X6S3)')
ann=[results[k][0][4] for k in results if k[0]=='state']
print(f'  annual 재최적 best(멀티팩터): {max(ann):.3f}' if ann else '')
ttm=[results[k][0][4] for k in results if k[0]=='_sp3']
print(f'  균등TTM 멀티팩터 best: {max(ttm):.3f}' if ttm else '')
print(f'  균등TTM 진입/이탈/슬롯까지 최적화: {ttm_final:.3f}')
print(f'  → 균등TTM 완전최적 {ttm_final:.3f} vs annual baseline 3.79: {"★TTM 승리!" if ttm_final>3.79 else "annual 유지"}')
