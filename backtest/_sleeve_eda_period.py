# -*- coding: utf-8 -*-
"""forward PER 패턴 기간별 robust EDA — 강세(19-21)/약세(22-23)/최근(24-26) 각각서 단조 유지되나."""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
df=pd.read_pickle(P+'/backtest/_sleeve_eda_df.pkl').dropna(subset=['r60']).copy()
df['yr']=df['d'].str[:4].astype(int)
def period(y):
    if y<=2021: return '강세19-21'
    if y<=2023: return '약세22-23'
    return '최근24-26'
df['pd']=df['yr'].apply(period)
periods=['강세19-21','약세22-23','최근24-26']
bins=[(0,10),(10,15),(15,20),(20,30),(30,50),(50,300)]
print("【A】 fwd_per 버킷별 fwd60 수익률 — 기간별 (단조 감소가 모든 기간서 유지되나?)\n")
print(f"  {'fwd_per':<10}"+"".join(f"{p:>13}" for p in periods)+f"{'전체':>10}")
for lo,hi in bins:
    row=f"  {f'{lo}~{hi}':<10}"
    for p in periods:
        s=df[(df['pd']==p)&(df['fwdper']>=lo)&(df['fwdper']<hi)]
        row+=f"{(s['r60'].mean() if len(s)>30 else np.nan):>12.1f}%" if len(s)>30 else f"{'n<30':>13}"
    s=df[(df['fwdper']>=lo)&(df['fwdper']<hi)]; row+=f"{s['r60'].mean():>9.1f}%"
    print(row)
print("\n【B】 fwd_per<20 vs >=20 — 기간별 (Δ가 모든 기간서 양수여야 robust)")
print(f"  {'기간':<12}{'<20 fwd60':>12}{'>=20 fwd60':>12}{'Δ':>8}{'<20승률':>9}{'>=20승률':>9}")
for p in periods+['전체']:
    s=df if p=='전체' else df[df['pd']==p]
    lo=s[s['fwdper']<20]; hi=s[s['fwdper']>=20]
    print(f"  {p:<12}{lo['r60'].mean():>11.1f}%{hi['r60'].mean():>11.1f}%{lo['r60'].mean()-hi['r60'].mean():>+8.1f}{(lo['r20']>0).mean()*100:>8.0f}%{(hi['r20']>0).mean()*100:>8.0f}%")
print("\n【C】 production 보유권(rank<=3)만 — 기간별 (실제 sleeve 대상서 유지되나, 표본 작음 주의)")
print(f"  {'기간':<12}{'<20 fwd60':>12}{'>=20 fwd60':>12}{'Δ':>8}{'n<20':>7}{'n>=20':>7}")
for p in periods+['전체']:
    s=df[df['prank']<=3] if p=='전체' else df[(df['pd']==p)&(df['prank']<=3)]
    lo=s[s['fwdper']<20]; hi=s[s['fwdper']>=20]
    d=(lo['r60'].mean()-hi['r60'].mean()) if (len(lo)>0 and len(hi)>0) else np.nan
    print(f"  {p:<12}{(lo['r60'].mean() if len(lo) else np.nan):>11.1f}%{(hi['r60'].mean() if len(hi) else np.nan):>11.1f}%{d:>+8.1f}{len(lo):>7}{len(hi):>7}")
print("\n→ 【B】Δ가 세 기간 모두 양수 = robust. 한 기간만 양수 = 기간쏠림(가짜)")
