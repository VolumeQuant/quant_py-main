# -*- coding: utf-8 -*-
"""융합 커버 유니버스 1회 스캔 (2026-06-25). production 유니버스(시총상위 N)에 FnGuide 컨센 보유 여부 스캔.
애널 커버는 끈적해서(거의 안 변함) 1회 파악 후 그 셋만 매일 수집 → cross-sec 상위100 확인에 사용.
외부 API 안전: get_consensus_data 순차(delay), 병렬 금지.
실행: python kr_eps_momentum/fusion_universe_scan.py [N]   (N=시총상위, 기본 700)
출력: fusion_covered_universe.json (covered=컨센보유 티커) + fusion_consensus_cache.csv 시드"""
import sys, io, os, glob, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import fnguide_crawler as fc
OUT = os.path.join(HERE, 'fusion_covered_universe.json')
CACHE = os.path.join(HERE, 'fusion_consensus_cache.csv')
N = int(sys.argv[1]) if len(sys.argv) > 1 else 700
DELAY = 1.2

mc = pd.read_parquet(sorted(glob.glob(ROOT + '/data_cache/market_cap_ALL_*.parquet'))[-1])
f = sorted(glob.glob(ROOT + '/state/ranking_*.json'))[-1]
scan_day = os.path.basename(f)[8:16]
# ★유니버스 = market_cap_ALL (state ranking은 필터후 생존자라 너무 좁음). 시총≥1000억(production 플로어) 상위 N.
cap = mc[mc['시가총액'] >= 1e11].copy().sort_values('시가총액', ascending=False)
# 우선주(끝자리!=0)·스팩 제외
scan = [t for t in cap.index if isinstance(t, str) and len(t) == 6 and t[-1] == '0'][:N]
print(f"[융합 커버 스캔] 시총≥1000억 {len(cap)}종목 중 상위 {len(scan)} 스캔 (~{len(scan)*DELAY/60:.0f}분)", flush=True)

covered, rows = [], []
for i, t in enumerate(scan, 1):
    try:
        d = fc.get_consensus_data(t)
        has = bool(d and d.get('has_consensus'))
        fe = d.get('forward_eps') if d else None
        if has and fe and fe > 0:
            covered.append(t)
        rows.append({'date': scan_day, 'ticker': t, 'forward_eps': fe,
                     'analyst_count': d.get('analyst_count') if d else None, 'has_consensus': int(has)})
    except Exception:
        rows.append({'date': scan_day, 'ticker': t, 'forward_eps': None, 'analyst_count': None, 'has_consensus': 0})
    if i % 50 == 0:
        print(f"  {i}/{len(scan)} 진행, 커버 {len(covered)}", flush=True)
    time.sleep(DELAY)

json.dump({'scan_date': scan_day, 'n_scanned': len(scan), 'covered': covered, 'n_covered': len(covered)},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
# 컨센 캐시 시드(스캔일자) — 첫 일일런이 바로 쓰게
seed = pd.DataFrame(rows)
if os.path.exists(CACHE):
    old = pd.read_csv(CACHE, dtype={'ticker': str, 'date': str})
    seed = pd.concat([old[old['date'] != scan_day], seed], ignore_index=True)
seed.to_csv(CACHE, index=False)
print(f"\n[완료] 스캔 {len(scan)} → 커버(컨센보유) {len(covered)}종목 → {os.path.basename(OUT)}", flush=True)
