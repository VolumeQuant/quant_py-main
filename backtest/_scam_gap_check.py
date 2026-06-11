# -*- coding: utf-8 -*-
"""뻥튀기 의심주가 v80.25(B>25&C>0.7)를 빠져나가는지 + 품질바닥 후보 진단.
_oneoff_eda.py 재사용. 출력 ASCII."""
import pandas as pd, os
CACHE='C:/dev/data_cache'
OP='영업이익'; NI='당기순이익'; CFO='영업활동으로인한현금흐름'; AST='자산'; REV='매출액'; EQ='자본'
NAMES={
 '008060':'DAEDUK #7  (PER178/ROE0.6 의심)',
 '043260':'SUNGHO #11 (mom2.4/PBR11.8)',
 '356860':'TLB #10    (무->10 급상승)',
 '452280':'HANSUN #12 (무->12 급상승)',
 '307930':'COMPANYK #20(무->20)',
 '031330':'ESAMT (이미 스캠판정)',
 '037460':'SAMJI (이미 스캠판정)',
 '000660':'SKHYNIX (winner-보존돼야)',
 '080220':'JEJU반도체 (winner-보존돼야)',
}
def load(tk):
    f=f'{CACHE}/fs_dart_{tk}.parquet'
    if not os.path.exists(f): return None
    df=pd.read_parquet(f)
    c=list(df.columns)  # [계정, 기준일, 값, 종목코드, 공시구분, rcept_dt, (fs_div)]
    acct,date,val,q=c[0],c[1],c[2],c[4]
    df=df[df[q]=='q']
    return df.pivot_table(index=date,columns=acct,values=val,aggfunc='last').sort_index()
def ttm(s):
    s=s.dropna(); return s.iloc[-4:].sum() if len(s)>=4 else None
print(f'{"종목":<26}{"opTTM":>9}{"opMgn%":>8}{"ROE%":>7}{"B(accr)":>9}{"C(쏠림)":>8}  v80.25?')
print('-'*80)
for tk,nm in NAMES.items():
    piv=load(tk)
    if piv is None: print(f'{nm:<26} NO FILE'); continue
    def col(c): return piv[c].dropna() if c in piv else pd.Series(dtype=float)
    op,ni,cf,ast,rev,eq=col(OP),col(NI),col(CFO),col(AST),col(REV),col(EQ)
    op_ttm,ni_ttm,cf_ttm,rev_ttm=ttm(op),ttm(ni),ttm(cf),ttm(rev)
    last_ast=ast.iloc[-1] if len(ast) else None
    last_eq=eq.iloc[-1] if len(eq) else None
    B=(ni_ttm-cf_ttm)/last_ast*100 if (ni_ttm is not None and cf_ttm is not None and last_ast) else None
    C=(op.iloc[-4:].max()/op_ttm) if (op_ttm and op_ttm>0 and len(op)>=4) else None
    opmgn=op_ttm/rev_ttm*100 if (op_ttm is not None and rev_ttm) else None
    roe=ni_ttm/last_eq*100 if (ni_ttm is not None and last_eq) else None
    trig = 'YES(걸림)' if (B is not None and C is not None and B>25 and C>0.7) else 'NO(빠져나감)'
    f=lambda x,d=1: (f'{x:.{d}f}' if x is not None else 'NA')
    print(f'{nm:<26}{f(op_ttm,0):>9}{f(opmgn):>8}{f(roe):>7}{f(B):>9}{f(C,2):>8}  {trig}')
