# -*- coding: utf-8 -*-
"""분할 매수(50%+다음날) 유용성 검증 (2026-06-14).
US 세션 "분할 무의미, 한번에" 결론을 KR full-config로 재현/반박.
모델: 신규 진입 슬롯은 첫날 50%만 투입(나머지 현금=0수익), 다음날부터 100%.
→ 신규 진입 종목의 '진입당일→다음날' 수익이 +면 분할은 손해(절반은 더 비싸게 삼).
"""
import sys, io, os, glob, json
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

rk = {}
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_2019*.json'))
              + glob.glob(os.path.join(PROJ, 'state', 'ranking_202[0-6]*.json'))):
    dt = os.path.basename(f).replace('ranking_', '').replace('.json', '')
    if dt < '20190102': continue
    try:
        d = json.load(open(f, encoding='utf-8'))
        rk[dt] = {x['ticker']: x['weighted_rank'] for x in d['rankings']}
    except Exception: pass
dates = sorted(rk)
px = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*.parquet')),
                            key=lambda f: f.split('_')[-1])[-1]).replace(0, np.nan).sort_index()
pxidx = {d: pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]) for d in dates}
print(f'[데이터] {dates[0]}~{dates[-1]} {len(dates)}일')

kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20, ma80 = kc.rolling(20).mean(), kc.rolling(80).mean()
def calc_reg(ec=5, en=5, dsub=None):
    ds = dsub or dates; reg={}; md=True; stk=0; ss=None
    for d in ds:
        ts = pxidx[d]
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d]=md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk >= (en if s else ec) and md!=s: md=s
        reg[d]=md
    return reg

def ret1(tk, d, dn):
    if tk not in px.columns: return None
    s = px[tk]; a, b = s.get(pxidx[d]), s.get(pxidx[dn])
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a<=0: return None
    r = b/a-1
    return None if abs(r)>0.35 else r

def replay(reg, split=False, dsub=None):
    ds = dsub or dates; hold=set(); rets=[]; newday_rets=[]
    for i in range(len(ds)-1):
        d, dn = ds[i], ds[i+1]
        if not reg[d]: hold=set(); rets.append(0.0); continue
        rank = rk[d]; prev=set(hold)
        hold = {t for t in hold if rank.get(t,9999)<=6}
        if len(hold)<3:
            for t in sorted([t for t in rank if rank[t]<=3 and t not in hold], key=lambda t: rank[t]):
                if len(hold)>=3: break
                hold.add(t)
        new = hold - prev
        contrib=[]
        for t in hold:
            r = ret1(t, d, dn)
            if r is None: continue
            if t in new:
                newday_rets.append(r)                 # 신규 진입 첫날 수익
                contrib.append(0.5*r if split else r)  # 분할이면 절반만 투입(나머지 현금0)
            else:
                contrib.append(r)
        rets.append(float(np.mean(contrib)) if contrib else 0.0)
    return np.array(rets), newday_rets

def metrics(rets):
    eq=np.cumprod(1+rets); n=len(rets)
    cagr=(eq[-1]**(252/max(n,1))-1)*100
    peak=np.maximum.accumulate(np.concatenate([[1.0],eq]))
    mdd=abs(((np.concatenate([[1.0],eq])-peak)/peak).min())*100
    return cagr, mdd, (cagr/mdd if mdd>0 else 0)

reg = calc_reg()
full, newr = replay(reg, split=False)
splt, _ = replay(reg, split=True)
print('\n========== 분할 매수(50%+다음날) vs 한번에 (full-config) ==========')
for nm, r in [('한번에(전액 당일)', full), ('분할(50%+다음날)', splt)]:
    cg, md, cal = metrics(r)
    print(f"  {nm:<18} Calmar {cal:.3f}  CAGR {cg:.1f}  MDD {md:.1f}")

# 진단: 신규 진입 종목의 '진입당일→다음날' 수익 분포
na = np.array(newr)
print(f'\n  [진단] 신규 진입 {len(na)}건의 진입당일→다음날 수익')
print(f"    평균 {na.mean()*100:+.3f}%  중앙 {np.median(na)*100:+.3f}%  승률 {(na>0).mean()*100:.1f}%")
print(f"    → 평균이 +면 다음날 더 비싸게 사는 것 = 분할은 그만큼 손해")
print(f"    분할 시 기대 드래그 ≈ 0.5 × 진입건당 {na.mean()*100:+.3f}% (신규진입에만)")

# WF: 약세장 포함 기간별로도 분할이 손해인가
print('\n  [WF] 기간별 한번에 vs 분할 Calmar')
for lab, lo, hi in [('2019-21','20190102','20211231'),('2022-23','20220101','20231231'),('2024-26','20240101','20261231')]:
    dsub=[d for d in dates if lo<=d<=hi]
    rf=metrics(replay(calc_reg(dsub=dsub), split=False, dsub=dsub)[0])[2]
    rs=metrics(replay(calc_reg(dsub=dsub), split=True, dsub=dsub)[0])[2]
    print(f"   {lab}: 한번에 {rf:.2f} | 분할 {rs:.2f}  (Δ{rs-rf:+.2f})")
