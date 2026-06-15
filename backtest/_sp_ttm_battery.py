# -*- coding: utf-8 -*-
"""TTM 종합 battery (2026-06-15): annual(state) vs 완전TTM(_sp2),
과열캡 가중치 스윕(0.0~0.3) × 멀티팩터 풀그리드 재최적 × 연도별 × 인접CV.
질문: TTM이 baseline(annual+과열0.2=3.59)을 이기는 config가 단 하나라도 있나?
usage: python backtest/_sp_ttm_battery.py"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
class _Tee:
    def __init__(self, *fs): self.fs = fs
    def write(self, x):
        for f in self.fs:
            try: f.write(x); f.flush()
            except Exception: pass
    def flush(self):
        for f in self.fs:
            try: f.flush()
            except Exception: pass
_rf = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_sp_ttm_battery_result.txt'), 'w', encoding='utf-8')
sys.stdout = _Tee(sys.stdout, _rf)
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_*_2026061*.parquet')))[0]).replace(0,np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
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
def regbt(tsim,dates,reg,v,q,g,m):
    tsim._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(tsim._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,dates,tsim._price_arr,tsim._bench_arr,
        tsim._has_bench,tsim._date_row_indices,len(dates),None,None,None,None,
        stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
combos=[(v,q,g,100-v-q-g) for v in range(0,45,5) for q in range(0,45,5) for g in range(10,75,5) if 10<=100-v-q-g<=60]
YEARS=['2019','2020','2021','2022','2023','2024','2025','2026']
RL={'2019':'회복','2020':'코로나','2021':'강세','2022':'약세','2023':'회복','2024':'강세','2025':'강세','2026':'초강세'}
CONFIGS=[('state','annual(현행)'),('_sp2','완전TTM')]
OWS=[0.2,0.0]  # 결정적 비교: 현행 vs 과열캡OFF (0.1/0.3은 0.0 유망 시 추가)
best_overall=('',-1)
for folder,lbl in CONFIGS:
    if not glob.glob(os.path.join(PROJ,folder,'ranking_*.json')):
        print(f'[{lbl}] 폴더 {folder} 없음 — 스킵'); continue
    ar,dates=load(folder); reg=calc_reg(dates)
    print(f'\n{"="*64}\n[{lbl}] {dates[0]}~{dates[-1]} {len(dates)}일\n{"="*64}')
    for ow in OWS:
        tsim=TurboSimulator(ar,dates,prices,overheat_w=ow); tsim._use_overlay=True; tsim._use_stored_growth=True
        prod=regbt(tsim,dates,reg,15,0,55,30)
        res=[]
        for v,q,g,m in combos:
            r=regbt(tsim,dates,reg,v,q,g,m)
            res.append((v,q,g,m,r.get('calmar',0),r.get('cagr',0)))
        res.sort(key=lambda x:-x[4])
        b=res[0]
        # 인접 CV
        bv,bq,bg=b[0],b[1],b[2]
        adj=[regbt(tsim,dates,reg,max(0,bv+dv),max(0,bq+dq),bg,100-max(0,bv+dv)-max(0,bq+dq)-bg).get('calmar',0)
             for dv in(-5,0,5) for dq in(-5,0,5) if 10<=100-max(0,bv+dv)-max(0,bq+dq)-bg<=60]
        adj=[a for a in adj if a>0]; cv=np.std(adj)/np.mean(adj) if len(adj)>2 else 0
        tag=' ★현행baseline' if (folder=='state' and ow==0.2) else ''
        print(f'  과열캡={ow}: prod V15Q0G55M30 Cal {prod["calmar"]:.3f} | 재최적 V{b[0]}Q{b[1]}G{b[2]}M{b[3]} Cal {b[4]:.3f} (CAGR {b[5]:.0f}) 인접CV {cv:.3f}{tag}')
        if b[4]>best_overall[1]: best_overall=(f'{lbl} 과열{ow} V{b[0]}Q{b[1]}G{b[2]}M{b[3]}',b[4])
# 연도별 (각 folder 최적 과열·config는 위 표 참조, 여기선 production config로 WF)
print(f'\n{"="*64}\n연도별 production-config CAGR (과열0.2)\n{"="*64}')
print(f"{'config':<14}"+''.join(f'{y[2:]}({RL[y]})'.rjust(12) for y in YEARS))
for folder,lbl in CONFIGS:
    if not glob.glob(os.path.join(PROJ,folder,'ranking_*.json')): continue
    ar,dates=load(folder); row=f'{lbl:<14}'
    for y in YEARS:
        ds=[d for d in dates if d[:4]==y]
        if len(ds)<20: row+='n/a'.rjust(12); continue
        sim=TurboSimulator({d:ar[d] for d in ds},sorted(ds),prices); sim._use_overlay=True; sim._use_stored_growth=True
        r=regbt(sim,sorted(ds),calc_reg(sorted(ds)),15,0,55,30)
        row+=f"{r.get('cagr',0):>+8.0f}%".rjust(12)
    print(row)
print(f'\n{"="*64}')
print(f'★ 전체 최고 config: {best_overall[0]} = Cal {best_overall[1]:.3f}')
print(f'   (annual+과열0.2 baseline 3.59를 넘는 TTM config가 있으면 그게 결론)')
