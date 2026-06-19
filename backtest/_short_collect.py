# -*- coding: utf-8 -*-
"""공매도 잔고비율 수집 (KRX 인증) — 주간 스냅샷, KOSPI+KOSDAQ.
안전: 1.2초 sleep, 순차, 중간저장(resume). 잔고비율(잔고/상장주식 %) = 구조적 숏 위험."""
import sys, time, json, glob
from pathlib import Path
import pandas as pd
sys.path.insert(0,'C:/dev'); sys.stdout.reconfigure(encoding='utf-8')
import krx_auth
from pykrx import stock

OUT='backtest/_short_balance.parquet'
PROG='backtest/_short_progress.json'

# 거래일 목록 (state_peg_bt) → 매 5거래일 (주간)
dates=sorted([f.split('_')[-1].replace('.json','') for f in glob.glob('state/ranking_*.json')
              if f.split('_')[-1].replace('.json','').isdigit() and '20190102'<=f.split('_')[-1].replace('.json','')<='20260605'])
snap=dates[::5]
print(f'주간 스냅샷 {len(snap)}일 ({snap[0]}~{snap[-1]})', flush=True)

# resume
done=set()
if Path(PROG).exists():
    done=set(json.load(open(PROG)))
existing={}
if Path(OUT).exists():
    ex=pd.read_parquet(OUT); existing={d:ex.loc[d] for d in ex.index}
    print(f'기존 {len(existing)}일 로드', flush=True)

if not krx_auth.login():
    print('인증 실패 — 중단'); sys.exit(1)

rows=dict(existing)
t0=time.time(); n=0; fail=0
for ds in snap:
    if ds in done: continue
    ser={}
    for mkt in ['KOSPI','KOSDAQ']:
        try:
            df=stock.get_shorting_balance_by_ticker(ds, market=mkt)
            if len(df):
                for tk in df.index:
                    ser[str(tk).zfill(6)]=float(df.at[tk,'비중'])  # 잔고비율 %
        except Exception as e:
            fail+=1
        time.sleep(1.2)
    if ser:
        rows[ds]=pd.Series(ser); done.add(ds); n+=1
    if n%20==0 and n>0:
        pd.DataFrame(rows).T.to_parquet(OUT)
        json.dump(sorted(done), open(PROG,'w'))
        print(f'  {n}일 수집 ({(time.time()-t0)/60:.1f}분, fail {fail})', flush=True)
# 최종 저장
panel=pd.DataFrame(rows).T
panel.index=pd.to_datetime(panel.index)
panel=panel.sort_index()
panel.to_parquet(OUT)
json.dump(sorted(done), open(PROG,'w'))
print(f'\n완료: {len(panel)}일 × {panel.shape[1]}종목, {(time.time()-t0)/60:.1f}분, fail {fail}', flush=True)
print(f'저장: {OUT}', flush=True)
