# -*- coding: utf-8 -*-
"""forward PER 스위트스팟 EDA (2026-06-30) — 커버 유니버스(487).
forward PER 레벨 & (fwd_per/per)배수별 forward 수익률 + 2D 그리드.
★look-ahead 프록시: forward EPS = 실제 t+250일 TTM지배순이익(컨센 히스토리無, 확신가중 BT와 동일·상한)."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
PROJ='C:/dev'
cov=json.load(open(PROJ+'/kr_eps_momentum/fusion_covered_universe.json',encoding='utf-8'))['covered']
px=pd.read_parquet(sorted(glob.glob(PROJ+'/data_cache/all_ohlcv_2017*_20260*.parquet'))[-1]).replace(0,np.nan)
tdays=px.index  # 거래일
di={d.strftime('%Y%m%d'):i for i,d in enumerate(tdays)}
pcol={c:j for j,c in enumerate(px.columns)}; parr=px.values
# 시총 파일 인덱스
mcf={os.path.basename(f).split('_')[-1][:8]:f for f in glob.glob(PROJ+'/data_cache/market_cap_ALL_*.parquet')}
mcdates=sorted(mcf)
def mc_on(d8):
    cand=[x for x in mcdates if x<=d8]
    if not cand: return None
    return pd.read_parquet(mcf[cand[-1]])
# TTM 지배순이익 PIT
ttm={}
for t in cov:
    fp=PROJ+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(fp): continue
    df=pd.read_parquet(fp)
    s=df[df['계정']=='지배주주당기순이익']
    if s.empty: s=df[df['계정']=='당기순이익']
    if s.empty: continue
    g=s.groupby('기준일').agg(v=('값','last'),rc=('rcept_dt','last')).reset_index().sort_values('기준일')
    g['rc']=pd.to_datetime(g['rc']).dt.strftime('%Y%m%d')
    ttm[t]=g
def ttm_at(t,d8):
    g=ttm.get(t)
    if g is None: return None
    a=g[g['rc']<=d8]
    if len(a)<4: return None
    last4=a.tail(4)['v'].values
    return float(last4.sum())  # 억원
def price_ret(t,i0,h):
    j=pcol.get(t)
    if j is None or i0+h>=len(parr): return None
    p0=parr[i0,j]; p1=parr[i0+h,j]
    return p1/p0-1 if (p0>0 and p1>0) else None
# 월별 샘플 (매월 첫 거래일)
sample=[]
seen=set()
for i,d in enumerate(tdays):
    ym=d.strftime('%Y%m')
    if ym not in seen and '201901'<=ym<='202506':
        seen.add(ym); sample.append((i,d.strftime('%Y%m%d')))
rows=[]
for i0,d8 in sample:
    mc=mc_on(d8)
    if mc is None: continue
    cap=mc['시가총액'] if '시가총액' in mc.columns else None
    if cap is None: continue
    # t+250 거래일 날짜
    if i0+250>=len(tdays): continue
    df8=tdays[i0+250].strftime('%Y%m%d')
    for t in cov:
        if t not in cap.index: continue
        capv=float(cap.loc[t])/1e8  # 억원
        tt=ttm_at(t,d8); ttf=ttm_at(t,df8)
        if not tt or not ttf or tt<=0 or ttf<=0 or capv<=0: continue
        per=capv/tt; fper=capv/ttf
        ratio=fper/per  # = tt/ttf = 1/기대성장
        r250=price_ret(t,i0,250); r120=price_ret(t,i0,120)
        if r250 is None: continue
        rows.append((d8,t,per,fper,ratio,r250,r120))
D=pd.DataFrame(rows,columns=['date','tk','per','fper','ratio','r250','r120'])
print(f"표본 {len(D)} (월{len(sample)}×커버, look-ahead 프록시 forward PER)\n")
def show(col,bins,labels,name):
    D['_b']=pd.cut(D[col],bins=bins,labels=labels)
    g=D.groupby('_b',observed=True)['r250']
    print(f"[{name}별 forward 250일 수익률]")
    for lb in labels:
        v=D[D['_b']==lb]['r250']
        if len(v): print(f"  {str(lb):<12} n={len(v):>5} 평균{v.mean()*100:+6.1f}% 승률{(v>0).mean()*100:4.0f}% 중앙{v.median()*100:+6.1f}%")
    print()
show('fper',[0,5,10,15,20,25,30,40,1e9],['<5','5-10','10-15','15-20','20-25','25-30','30-40','>40'],'① forward PER 절대값')
show('ratio',[0,0.4,0.6,0.8,1.0,1.3,1.7,1e9],['<0.4(성장↑)','0.4-0.6','0.6-0.8','0.8-1.0','1.0-1.3','1.3-1.7','>1.7(역성장)'],'② fwd_per/per 배수')
# 2D 그리드 (forward PER × ratio) 평균 r250
print("[③ 2D 그리드: forward PER(행) × fwd_per/per(열) — 평균 250일 수익률%, n]")
fb=[0,10,15,20,30,1e9]; fl=['<10','10-15','15-20','20-30','>30']
rb=[0,0.6,0.85,1.0,1e9]; rl=['<0.6','0.6-0.85','0.85-1.0','>1.0']
D['fb']=pd.cut(D['fper'],fb,labels=fl); D['rb']=pd.cut(D['ratio'],rb,labels=rl)
print('  fPER/ratio  '+' '.join(f'{x:>11}' for x in rl))
for f in fl:
    cells=[]
    for r in rl:
        v=D[(D['fb']==f)&(D['rb']==r)]['r250']
        cells.append((f'{v.mean()*100:+.0f}%(n{len(v)})' if len(v)>=10 else '-'))
    print(f'  {f:<10} '+' '.join(f'{c:>11}' for c in cells))
# ④ 극단 저점 정밀 — 너무 낮으면 U자(나빠짐)인가? 승률·중앙 우선(평균은 outlier 왜곡)
print("\n[④ 극단 저점 정밀 — forward PER 저구간]")
show('fper',[0,1,2,3,5,7,10],['<1','1-2','2-3','3-5','5-7','7-10'],'forward PER 저구간')
print("[④ 극단 저점 정밀 — 배수 저구간]")
show('ratio',[0,0.1,0.2,0.3,0.4,0.6],['<0.1','0.1-0.2','0.2-0.3','0.3-0.4','0.4-0.6'],'배수 저구간')
print("\n[완료]")
