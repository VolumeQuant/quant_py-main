# -*- coding: utf-8 -*-
"""③ corp-OFF baseline에서 oneoff·vtrap 재검증 (전문가 지적: all-ON 1.74 기준 평가는 초가법성으로 무효).
corp-OFF 고정, 4코너: both ON(_sp0b_co) / oneoff OFF(_sp0b_co_oo) / vtrap OFF(_sp0b_co_vo) / both OFF(_sp0b_none).
고정 config V15Q0G55M30 12m E3X6S3 + WF 3블록. 각 필터 제거가 corp-OFF서 +면 유익(유지), -면 무익."""
import sys, io, os, glob, json
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
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
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
def load(folder):
    ar,dates={}, []
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
    return ar,sorted(dates)
F={'both ON (_sp0b_co)':'_sp0b_co','oneoff OFF':'_sp0b_co_oo','vtrap OFF':'_sp0b_co_vo','both OFF (_sp0b_none)':'_sp0b_none'}
L={}
for lbl,fld in F.items():
    if os.path.isdir(os.path.join(PROJ,fld)): L[lbl]=load(fld)
    else: print(f"[skip] {lbl} 없음")
common=sorted(set.intersection(*[set(d) for _,d in L.values()])); reg=calc_reg(common)
def cal(ar, sub):
    t=TurboSimulator({d:ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
print(f"[{common[0]}~{common[-1]} {len(common)}일] corp-OFF baseline 4코너")
blocks=[('전체',common),('19-21',[d for d in common if d<'20220101']),('22-23',[d for d in common if '20220101'<=d<'20240101']),('24-26',[d for d in common if d>='20240101'])]
print(f"\n{'코너':<22}{'전체':>8}{'19-21':>8}{'22-23':>8}{'24-26':>8}")
res={}
for lbl,(ar,_) in L.items():
    vals=[cal(ar,sub) for _,sub in blocks]; res[lbl]=vals[0]
    print(f"{lbl:<22}"+"".join(f"{v:>8.2f}" for v in vals))
b=res.get('both ON (_sp0b_co)')
print(f"\n=== corp-OFF에서 각 필터 제거 효과 (vs both ON {b:.3f}) ===")
if 'oneoff OFF' in res: print(f"  oneoff 제거: {res['oneoff OFF']:.3f}  (Δ {res['oneoff OFF']-b:+.3f}) → −면 oneoff 유익(유지), +면 무익")
if 'vtrap OFF' in res: print(f"  vtrap 제거 : {res['vtrap OFF']:.3f}  (Δ {res['vtrap OFF']-b:+.3f}) → −면 vtrap 유익(유지), +면 무익")
print(f"\n→ noise ±0.3~0.5 감안. 일관 −(제거가 손해)면 유지, 명확 +(제거가 이득)면 제거 검토.")
