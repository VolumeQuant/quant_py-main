# -*- coding: utf-8 -*-
"""'폭락날 혼자 오른 종목'이 진짜 알파인가? 7년 EDA.
가설: 시장 급락일에 상승한 종목 = 상대강도 → 이후 forward 수익 우월?
vs 함정: 펌프라 이후 빠짐?
all_ohlcv + kospi. 시장하락 임계 여러개 + forward 5/20/60일.
"""
import sys, glob
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
DATA='data_cache'
ohlcv=pd.read_parquet(sorted(glob.glob(f'{DATA}/all_ohlcv_2019*_*.parquet'))[-1]).replace(0,np.nan)
ohlcv.index=pd.to_datetime(ohlcv.index)
kospi=pd.read_parquet(f'{DATA}/kospi_yf.parquet')['close'].sort_index()
kospi.index=pd.to_datetime(kospi.index)

ret=ohlcv.pct_change()                       # 당일 수익률
kret=kospi.reindex(ohlcv.index).pct_change()  # 코스피 당일
# 유동성 대략 필터: 종가 1000원 미만 동전주 제외 (펌프 노이즈 줄임)
valid = ohlcv >= 1000

def fwd(n):
    return ohlcv.shift(-n)/ohlcv - 1

print('시장 급락일 정의별 / forward 기간별 — "그날 오른 종목" vs "그날 내린 종목" 이후 평균수익')
print(f'{"급락기준":<12}{"급락일수":>7}{"fwd":>5}{"오른종목수":>9}{"오른→fwd":>10}{"내린→fwd":>10}{"차이(알파)":>11}{"오른쪽승률":>9}')
for thr in [-0.01, -0.02, -0.03]:
    downdays = kret[kret < thr].index
    downdays = [d for d in downdays if d in ohlcv.index]
    for n in [5, 20, 60]:
        f = fwd(n)
        up_fwd=[]; dn_fwd=[]; n_up=0
        for d in downdays:
            r = ret.loc[d]; fv = f.loc[d]; vmask = valid.loc[d]
            ok = r.notna() & fv.notna() & vmask
            up = ok & (r > 0)       # 폭락날 오른 종목
            dn = ok & (r <= 0)      # 폭락날 내린 종목
            up_fwd.append(fv[up].values); dn_fwd.append(fv[dn].values); n_up += int(up.sum())
        uf = np.concatenate(up_fwd) if up_fwd else np.array([])
        dnf = np.concatenate(dn_fwd) if dn_fwd else np.array([])
        if len(uf)==0: continue
        um, dm = np.nanmean(uf)*100, np.nanmean(dnf)*100
        wr = (uf>0).mean()*100
        print(f'{thr*100:>+6.0f}%{"":<6}{len(downdays):>7}{n:>5}{n_up:>9}{um:>+9.2f}%{dm:>+9.2f}%{um-dm:>+10.2f}%{wr:>8.0f}%')
    print()
