# -*- coding: utf-8 -*-
"""게이트2 표본검증 — 과열캡 저점면제: TTM이익<정규화이익×0.7(사이클저점)이면 과열페널티 면제.
어떤 종목이 풀리나(진짜 인플렉션인가) + 부당감점 규모 확인."""
import sys, io, os, glob, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
def ttm_norm(t,base_ts):
    d=cache.get(t)
    if d is None: return None,None
    s=d.get('ni') or d.get('ni2')
    if s is None: return None,None
    v=s[1][s[0]<=np.datetime64(base_ts)]
    if len(v)<8: return None,None
    ttm=v[-4:].sum()
    N=min(12,len(v)); norm=v[-N:].mean()*4
    return ttm,norm
# 최근 날짜들에서 과열페널티 받은 종목 중 저점(TTM<norm*0.7) = 면제대상
for dt in ['20260624','20260601','20251201','20240603']:
    f=P+f'/state/ranking_{dt}.json'
    if not os.path.exists(f): continue
    r=json.load(open(f,encoding='utf-8'))['rankings']
    ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
    print(f"\n=== {dt} 과열페널티 받은 종목 중 사이클저점=면제대상 ===")
    exr=[]
    for x in r:
        pen=x.get('overheat_pen') or 0
        if pen>=-0.05: continue  # 감점 받은 것만
        ttm,norm=ttm_norm(x['ticker'],ts)
        if ttm is None or norm is None or norm<=0: continue
        ratio=ttm/norm
        if ratio<0.7:  # 저점
            exr.append((x['name'],x['rank'],pen,ratio,ttm,norm))
    for nm,rk,pen,ratio,ttm,norm in sorted(exr,key=lambda z:z[2])[:10]:
        print(f"  {nm[:12]:12s} rank{rk:>2} 과열pen{pen:>+5.2f} TTM/정규화={ratio:>4.2f} (TTM{ttm:>7.0f}/정규화{norm:>7.0f})")
    print(f"  → 면제대상 {len(exr)}종목 (이들 감점 풀림)")
