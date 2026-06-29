# -*- coding: utf-8 -*-
"""기대성장 sleeve vs production 수익률 대결 (6/1~6/24, NTM 겹치는 구간). ★15일·하락장, 방향성만."""
import sqlite3, sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)}
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
START,END='20260601','20260624'
def ret(tk,d0,d1):
    if tk not in pcol or d0 not in pdi or d1 not in pdi: return None
    p0,p1=parr[pdi[d0],pcol[tk]],parr[pdi[d1],pcol[tk]]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
def ttm_eps(tk6):
    p=P+f'/data_cache/fs_dart_{tk6}.parquet'
    if not os.path.exists(p) or tk6 not in mc.index: return None
    fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    q=fs[(fs['공시구분']=='q')&(fs['계정']=='지배주주당기순이익')&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
    v=q['값'].astype(float).values
    if len(v)<4: return None
    sh=mc.loc[tk6,'상장주식수']; return (v[-4:].sum()*1e8)/sh if sh>0 else None
# === 기대성장 sleeve: 6/1 top15 buy&hold ===
c=sqlite3.connect(P+'/kr_eps_momentum/eps_momentum_data_kr.db')
d0=sorted(r[0] for r in c.execute("SELECT DISTINCT date FROM ntm_screening WHERE date>='2026-06-01'"))[0]
df=pd.read_sql(f"SELECT ticker,ntm_current FROM ntm_screening WHERE date='{d0}'",c)
df['tk6']=df['ticker'].str[:6]
rows=[]
for _,r in df.iterrows():
    if not r['ntm_current'] or r['ntm_current']<=0: continue
    te=ttm_eps(r['tk6'])
    if te and te>0: rows.append((r['tk6'],r['ntm_current']/te))
g=pd.DataFrame(rows,columns=['tk6','gap']); g=g[g['gap']<15].sort_values('gap',ascending=False).head(15)
sret=[ret(t,d0.replace('-',''),END) for t in g['tk6']]; sret=[x for x in sret if x is not None]
print(f"기대성장 sleeve (6/1 top15 buy&hold): n={len(sret)} 평균 {np.mean(sret):+.1f}% (중앙 {np.median(sret):+.1f}%)")
# === production: TurboSim 6/1~6/24 ===
ar={};dates=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dates.append(dt)
dates=sorted(dates)
def reg_s(ds):
    reg={};md=True;stk=0;ss=None
    for dd in ds:
        ts=pd.Timestamp(dd[:4]+'-'+dd[4:6]+'-'+dd[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[dd]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[dd]=md
    return reg
reg=reg_s(dates)
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50: s2.loc[s2.index<d]*=f
    return s2
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
t=TurboSimulator({d:ar[d] for d in dates},dates,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
for d in dates:
    tkn=t._preextracted[d][0];fd={x['ticker']:x for x in ar[d]}
    t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
t._cached_key=None;t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,dates,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(dates),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
dr=r['_daily_rets']
idx=[i for i,d in enumerate(dates) if START<=d<=END]
prod=(np.prod([1+dr[i] for i in idx])-1)*100
reg_win=set(reg[dates[i]] for i in idx)
print(f"production 메인 (rank<=3, 6/1~6/24): {prod:+.1f}%  (국면: {'boost' if True in reg_win else ''}{'/defense' if False in reg_win else ''})")
kret=(kc[pd.Timestamp('2026-06-24')]/kc[pd.Timestamp('2026-06-01')]-1)*100
print(f"코스피: {kret:+.1f}%")

# === REVISION 신호 top15 (대조) ===
df2=pd.read_sql(f"SELECT ticker,ntm_current,ntm_30d,score FROM ntm_screening WHERE date='{d0}'",c)
df2['tk6']=df2['ticker'].str[:6]
df2['rev']=np.where((df2['ntm_30d']>0)&(df2['ntm_current']>0),(df2['ntm_current']/df2['ntm_30d']-1)*100,np.nan)
for sig,nm2 in [('rev','REVISION(추정상향)'),('score','시스템 score')]:
    gg=df2.dropna(subset=[sig]).sort_values(sig,ascending=False).head(15)
    rr=[ret(t,d0.replace('-',''),END) for t in gg['tk6']]; rr=[x for x in rr if x is not None]
    print(f"{nm2} top15 buy&hold: n={len(rr)} 평균 {np.mean(rr):+.1f}% (중앙 {np.median(rr):+.1f}%)")
