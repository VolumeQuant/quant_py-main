# -*- coding: utf-8 -*-
"""일회성 필터 전체분포 + winner 충돌 체크.
B=accruals=(NI-CFO)/asset(TTM)%, C=maxQ_OP/TTM_OP. winner=12M 주가상승 상위20%.
질문: B&C 결합컷이 스캠을 잡으면서 winner는 안 죽이나? 출력 ASCII.
주의: 현재시점 TTM/return = look-ahead(1차 스크리닝용). 실검증은 BT.
"""
import pandas as pd, numpy as np, glob, os
CACHE='C:/dev/data_cache'
OP='영업이익'; NI='당기순이익'; CFO='영업활동으로인한현금흐름'; AST='자산'
def metrics(tk):
    f=f'{CACHE}/fs_dart_{tk}.parquet'
    try: raw=pd.read_parquet(f)
    except: return None
    if raw.shape[1]<5: return None
    # 첫 3개 고정: 계정/날짜/값. q플래그=뒤쪽 컬럼 중 'q' 값 가진 것
    acct=raw.iloc[:,0]; date=raw.iloc[:,1]; val=raw.iloc[:,2]
    qcol=None
    for j in range(3,raw.shape[1]):
        u=raw.iloc[:,j].astype(str)
        if u.isin(['q','y','a','h']).any() and raw.iloc[:,j].nunique()<8: qcol=raw.iloc[:,j]; break
    if qcol is None: return None
    df=pd.DataFrame({'acct':acct.values,'date':date.values,'val':val.values,'q':qcol.values})
    df=df[df['q']=='q']
    if df.empty: return None
    piv=df.pivot_table(index='date',columns='acct',values='val',aggfunc='last').sort_index()
    if OP not in piv or NI not in piv: return None
    op=piv[OP].dropna(); ni=piv[NI].dropna()
    cf=piv[CFO].dropna() if CFO in piv else pd.Series(dtype=float)
    ast=piv[AST].dropna() if AST in piv else pd.Series(dtype=float)
    if len(op)<8 or len(ni)<4 or len(cf)<4 or len(ast)<1: return None
    op_ttm=op.iloc[-4:].sum(); ni_ttm=ni.iloc[-4:].sum(); cf_ttm=cf.iloc[-4:].sum()
    if op_ttm<=0: return None  # 흑자(양수 TTM)만 — 스캠은 양수로 꼬심
    B=(ni_ttm-cf_ttm)/ast.iloc[-1]*100
    C=op.iloc[-4:].max()/op_ttm
    return dict(B=B,C=C,op_ttm=op_ttm)

# OHLCV → 12M return
ohf=sorted(glob.glob(f'{CACHE}/all_ohlcv_*.parquet'))[-1]
oh=pd.read_parquet(ohf)
print('OHLCV shape',oh.shape,'idx',type(oh.index).__name__,'cols sample',list(oh.columns)[:3])
# 구조 추정: index=date, columns=ticker (close)
def ret12(tk):
    if tk not in oh.columns: return None
    s=oh[tk].dropna()
    if len(s)<240: return None
    return s.iloc[-1]/s.iloc[-240]-1

tickers=[os.path.basename(f).replace('fs_dart_','').replace('.parquet','') for f in glob.glob(f'{CACHE}/fs_dart_*.parquet')]
rows=[]
for tk in tickers:
    m=metrics(tk)
    if not m: continue
    r=ret12(tk)
    rows.append(dict(tk=tk,B=m['B'],C=m['C'],ret=r))
df=pd.DataFrame(rows)
print(f'\n유효 종목: {len(df)} (흑자 TTM + 8분기+ 재무)')
print('\n=== B(accruals%) 분포 ===')
print(df['B'].describe(percentiles=[.5,.75,.9,.95,.99]).round(1).to_string())
print('\n=== C(분기쏠림) 분포 ===')
print(df['C'].describe(percentiles=[.5,.75,.9,.95,.99]).round(2).to_string())

# 삼지/에스에이엠티 위치
for tk,nm in [('037460','SAMJI'),('031330','SAMT')]:
    row=df[df.tk==tk]
    if len(row):
        b=row.B.iloc[0]; c=row.C.iloc[0]
        bp=(df.B<b).mean()*100; cp=(df.C<c).mean()*100
        print(f'{nm}({tk}): B={b:.1f}(상위{100-bp:.0f}%) C={c:.2f}(상위{100-cp:.0f}%)')

# winner = 12M ret 상위 20%
dfr=df.dropna(subset=['ret'])
thr=dfr['ret'].quantile(0.80)
dfr=dfr.assign(winner=dfr['ret']>=thr)
print(f'\nwinner 정의: 12M수익 상위20% (>={thr*100:.0f}%), n={dfr.winner.sum()} / 전체 {len(dfr)}')

print('\n=== 결합컷 후보별: 전체 걸림율 vs winner 걸림율 (winner 학살 체크) ===')
print(f'{"rule":<26}{"flag전체%":>9}{"flag수":>7}{"flagWinner%":>12}{"WinnerLoss":>11}')
for bT,cT in [(10,0.5),(15,0.55),(15,0.6),(20,0.6),(20,0.65),(25,0.7)]:
    flag=(dfr.B>bT)&(dfr.C>cT)
    overall=flag.mean()*100
    n=int(flag.sum())
    wl=(flag & dfr.winner).sum()/dfr.winner.sum()*100  # winner 중 걸리는 비율
    # 걸린 것 중 winner 비율
    samji_ok='Y' if ((df[df.tk=='037460'].B.iloc[0]>bT) and (df[df.tk=='037460'].C.iloc[0]>cT)) else 'N'
    samt_ok='Y' if ((df[df.tk=='031330'].B.iloc[0]>bT) and (df[df.tk=='031330'].C.iloc[0]>cT)) else 'N'
    print(f'B>{bT} & C>{cT:<7}{overall:>9.1f}{n:>7}{wl:>12.1f}   SAMJI={samji_ok} SAMT={samt_ok}')
print('\n해석: winner걸림율 << 전체걸림율 이면 타깃팅 양호. winner걸림율 높으면 위험(winner 학살).')
