"""Phase 5a: Attack 그리드서치 — TurboSimulator 사용 (attack-only 기준)

탐색 범위 (v77~v78 인사이트 기반):
  V: 0,5,10,15,20,25,30 (7)
  Q: 0,5,10,15 (4)
  G: 20,30,40,45,50,55,60,65,70 (9)
  M: 20,25,30,35,40,45 (6)
  조건: V+Q+G+M = 100
  G서브: 3팩터(rev+oca+gp, 0.5/0.3/0.2), 2팩터(rev+oca, 0.7/0.3)
  MOM: 6m, 6m-1m, 12m, 12m-1m

E/X/S 고정 (Phase 2b에서 재서치):
  entry=5, exit=8, slots=5

결과: Top 15 선정 → Phase 5b (E/X/S) 입력
"""
import sys, os, time, json, glob
from pathlib import Path
from itertools import product
sys.path.insert(0, 'C:/dev/backtest')
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator

# 데이터 로드
print('ranking 로드...', flush=True)
STATE = Path('C:/dev/state')
BT_EXT = Path('C:/dev/backtest/bt_extended')

def load_rankings(dirs):
    data = {}
    for d in dirs:
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            if len(fp.stem.replace('ranking_','')) != 8: continue
            k = fp.stem.replace('ranking_','')
            if k not in data:
                data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data

rankings_rd = load_rankings([BT_EXT, STATE])  # 2018-07~2026-04
dates = sorted(rankings_rd.keys())
# TurboSim은 {date: [ranking_list]} 기대
rankings = {d: rankings_rd[d]['rankings'] for d in dates}
print(f'ranking: {len(dates)}일 ({dates[0]}~{dates[-1]})', flush=True)

# OHLCV
ohlcv_files = sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))
prices = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
print(f'OHLCV: {prices.shape}, {prices.index.min()}~{prices.index.max()}', flush=True)

# TurboSimulator
tsim = TurboSimulator(rankings, dates, prices)
print('TurboSimulator 초기화 완료', flush=True)

# Phase 4b 인사이트 기반 축소 범위 (v77.1, v78 중심 탐색)
VW_RANGE = [0, 5, 10, 15, 20]
QW_RANGE = [0, 5]
GW_RANGE = [45, 50, 55, 60, 65]
MW_RANGE = [25, 30, 35]
MOMS = ['12m', '12m-1m']  # 4종 → 2종 (Phase 4b에서 12m 계열 우세)
G_SUBS = [
    ('3f_rev_oca_gp', 'rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),   # v77.1
    ('3f_rev_oca_opm', 'rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2),  # v78
    ('2f_rev_oca_0.7', 'rev_z', 'oca_z', None, None, None, None),        # 2팩터
]

# V+Q+G+M=100 조건
combos = []
for v, q, g, m in product(VW_RANGE, QW_RANGE, GW_RANGE, MW_RANGE):
    if v + q + g + m == 100:
        for mom in MOMS:
            for gs_label, gs1, gs2, gs3, w1, w2, w3 in G_SUBS:
                combos.append((v, q, g, m, mom, gs_label, gs1, gs2, gs3, w1, w2, w3))
print(f'조합 수: {len(combos)}', flush=True)

# 실행
results = []
t0 = time.time()
ENTRY, EXIT, SLOTS = 5, 8, 5
TRAIL = -0.15

# BT 기간: 7.8년 (2018-07-02 ~ 2026-04-14)
# attack-only: regime_dict = {d: True for d in dates}
regime_all_attack = {d: True for d in dates}

for i, (v, q, g, m, mom, gs_label, gs1, gs2, gs3, w1, w2, w3) in enumerate(combos):
    v_w, q_w, g_w, m_w = v/100, q/100, g/100, m/100
    g_rev = w1 if w1 is not None else 0.7  # 2팩터면 g_rev=0.7

    try:
        r = tsim.run_fast(
            v_w=v_w, q_w=q_w, g_w=g_w, m_w=m_w, g_rev=g_rev,
            entry_param=ENTRY, exit_param=EXIT, max_slots=SLOTS,
            mom_type=mom, trailing_stop=TRAIL,
            g_sub1=gs1, g_sub2=gs2, g_sub3=gs3, g_w1=w1, g_w2=w2, g_w3=w3,
        )
        results.append({
            'V': v, 'Q': q, 'G': g, 'M': m,
            'mom': mom, 'gs': gs_label,
            'cagr': r.get('cagr', 0), 'mdd': r.get('mdd', 0),
            'calmar': r.get('calmar', 0), 'total': r.get('total', 0),
        })
    except Exception as e:
        print(f'  [{i}] {v}Q{q}G{g}M{m} {mom} {gs_label}: ERR {str(e)[:60]}', flush=True)
        continue

    if (i + 1) % 50 == 0:
        elapsed = time.time() - t0
        rate = (i+1) / elapsed
        eta = (len(combos) - i - 1) / rate if rate > 0 else 0
        print(f'  [{i+1}/{len(combos)}] {elapsed:.1f}s elapsed, ETA {eta:.0f}s', flush=True)

# 정렬 + 저장
df = pd.DataFrame(results)
df = df.sort_values('calmar', ascending=False)

out_path = 'C:/dev/backtest/phase5a_attack_grid.csv'
df.to_csv(out_path, index=False, encoding='utf-8-sig')
print(f'\n저장: {out_path}', flush=True)

print(f'\n=== Top 15 (Cal 기준) ===')
print(df.head(15).to_string(index=False))

elapsed = time.time() - t0
print(f'\n총 소요: {elapsed/60:.1f}분 ({len(combos)/elapsed:.1f} comb/초)', flush=True)
