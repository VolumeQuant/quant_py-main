# -*- coding: utf-8 -*-
"""일회성 이익 탐지 지표 표본 EDA — 스캠의심(삼지전자/에스에이엠티) vs winner(SK하이닉스/제룡전기).
지표 A: 순이익/영업이익(TTM)  B: accruals=(순이익-CFO)/자산(TTM)  C: max분기OP/TTM OP.
출력은 ASCII만(콘솔 cp949 회피). 계정명 매칭만 한글 literal.
"""
import pandas as pd, os
CACHE='C:/dev/data_cache'
OP='영업이익'; NI='당기순이익'; CFO='영업활동으로인한현금흐름'; AST='자산'; REV='매출액'
NAMES={'037460':'SAMJI(samji)','031330':'SAMT(esamt)','000660':'SKHYNIX(win)','033100':'JERYONG(win)','112610':'CSWIND(win)'}
def load(tk):
    f=f'{CACHE}/fs_dart_{tk}.parquet'
    if not os.path.exists(f): return None
    df=pd.read_parquet(f)
    df.columns=['acct','date','val','tk','q','rcept','fsdiv']
    df=df[df['q']=='q']
    piv=df.pivot_table(index='date',columns='acct',values='val',aggfunc='last').sort_index()
    return piv
def ttm(s):
    s=s.dropna()
    return s.iloc[-4:].sum() if len(s)>=4 else None
for tk,nm in NAMES.items():
    piv=load(tk)
    if piv is None: print(f'\n{tk} {nm}: NO FILE'); continue
    print(f'\n===== {tk} {nm} =====')
    cols=[c for c in [OP,NI,CFO,AST,REV] if c in piv.columns]
    sub=piv[cols].dropna(how='all').tail(9)
    # 최근 8분기 OP/NI/CFO 시계열(단위 억 추정)
    print('quarter   '+'  '.join(f'{c[:3]:>10}' for c in ['OP','NI','CFO','REV']))
    for d,row in sub.iterrows():
        def g(c):
            v=row.get(c); return f'{v:>10.0f}' if pd.notna(v) else f'{"-":>10}'
        print(f'{str(d)[:7]}  '+'  '.join(g(c) for c in [OP,NI,CFO,REV]))
    # 지표 (최근 8분기 기준)
    op=piv[OP].dropna() if OP in piv else pd.Series(dtype=float)
    ni=piv[NI].dropna() if NI in piv else pd.Series(dtype=float)
    cf=piv[CFO].dropna() if CFO in piv else pd.Series(dtype=float)
    ast=piv[AST].dropna() if AST in piv else pd.Series(dtype=float)
    op_ttm=ttm(op); ni_ttm=ttm(ni); cf_ttm=ttm(cf)
    last_ast=ast.iloc[-1] if len(ast) else None
    A=ni_ttm/op_ttm if op_ttm and op_ttm>0 else None
    B=(ni_ttm-cf_ttm)/last_ast*100 if (ni_ttm is not None and cf_ttm is not None and last_ast) else None
    C=(op.iloc[-4:].max()/op_ttm) if (op_ttm and op_ttm>0 and len(op)>=4) else None
    def fmt(x): return f'{x:.2f}' if x is not None else 'NA'
    print(f'  [A] NI/OP (TTM)            = {fmt(A)}   (>1.3 의심: 영업외 일회성)')
    print(f'  [B] accruals (NI-CFO)/asset= {fmt(B)}%  (높을수록 이익質 낮음/비현금)')
    print(f'  [C] maxQ_OP / TTM_OP       = {fmt(C)}   (>0.5 한분기 쏠림=일회성)')
