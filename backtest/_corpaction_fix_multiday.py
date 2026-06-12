# -*- coding: utf-8 -*-
"""전 종목 권리락(무상증자/병합) 자동보정 + 다일자 모멘텀 재계산.
- backadjust: 하루 |수익률|>33%(KR 가격제한 ±30% 초과=corporate action) → 이전 주가 스티칭
- 각 날짜별 영향 종목 모멘텀_z 재계산(검증된 방법) → score 보정(Δz×0.30) → cr 재정렬
- 디바이스/재영솔루텍 다일자 추적 → wr(3일가중) 영향 확인
"""
import pandas as pd, numpy as np, glob, json
from scipy.stats import norm
oh_raw=pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2019*_*.parquet'))[-1]).replace(0,np.nan)
oh_raw.index=pd.to_datetime(oh_raw.index)
out=open('_camd.txt','w',encoding='utf-8')

def backadjust(s):
    r=s.pct_change(fill_method=None)
    ev=r[(r<-0.33)|(r>0.45)]
    if ev.empty: return s, []
    s2=s.copy(); evs=[]
    for d,ret in ev.items():
        f=1+ret
        if 0.05<abs(f)<10:  # sanity
            s2.loc[s2.index<d]*=f; evs.append((d, round(ret*100)))
    return s2, evs

# 전 종목 보정 + 권리락 이력
ADJ={}; EVENTS={}
for tk in oh_raw.columns:
    s=oh_raw[tk].dropna()
    if len(s)<260: continue
    s2,evs=backadjust(oh_raw[tk])
    if evs: EVENTS[tk]=evs
    ADJ[tk]=s2

L12=252; VFLOOR=15.0
def voladj_mom(s, asof):
    s=s[s.index<=asof].dropna()
    if len(s)<L12+1: return np.nan
    cur=s.iloc[-1]; start=s.iloc[-(L12+1)]
    if not(start>0 and cur>0): return np.nan
    ret=(cur/start-1)*100
    dr=s.iloc[-(L12+1):].pct_change(fill_method=None).iloc[1:]
    vol=max(dr.std()*np.sqrt(252)*100, VFLOOR)
    return ret/vol

def blom(x):
    n=len(x); r=x.rank(method='average'); u=((r-0.375)/(n+0.25)).clip(0.001,0.999); return pd.Series(norm.ppf(u),index=x.index)
def sector_z(rawmap, secmap, min_sector=10):
    s=pd.Series(rawmap); sec=pd.Series({k:secmap.get(k,'?') for k in rawmap})
    z=blom(s)
    for sn in sec.unique():
        m=sec==sn
        if m.sum()>=min_sector: z[m]=blom(s[m])
    return z

def recompute_day(ds):
    """그날 랭킹 JSON 기준, 보정 모멘텀으로 cr 재정렬. return: {tk: (cr_old, cr_new, name)}"""
    import os
    f=f'state/ranking_{ds}.json'
    if not os.path.exists(f): return None
    rk=json.load(open(f,encoding='utf-8'))
    elig={str(x['ticker']).zfill(6):x for x in rk['rankings']}
    asof=pd.Timestamp(ds)
    secmap={tk:elig[tk].get('sector','?') for tk in elig}
    mom_w={}; mom_r={}
    for tk in elig:
        if tk in oh_raw.columns: mom_w[tk]=voladj_mom(oh_raw[tk], asof)
        if tk in ADJ: mom_r[tk]=voladj_mom(ADJ[tk], asof)
    mom_w={k:v for k,v in mom_w.items() if pd.notna(v)}
    mom_r={k:v for k,v in mom_r.items() if pd.notna(v)}
    zw=sector_z(mom_w, secmap); zr=sector_z(mom_r, secmap)
    # 보정 점수 = stored_score + 0.30*(zr - zw)  (델타법: 내 방법 잔차 상쇄)
    rows=[]
    for tk in elig:
        sc=elig[tk].get('score',0)
        d=0.0
        if tk in zw.index and tk in zr.index: d=zr[tk]-zw[tk]
        rows.append((tk, elig[tk]['name'], sc, sc+0.30*d, d))
    old=sorted(rows,key=lambda x:-x[2]); new=sorted(rows,key=lambda x:-x[3])
    crold={t:i+1 for i,(t,_,_,_,_) in enumerate(old)}
    crnew={t:i+1 for i,(t,_,_,_,_) in enumerate(new)}
    return {t:(crold[t],crnew[t],nm,dd) for (t,nm,_,_,dd) in rows}, len(elig)

DAYS=['20260603','20260604','20260605','20260608','20260609','20260610','20260611']
print('계산중...',flush=True)

# 1) 재영솔루텍 집중
out.write('========== 재영솔루텍(089470?) 권리락 이력 ==========\n')
# ticker 찾기
JY=None
for ds in DAYS[::-1]:
    import os
    if os.path.exists(f'state/ranking_{ds}.json'):
        rk=json.load(open(f'state/ranking_{ds}.json',encoding='utf-8'))
        m=next((x for x in rk['rankings'] if '재영솔루텍' in str(x.get('name',''))),None)
        if m: JY=str(m['ticker']).zfill(6); break
out.write(f'  ticker={JY}, 권리락이력={EVENTS.get(JY,"없음")}\n')

# 2) 다일자 cr old→new (디바이스/재영솔루텍)
out.write('\n========== 다일자 cr (보정 전→후) ==========\n')
out.write(f"{'날짜':<10}{'디바이스 cr':>16}{'재영솔루텍 cr':>18}\n")
dv_crs={}; jy_crs={}
for ds in DAYS:
    res=recompute_day(ds)
    if res is None: continue
    r,nel=res
    dv=r.get('187870'); jy=r.get(JY) if JY else None
    if dv: dv_crs[ds]=(dv[0],dv[1])
    if jy: jy_crs[ds]=(jy[0],jy[1])
    dvs=f"{dv[0]}→{dv[1]}" if dv else "-"
    jys=f"{jy[0]}→{jy[1]}" if jy else "-"
    out.write(f"{ds[4:6]}-{ds[6:]:<8}{dvs:>16}{jys:>18}\n")

# 3) wr(3일가중) 영향 — 디바이스
def wr(crs, days3):
    # crs: {ds:(old,new)}; days3=[t0,t1,t2]
    def val(ds,idx): return crs.get(ds,(50,50))[idx] if ds in crs else 50
    def pen(c): return c if c<=20 else 50
    o=val(days3[0],0)*0.4+pen(val(days3[1],0))*0.35+pen(val(days3[2],0))*0.25
    n=val(days3[0],1)*0.4+pen(val(days3[1],1))*0.35+pen(val(days3[2],1))*0.25
    return o,n
out.write('\n========== 디바이스 wr(3일가중, 매수기준) 보정 전→후 ==========\n')
for t0,t1,t2 in [('20260611','20260610','20260609')]:
    o,n=wr(dv_crs,[t0,t1,t2])
    out.write(f"  {t1[4:]}+{t0[4:]} 기준 wr: {o:.1f} → {n:.1f}  (매수권=3이하)\n")

# 4) 오늘 영향받은 랭킹종목 전체
out.write('\n========== 오늘(6/11) 권리락으로 cr 바뀐 랭킹종목 ==========\n')
res=recompute_day('20260611')
if res:
    r,_=res
    changed=[(t,v) for t,v in r.items() if v[0]!=v[1]]
    changed.sort(key=lambda x:x[1][0])
    out.write(f"  {'종목':<14}{'cr 보정전→후':>14}{'모멘텀Δz':>10}\n")
    for t,(co,cn,nm,dd) in changed:
        out.write(f"  {nm:<14}{f'{co}→{cn}':>14}{dd:>+10.2f}\n")
    out.write(f'  (총 {len(changed)}종목 cr 변동)\n')
out.close(); print('done')
