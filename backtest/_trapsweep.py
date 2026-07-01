# -*- coding: utf-8 -*-
"""트랩 시그니처 전수 스윕 — 15개 펀더 지표 × 매수권 forward수익률. 깨끗한 음수꼬리 찾기."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
PROJ='C:/dev'
days={};dall=[]
for f in sorted(glob.glob(PROJ+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        days[dt]={r['ticker']:r for r in json.load(open(f,encoding='utf-8'))['rankings']};dall.append(dt)
dall=sorted(dall)
px=pd.read_parquet(sorted(glob.glob(PROJ+'/data_cache/all_ohlcv_2017*_20260*.parquet'))[-1]).replace(0,np.nan)
di={d:i for i,d in enumerate(px.index.strftime('%Y%m%d'))};pc={c:j for j,c in enumerate(px.columns)};pa=px.values
def fwd(tk,d,h=60):
    i=di.get(d);j=pc.get(tk)
    if i is None or j is None or i+h>=len(pa):return None
    p0=pa[i,j];p1=pa[i+h,j];return p1/p0-1 if(p0>0 and p1>0)else None
METRICS=['net_margin','op_margin','gross_margin','roe','roa','accruals_B','cfo_ni','asset_grow','debt_ratio','curr_ratio','ni_conc','rev_conc','tax_rate','op_pretax','equity_grow']
sig={}  # t -> (rc_array, {metric: array})
tk_all=set()
for d in dall: tk_all|=set(days[d])
for t in tk_all:
    fp=PROJ+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(fp):continue
    df=pd.read_parquet(fp)
    A={}
    for nm in ['매출액','매출총이익','영업이익','당기순이익','지배주주당기순이익','영업활동으로인한현금흐름','자산','부채','자본','지배주주자본','유동자산','유동부채','세전계속사업이익','법인세비용']:
        s=df[df['계정']==nm]
        if s.empty:continue
        g=s.groupby('기준일').agg(v=('값','last'),rc=('rcept_dt','last')).reset_index().sort_values('기준일')
        g['rc']=pd.to_datetime(g['rc']).dt.strftime('%Y%m%d');A[nm]=g
    if '매출액' not in A or '지배주주당기순이익' not in A and '당기순이익' not in A:continue
    base=A['매출액'][['기준일','rc']]
    M=base.copy()
    for nm,g in A.items(): M=M.merge(g[['기준일','v']].rename(columns={'v':nm}),on='기준일',how='left')
    M=M.sort_values('기준일').reset_index(drop=True)
    if len(M)<5:continue
    ni=M['지배주주당기순이익'].fillna(M.get('당기순이익')) if '지배주주당기순이익' in M else M['당기순이익']
    def ttm(col): return M[col].rolling(4).sum() if col in M else pd.Series([np.nan]*len(M))
    rev_t=ttm('매출액');ni_t=ni.rolling(4).sum();op_t=ttm('영업이익');gp_t=ttm('매출총이익')
    cfo_t=ttm('영업활동으로인한현금흐름');pt_t=ttm('세전계속사업이익');tax_t=ttm('법인세비용')
    out={}
    out['net_margin']=(ni_t/rev_t*100).values
    out['op_margin']=(op_t/rev_t*100).values
    out['gross_margin']=(gp_t/rev_t*100).values
    out['roe']=(ni_t/M.get('지배주주자본',M.get('자본'))*100).values if '지배주주자본' in M or '자본' in M else np.full(len(M),np.nan)
    out['roa']=(ni_t/M['자산']*100).values if '자산' in M else np.full(len(M),np.nan)
    out['accruals_B']=((ni_t-cfo_t)/M['자산']*100).values if '자산' in M else np.full(len(M),np.nan)
    out['cfo_ni']=(cfo_t/ni_t).values
    out['asset_grow']=(M['자산']/M['자산'].shift(4)-1).values if '자산' in M else np.full(len(M),np.nan)
    out['debt_ratio']=(M['부채']/M['자본']).values if '부채' in M and '자본' in M else np.full(len(M),np.nan)
    out['curr_ratio']=(M['유동자산']/M['유동부채']).values if '유동자산' in M and '유동부채' in M else np.full(len(M),np.nan)
    out['ni_conc']=(ni.rolling(4).max()/ni_t).values
    out['rev_conc']=(M['매출액'].rolling(4).max()/rev_t).values
    out['tax_rate']=(tax_t/pt_t*100).values
    out['op_pretax']=(op_t/pt_t).values
    out['equity_grow']=(M.get('자본',M.get('지배주주자본'))/M.get('자본',M.get('지배주주자본')).shift(4)-1).values if '자본' in M else np.full(len(M),np.nan)
    sig[t]=(M['rc'].values,out)
def at(t,d8,met):
    x=sig.get(t)
    if x is None:return None
    rcs,out=x;k=np.searchsorted(rcs,d8,'right')-1
    if k<0 or met not in out:return None
    v=out[met][k];return float(v) if v==v and abs(v)<1e6 else None
# 매수권(rank<=6) 수집
COH=[]
for d in dall:
    for tk,r in days[d].items():
        if r.get('rank',99)>6:continue
        fr=fwd(tk,d)
        if fr is None:continue
        row={'fr':fr}
        for m in METRICS: row[m]=at(tk,d,m)
        COH.append(row)
D=pd.DataFrame(COH)
print(f"매수권 표본 {len(D)} | 전체 fwd60 평균 {D['fr'].mean()*100:+.1f}% 중앙 {D['fr'].median()*100:+.1f}%\n")
print(f"{'지표':<13}{'최악꼬리(Q1/Q5)':>16}{'n':>5}{'평균%':>7}{'승률':>6}{'중앙%':>7}  vs 나머지중앙")
res=[]
for m in METRICS:
    s=D[D[m].notna()]
    if len(s)<200:continue
    q1=s[m].quantile(0.2); q5=s[m].quantile(0.8)
    lo=s[s[m]<=q1]['fr']; hi=s[s[m]>=q5]['fr']
    # 더 나쁜 꼬리 선택
    if lo.median()<hi.median(): tail,nm='하위20%',lo
    else: tail,nm='상위20%',hi
    rest=s[~s.index.isin(s[s[m]<=q1].index if tail=='하위20%' else s[s[m]>=q5].index)]['fr']
    res.append((m,tail,len(nm),nm.mean(),(nm>0).mean(),nm.median(),rest.median()))
for m,tail,n,mn,wr,md,restmd in sorted(res,key=lambda x:x[5]):
    flag=' ★깨끗한음수' if (md<-0.05 and wr<0.40 and n>100) else ''
    print(f"{m:<13}{tail:>16}{n:>5}{mn*100:>+7.1f}{wr*100:>5.0f}%{md*100:>+7.1f}  (나머지{restmd*100:+.1f}){flag}")
print("\n[완료]")
