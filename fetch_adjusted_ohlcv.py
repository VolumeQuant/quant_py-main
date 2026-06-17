# -*- coding: utf-8 -*-
"""KRX 수정주가(adjusted) fetch — CA 후보 종목만 (raw에서 >30% 갭 발생 = 무상증자/분할/병합)
나머지 종목은 raw=수정주가라 fetch 불필요. _backadjust_corpaction(자작 임계) 대체.
출력: data_cache/adjusted_close_<today>.parquet (flagged 종목 수정 종가)"""
import sys, io, os, glob, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:/dev')
import numpy as np, pandas as pd

import krx_auth
if not krx_auth.login():
    print("[FATAL] KRX 로그인 실패 — 중복세션(CD011)일 수 있음. 중단.", flush=True)
    sys.exit(1)
from pykrx import stock

# 1) raw all_ohlcv 로드 + flagged(CA 후보) 산출
f = sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*_2026061*.parquet'))[-1]
px = pd.read_parquet(f).replace(0, np.nan)
fromdate = px.index[0].strftime('%Y%m%d')
todate = px.index[-1].strftime('%Y%m%d')
flagged = []
for tk in px.columns:
    r = px[tk].pct_change(fill_method=None)
    if ((r < -0.33) | (r > 0.45)).any():
        flagged.append(tk)
print(f"[INFO] flagged(CA 후보) {len(flagged)}종목 fetch 시작 ({fromdate}~{todate})", flush=True)

# 2) 종목별 수정주가 fetch (1.2s sleep, 순차)
adj = {}
fail = []
t0 = time.time()
for i, tk in enumerate(flagged):
    try:
        df = stock.get_market_ohlcv_by_date(fromdate, todate, tk, adjusted=True)
        if df is not None and len(df) and '종가' in df.columns:
            s = df['종가'].replace(0, np.nan)
            s.index = pd.to_datetime(s.index)
            adj[tk] = s
        else:
            fail.append(tk)
    except Exception as e:
        fail.append(tk)
        if len(fail) <= 5:
            print(f"  [warn] {tk}: {type(e).__name__}: {e}", flush=True)
    if (i + 1) % 50 == 0:
        el = time.time() - t0
        print(f"  {i+1}/{len(flagged)} ({el/60:.1f}분, 실패 {len(fail)})", flush=True)
    time.sleep(1.2)

# 3) 저장
out = pd.DataFrame(adj)
outpath = f'C:/dev/data_cache/adjusted_close_{todate}.parquet'
out.to_parquet(outpath)
print(f"[DONE] 수정주가 저장: {outpath} | {out.shape[1]}종목 {out.shape[0]}일 | 실패 {len(fail)}", flush=True)
if fail:
    print(f"[INFO] 실패 종목(상장폐지/신규 등): {fail[:20]}{'...' if len(fail)>20 else ''}", flush=True)
print(f"[INFO] 총 소요 {(time.time()-t0)/60:.1f}분", flush=True)
