# -*- coding: utf-8 -*-
"""현재 전략(_sp0b_co, 7.4년) 기준 통계: wr 3위 안 진입(매수후보) → 이후 6위 밖 이탈 케이스 집계.
wr = cr_t0*0.4 + cr_t1(top20만,else50)*0.35 + cr_t2(top20만,else50)*0.25 (production _postprocess와 동일).
국면(KOSPI MA20>MA80 5일확인=boost)만 매수, 방어 전환 시 청산(top6이탈과 구분)."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd, numpy as np
PROJ = r'C:\dev'
def load(folder):
    ar={}
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102':
            ar[dt]={x['ticker']:x.get('composite_rank',x['rank']) for x in json.load(open(f,encoding='utf-8'))['rankings']}
    return ar
cr=load('_sp0b_co'); days=sorted(cr)
# 국면
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]; kc.index=pd.to_datetime(kc.index)
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
reg={}; md=True; stk=0; ss=None
for d in days:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md; continue
    s=bool(ma20[ts]>ma80[ts])
    if s==ss: stk+=1
    else: stk=1; ss=s
    if stk>=5 and md!=s: md=s
    reg[d]=md
# wr 순위 per day
wrrank={}
for i,d in enumerate(days):
    c0=cr[d]; p1=cr[days[i-1]] if i>=1 else {}; p2=cr[days[i-2]] if i>=2 else {}
    t1={t:r for t,r in p1.items() if r<=20}; t2={t:r for t,r in p2.items() if r<=20}
    wr={t:c0[t]*0.4 + t1.get(t,50)*0.35 + t2.get(t,50)*0.25 for t in c0}
    order=sorted(wr,key=lambda t:wr[t])
    wrrank[d]={t:i+1 for i,t in enumerate(order)}
# 상태머신
holding={}  # tk -> (entry_day_idx)
n_entry=0; n_top6_exit=0; n_regime_exit=0; durations=[]
boost_days=sum(1 for d in days if reg[d])
for i,d in enumerate(days):
    wrr=wrrank[d]
    if not reg[d]:
        for tk in list(holding): n_regime_exit+=1; del holding[tk]
        continue
    # 이탈 체크(보유중 wr>6 or 랭킹이탈)
    for tk in list(holding):
        rk=wrr.get(tk,999)
        if rk>6:
            n_top6_exit+=1; durations.append(i-holding[tk]); del holding[tk]
    # 진입(wr<=3, 미보유)
    for tk,rk in wrr.items():
        if rk<=3 and tk not in holding:
            holding[tk]=i; n_entry+=1
still=len(holding)
durations=np.array(durations)
print(f"[현재전략 _sp0b_co | {days[0]}~{days[-1]} {len(days)}일 (boost {boost_days}일)]")
print(f"\n=== top3 진입(매수후보) → 6위 밖 이탈 통계 ===")
print(f"총 top3 진입(매수후보 편입) 횟수 : {n_entry}건")
print(f"그중 ★6위 밖 이탈로 빠진 케이스  : {n_top6_exit}건  ({n_top6_exit/max(n_entry,1)*100:.1f}%)")
print(f"방어전환으로 청산(6위이탈 아님)  : {n_regime_exit}건  ({n_regime_exit/max(n_entry,1)*100:.1f}%)")
print(f"아직 보유중(종료시점)            : {still}건")
print(f"\n=== 6위 이탈까지 보유기간 분포 (거래일) ===")
if len(durations):
    print(f"  중앙값 {np.median(durations):.0f}일 / 평균 {durations.mean():.1f}일 / 최소 {durations.min()} / 최대 {durations.max()}")
    for thr in [1,2,3,5,10,20]:
        print(f"  {thr}일 이내 이탈(휩쏘): {(durations<=thr).sum()}건 ({(durations<=thr).mean()*100:.0f}%)")
print(f"\n→ '매수후보 됐다가 6위밖으로 빠진' = {n_top6_exit}건. 이 중 단기(≤3일) 휩쏘가 {(durations<=3).sum() if len(durations) else 0}건.")
