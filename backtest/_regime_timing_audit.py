# -*- coding: utf-8 -*-
"""국면(MA20<MA80, 5일) 전 기간 타이밍 검증: 모든 급락 탐지 + 강세 진입 타이밍."""
import sys, io, os
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = r'C:\dev\claude-code\quant_py-main'

kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0].sort_index()
kc = kc[kc.index>='2019-01-01']
ma20, ma80 = kc.rolling(20).mean(), kc.rolling(80).mean()
idx = kc.index

# 5일 확인 국면
md=True; stk=0; ss=None; reg={}
for ts in idx:
    if pd.isna(ma80.get(ts,np.nan)): reg[ts]=md; continue
    s = bool(ma20[ts]>ma80[ts])
    if s==ss: stk+=1
    else: stk=1; ss=s
    if stk>=5 and md!=s: md=s
    reg[ts]=md
reg = pd.Series(reg)

def fwd(ts, n):
    pos = idx.get_loc(ts)
    if pos+n>=len(idx): return np.nan
    return (kc.iloc[pos+n]/kc.loc[ts]-1)*100

# 1) 모든 전환 + 이후 KOSPI 수익(타이밍 채점)
print("="*70)
print("【1】 모든 국면 전환 + 전환 후 KOSPI 흐름 (타이밍 채점)")
print("="*70)
print(f"{'날짜':<12}{'전환':<14}{'KOSPI':>8}{'+20일':>8}{'+60일':>8}  판정")
prev=None
for ts,v in reg.items():
    if prev is None or v!=prev:
        if prev is not None:
            f20,f60 = fwd(ts,20), fwd(ts,60)
            if not v:  # 방어 전환: 이후 KOSPI 하락이면 GOOD(피함)
                judge = '✅좋음(이후 하락 회피)' if (f60<0 or f20<0) else '➖무난/헛방어' if f60<3 else '❌비쌈(상승장 이탈)'
            else:      # 공격 전환: 이후 KOSPI 상승이면 GOOD
                judge = '✅좋음(이후 상승 포착)' if (f60>0 or f20>0) else '❌이른진입(이후 하락)'
            arrow = '🛡️방어(현금)' if not v else '📈공격(진입)'
            f20s = f'{f20:+.1f}' if not np.isnan(f20) else '  -'
            f60s = f'{f60:+.1f}' if not np.isnan(f60) else '  -'
            print(f"{str(ts.date()):<12}{arrow:<14}{kc.loc[ts]:>8,.0f}{f20s:>8}{f60s:>8}  {judge}")
    prev=v

# 2) 주요 급락 에피소드 자동 탐지(고점 대비 -12%+) + 국면 대응
print("\n"+"="*70)
print("【2】 주요 급락 에피소드(고점대비 -12%↑) 별 국면 대응")
print("="*70)
runpeak = kc.cummax()
dd = kc/runpeak - 1
# 에피소드: dd가 -12% 아래로 처음 내려간 뒤 신고점 회복까지
episodes=[]; in_ep=False; ep_peak_dt=None; ep_peak=None; trough=None; trough_dt=None
for ts in idx:
    if dd.loc[ts] <= -0.12 and not in_ep:
        in_ep=True; ep_peak=runpeak.loc[ts]; ep_peak_dt = kc[kc.index<=ts][kc[kc.index<=ts]==ep_peak].index[-1]
        trough=kc.loc[ts]; trough_dt=ts
    if in_ep:
        if kc.loc[ts]<trough: trough=kc.loc[ts]; trough_dt=ts
        if kc.loc[ts]>=ep_peak:  # 회복
            episodes.append((ep_peak_dt,ep_peak,trough_dt,trough)); in_ep=False
if in_ep: episodes.append((ep_peak_dt,ep_peak,trough_dt,trough))

for pk_dt,pk,tr_dt,tr in episodes:
    decline=(tr/pk-1)*100
    # 이 에피소드 동안 첫 방어 전환일
    seg = reg[(reg.index>=pk_dt)&(reg.index<=tr_dt)]
    first_def = next((t for t,v in seg.items() if not v), None)
    print(f"\n● 고점 {pk:,.0f}({pk_dt.date()}) → 저점 {tr:,.0f}({tr_dt.date()})  {decline:.1f}%  ({(tr_dt-pk_dt).days}일간)")
    if first_def is None:
        # 고점 전부터 이미 방어였는지 확인
        before = reg[reg.index<=pk_dt]
        if len(before) and not before.iloc[-1]:
            # 방어 시작일 역추적
            ds = before[before].index.max() if before.any() else None
            print(f"   🛡️ 고점 이전부터 이미 방어 상태 (선제 회피)")
        else:
            print(f"   ❌ 이 급락 구간에 방어 전환 없음 (놓침)")
    else:
        lvl=kc.loc[first_def]
        missed=(lvl/pk-1)*100; avoided=(tr/lvl-1)*100
        grade = '✅조기탐지' if missed>-10 else '⚠️늦은탐지' if missed>-20 else '❌많이놓침'
        print(f"   🛡️ 방어전환 {first_def.date()} @ {lvl:,.0f}: 놓친낙폭 {missed:+.1f}% / 회피낙폭 {avoided:+.1f}%  {grade}")

# 3) 강세(공격) 진입 타이밍 종합
print("\n"+"="*70)
print("【3】 강세장 진입(공격 전환) 타이밍 종합")
print("="*70)
boost_sigs=[]; prev=None
for ts,v in reg.items():
    if prev is not None and v and not prev: boost_sigs.append(ts)
    prev=v
f20s=[fwd(t,20) for t in boost_sigs]; f60s=[fwd(t,60) for t in boost_sigs]
f20s=[x for x in f20s if not np.isnan(x)]; f60s=[x for x in f60s if not np.isnan(x)]
print(f"  공격 전환 {len(boost_sigs)}회")
print(f"  진입 후 +20일 KOSPI: 평균 {np.mean(f20s):+.1f}% / 승률 {np.mean([x>0 for x in f20s])*100:.0f}%")
print(f"  진입 후 +60일 KOSPI: 평균 {np.mean(f60s):+.1f}% / 승률 {np.mean([x>0 for x in f60s])*100:.0f}%")

# 4) 방어/공격 구간 KOSPI 평균 일수익 (국면이 방향을 맞췄나)
bd = reg.reindex(idx).fillna(method='ffill')
ret = kc.pct_change()*100
print(f"\n  [전체] 공격구간 KOSPI 평균 일수익 {ret[bd].mean():+.3f}% (양수=상승장 포착)")
print(f"         방어구간 KOSPI 평균 일수익 {ret[~bd].mean():+.3f}% (음수/0=하락 회피)")
print(f"         공격 {bd.mean()*100:.0f}% / 방어 {(1-bd.mean())*100:.0f}% 시간 비중")
