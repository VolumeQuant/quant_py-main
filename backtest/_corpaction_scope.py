# -*- coding: utf-8 -*-
"""무상증자/액면분할 미보정 OHLCV 불연속 스캔 — 모멘텀 왜곡 범위 조사.
KR 일일 가격제한 ±30% → 하루 |수익률|>33%면 corporate action(권리락) 또는 데이터.
trailing ~13개월(12m 모멘텀 창) 내 불연속 종목 + 현재 랭킹 포함 여부 + 현 모멘텀."""
import pandas as pd, numpy as np, glob, json, os
oh=pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2019*_*.parquet'))[-1]).replace(0,np.nan)
oh.index=pd.to_datetime(oh.index)
cutoff=oh.index[-1]-pd.Timedelta(days=400)   # 12m 모멘텀 창 + 버퍼
recent=oh[oh.index>=cutoff]
ret=recent.pct_change(fill_method=None)

# 최신 랭킹: ticker -> (name, rank, momentum_s)
rk=json.load(open(sorted(glob.glob('state/ranking_2026*.json'))[-1],encoding='utf-8'))
RKMAP={str(x['ticker']).zfill(6):(x.get('name','?'),int(x['rank']),x.get('momentum_s',0)) for x in rk['rankings']}

down={}; up={}
for tk in recent.columns:
    r=ret[tk]
    d=r[(r<-0.33)&(r>-0.90)]      # 권리락(무상증자/분할): 가격↓
    u=r[(r>0.45)&(r<5)]           # 주식병합(reverse split): 가격↑
    if len(d): down[tk]=[(dt.date().isoformat(),round(v*100)) for dt,v in d.items()]
    if len(u): up[tk]=[(dt.date().isoformat(),round(v*100)) for dt,v in u.items()]

out=open('_scope_scan.txt','w',encoding='utf-8')
out.write(f'OHLCV 전체 {recent.shape[1]}종목, 기간 {recent.index[0].date()}~{recent.index[-1].date()}\n')
out.write(f'\n[가격 급락 불연속(-33%~-90%, 무상증자/액면분할 권리락 의심)] 총 {len(down)}종목\n')
out.write(f'[가격 급등 불연속(+45%+, 주식병합 의심)] 총 {len(up)}종목\n')

ranked_down=[(tk,RKMAP[tk]) for tk in down if tk in RKMAP]
out.write(f'\n===== ★ 현재 랭킹에 든 종목 중 급락불연속 {len(ranked_down)}개 (=지금 순위 왜곡 중) =====\n')
out.write(f"{'종목':<14}{'현순위':>5}{'현모멘텀':>8}  불연속(날짜,%)\n")
for tk,(nm,rnk,mom) in sorted(ranked_down,key=lambda x:x[1][1]):
    out.write(f"{nm:<14}{rnk:>5}{mom:>+8.2f}  {down[tk]}\n")

ranked_up=[(tk,RKMAP[tk]) for tk in up if tk in RKMAP]
out.write(f'\n===== 랭킹 종목 중 급등불연속(병합) {len(ranked_up)}개 =====\n')
for tk,(nm,rnk,mom) in sorted(ranked_up,key=lambda x:x[1][1]):
    out.write(f"{nm:<14}{rnk:>5}{mom:>+8.2f}  {up[tk]}\n")
out.close(); print('done')
