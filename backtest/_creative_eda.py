# -*- coding: utf-8 -*-
"""창의적 함정 시그니처 전수실험 — 가격미시구조+거래량+재무 20피처 vs fwd60/fwd120.
패자(eventual loser)를 가르는 비표준 시그니처 탐색. lumpiness급 발견 노림."""
import sys, io, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
vol=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_volume_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}
vcol={c:i for i,c in enumerate(vol.columns)};varr=vol.values;vdi={d.strftime('%Y%m%d'):i for i,d in enumerate(vol.index)}
df=pd.read_parquet(P+'/backtest/_trap_entries.parquet')
def pser(tk,d,n):  # 진입일까지 n일 종가
    if tk not in pcol or d not in pdi: return None
    i=pdi[d];ci=pcol[tk]
    if i-n<0: return None
    s=parr[i-n:i+1,ci]
    return s if not np.isnan(s).any() else None
def vser(tk,d,n):
    if tk not in vcol or d not in vdi: return None
    i=vdi[d];ci=vcol[tk]
    if i-n<0: return None
    s=varr[i-n:i+1,ci]; return s
def feats(tk,d):
    o={}
    s=pser(tk,d,130)
    if s is not None and len(s)>=121:
        c=s[-1]; ret=np.diff(s)/s[:-1]
        o['dpar20']=c/s[-21:].mean()-1
        o['dpar60']=c/s[-61:].mean()-1
        o['dpar120']=c/s[-121:].mean()-1
        o['pct52wh']=c/s.max()  # 1.0=52주(130일)고점
        r20=c/s[-21]-1; r40_20=s[-21]/s[-41]-1
        o['accel']=r20-r40_20
        o['ret60']=c/s[-61]-1
        o['upratio20']=(ret[-20:]>0).mean()
        o['rvol20']=ret[-20:].std()*100
        o['max1d20']=ret[-20:].max()*100
    v=vser(tk,d,100)
    s2=pser(tk,d,100)
    if v is not None and len(v)>=81 and not np.isnan(v[-80:]).all():
        v=np.nan_to_num(v,nan=0.0)
        recent=v[-20:].mean(); prior=v[-80:-20].mean()
        o['volsurge']=recent/prior if prior>0 else np.nan
        o['volcv']=v[-20:].std()/v[-20:].mean() if v[-20:].mean()>0 else np.nan
        # 거래량 추세 (최근20일 회귀 기울기 부호) — 음수=price up while vol declining 가능
        x=np.arange(20); vv=v[-20:]
        if vv.mean()>0: o['voltrend']=np.polyfit(x,vv/vv.mean(),1)[0]
        if s2 is not None and len(s2)>=21:
            ret2=np.abs(np.diff(s2[-21:]))/s2[-21:-1]
            o['amihud']=np.mean(ret2/(v[-20:]+1))*1e10  # 가격충격
        o['turnover_abs']=np.log10(recent+1)  # 거래대금 레벨(낮을수록 작전취약)
    # 재무
    p=P+f'/data_cache/fs_dart_{tk}.parquet'
    if os.path.exists(p):
        fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        def q(a):
            x=fs[(fs['공시구분']=='q')&(fs['계정']==a)&(fs['rcept_dt'].notna())&(fs['rcept_dt']<=ts)].sort_values('rcept_dt')
            return x['값'].astype(float).values
        asset=q('자산');rev=q('매출액');gp=q('매출총이익');cash=q('현금및현금성자산');cap=q('자본');debt=q('부채')
        if len(asset)>=5 and asset[-5]>0: o['asset_g']=(asset[-1]/asset[-5]-1)*100  # YoY 자산증가
        if len(cap)>=1 and len(debt)>=1 and cap[-1]>0: o['leverage']=debt[-1]/cap[-1]
        if len(gp)>=4 and len(rev)>=4 and rev[-4:].sum()>0: o['gpmargin']=gp[-4:].sum()/rev[-4:].sum()*100
        if len(cash)>=1 and len(asset)>=1 and asset[-1]>0: o['cashratio']=cash[-1]/asset[-1]*100
    return o
F=[feats(tk,d) for tk,d in zip(df['tk'],df['d'])]
fd=pd.DataFrame(F);df=pd.concat([df.reset_index(drop=True),fd],axis=1)
df.to_parquet(P+'/backtest/_creative_feats.parquet')
cols=['dpar20','dpar60','dpar120','pct52wh','accel','ret60','upratio20','rvol20','max1d20',
      'volsurge','volcv','voltrend','amihud','turnover_abs','asset_g','leverage','gpmargin','cashratio']
v=df.dropna(subset=['f60']).copy()
print(f"진입 {len(v)}건 (fwd60 평균 {v['f60'].mean():+.1f}%, 승률 {(v['f60']>0).mean()*100:.0f}%)\n")
print("=== 각 피처 극단분위(Q1/Q4) fwd60 — 분리력 순 ===")
res=[]
for c in cols:
    a=v.dropna(subset=[c])
    if len(a)<60: continue
    try: a['q']=pd.qcut(a[c],4,labels=['Q1','Q2','Q3','Q4'],duplicates='drop')
    except: continue
    g=a.groupby('q',observed=True)['f60'].agg(['mean','count'])
    win=a.groupby('q',observed=True)['f60'].apply(lambda x:(x>0).mean()*100)
    if 'Q1' in g.index and 'Q4' in g.index:
        spread=g.loc['Q4','mean']-g.loc['Q1','mean']
        res.append((c,g.loc['Q1','mean'],g.loc['Q4','mean'],win.get('Q1',0),win.get('Q4',0),abs(spread)))
res.sort(key=lambda x:-x[5])
print(f"  {'피처':12s}{'Q1평균f60':>10s}{'Q4평균f60':>10s}{'Q1승률':>8s}{'Q4승률':>8s}{'|분리|':>8s}")
for c,q1,q4,w1,w4,sp in res:
    print(f"  {c:12s}{q1:>+9.1f}%{q4:>+9.1f}%{w1:>7.0f}%{w4:>7.0f}%{sp:>7.1f}")
