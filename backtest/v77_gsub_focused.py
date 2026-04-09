"""v77 G서브 인사이트 기반 집중 분석

Usage: python v77_gsub_focused.py [attack|defense|both]
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
RUN_MODE = sys.argv[1] if len(sys.argv) > 1 else 'both'  # attack, defense, both
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
t0 = time.time()

ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

mode = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d)
    kv = kospi.get(ts, None); mv = km200.get(ts, None)
    s = (kv > mv) if kv is not None and mv is not None else mode
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and mode != s: mode = s
    rd[d] = mode

boost_dates = [d for d in dates if rd[d]]
defense_dates = [d for d in dates if not rd[d]]
print(f'공격 {len(boost_dates)}일, 방어 {len(defense_dates)}일', flush=True)

g_revs = [round(x * 0.1, 1) for x in range(11)]
mom_types = ['6m', '6m-1m', '12m', '12m-1m']

# ── 공격용 대표 가중치 (G=40~70%, 역대 패턴 기반) ──
atk_weights = [
    (15, 5, 60, 20), (10, 0, 70, 20), (10, 5, 65, 20), (20, 5, 55, 20),
    (15, 0, 60, 25), (10, 5, 55, 30), (15, 10, 50, 25), (10, 0, 65, 25),
    (20, 0, 50, 30), (5, 5, 70, 20), (15, 5, 50, 30), (10, 10, 50, 30),
    (25, 5, 45, 25), (20, 10, 40, 30), (15, 5, 55, 25),
]

# ── 방어용 대표 가중치 (M=40~60%, 역대 패턴 기반) ──
def_weights = [
    (15, 10, 25, 50), (20, 10, 20, 50), (15, 10, 20, 55), (25, 10, 20, 45),
    (15, 5, 20, 60), (20, 5, 25, 50), (10, 10, 30, 50), (15, 15, 20, 50),
    (20, 10, 25, 45), (25, 5, 20, 50), (10, 10, 20, 60), (15, 10, 30, 45),
    (20, 10, 15, 55), (25, 10, 25, 40), (10, 5, 25, 60),
]


def make_3factor_rankings(rk_orig, sub1, sub2, sub3, w1, w2, w3):
    """3팩터 합성: sub1*w1 + sub2*w2 + sub3*w3 → synthetic growth_s로 저장"""
    rk_new = {}
    for d, items in rk_orig.items():
        # 1단계: raw 합산
        raw_vals = []
        for s in items:
            v1 = s.get(sub1, 0) or 0
            v2 = s.get(sub2, 0) or 0
            v3 = s.get(sub3, 0) or 0
            raw_vals.append(v1 * w1 + v2 * w2 + v3 * w3)
        # 2단계: 재정규화 (2팩터와 동일하게 mean=0, std=1)
        import numpy as _np
        arr = _np.array(raw_vals)
        mean, std = arr.mean(), arr.std()
        if std > 0:
            normed = (arr - mean) / std
        else:
            normed = _np.zeros(len(arr))
        # 3단계: growth_s에 저장
        new_items = []
        for i, s in enumerate(items):
            ns = dict(s)
            ns['growth_s'] = float(normed[i])
            new_items.append(ns)
        rk_new[d] = new_items
    return rk_new


def run_test(tsim, weights, entry, exit_r, slots, g_rev, mom, gs1='rev_z', gs2='oca_z'):
    results = []
    for v, q, g, m in weights:
        r = tsim.run_fast(v/100, q/100, g/100, m/100, g_rev,
                         entry_param=entry, exit_param=exit_r, max_slots=slots,
                         mom_type=mom, stop_loss=-0.10, trailing_stop=-0.15,
                         g_sub1=gs1, g_sub2=gs2)
        results.append({'v': v, 'q': q, 'g': g, 'm': m, **r})
    return results


def test_gsub_combo(label, mode_dates, weights, entry, exit_r, slots, gs1, gs2, rk_data=None):
    """단일 G서브 조합 테스트 → 모든 g_rev × mom × weights"""
    if rk_data is None:
        rk_mode = {d: rk[d] for d in mode_dates}
    else:
        rk_mode = {d: rk_data[d] for d in mode_dates if d in rk_data}
    tsim = TurboSimulator(rk_mode, mode_dates, ohlcv, bench=bench)

    all_results = []
    for gr in g_revs:
        for mom in mom_types:
            results = run_test(tsim, weights, entry, exit_r, slots, gr, mom, gs1, gs2)
            for r in results:
                r.update({'gr': gr, 'mom': mom, 'gs1': gs1, 'gs2': gs2, 'label': label})
            all_results.extend(results)
    return all_results


def test_3factor(label, mode_dates, weights, entry, exit_r, slots,
                 sub1, sub2, sub3, w_combos):
    """3팩터 조합 테스트"""
    all_results = []
    for w1, w2, w3 in w_combos:
        rk_3f = make_3factor_rankings(rk, sub1, sub2, sub3, w1, w2, w3)
        rk_mode = {d: rk_3f[d] for d in mode_dates if d in rk_3f}
        tsim = TurboSimulator(rk_mode, mode_dates, ohlcv, bench=bench)
        for mom in mom_types:
            # growth_s 사용 → g_rev=0.5 (use_original_g path)
            results = run_test(tsim, weights, entry, exit_r, slots, 0.5, mom)
            for r in results:
                r.update({'gr': f'{w1:.1f}/{w2:.1f}/{w3:.1f}', 'mom': mom,
                          'gs1': f'{sub1}+{sub2}+{sub3}', 'gs2': f'{w1}/{w2}/{w3}',
                          'label': label})
            all_results.extend(results)
    return all_results


# ============================================================
# 공격 모드
# ============================================================
if RUN_MODE not in ('attack', 'both'):
    print('공격 스킵', flush=True)
elif True:
    print(f'\n{"="*70}', flush=True)
    print('공격 모드 G서브 집중 분석', flush=True)
    print(f'{"="*70}', flush=True)

atk_all = []

# 2팩터 후보 (인사이트 기반)
atk_2f = [
    ('atk_oca_opm', 'oca_z', 'op_margin_z'),      # v75-v76 실전
    ('atk_rev_oca', 'rev_z', 'oca_z'),             # v77 G서브 1위
    ('atk_oca_gp', 'oca_z', 'gp_growth_z'),        # v77 G서브 3위
    ('atk_rev_opm', 'rev_z', 'op_margin_z'),       # v77 G서브 5위
    ('atk_rev_gp', 'rev_z', 'gp_growth_z'),        # v77 G서브 4위
]

for label, gs1, gs2 in atk_2f:
    print(f'  {label}: {gs1} + {gs2}', flush=True)
    t1 = time.time()
    results = test_gsub_combo(label, boost_dates, atk_weights, 5, 8, 3, gs1, gs2)
    atk_all.extend(results)
    cals = [r['calmar'] for r in results]
    print(f'    {len(results)}건, avg_cal={np.mean(cals):.3f}, max_cal={np.max(cals):.2f} ({time.time()-t1:.0f}s)', flush=True)

# 1팩터 (oca_z 단독)
print(f'  atk_oca_only: oca_z 단독', flush=True)
t1 = time.time()
results = test_gsub_combo('atk_oca_only', boost_dates, atk_weights, 5, 8, 3, 'oca_z', 'oca_z')
# g_rev=1.0일 때만 유효 (sub1=sub2이므로 어떤 비율이든 같음)
atk_all.extend(results)
print(f'    {len(results)}건 ({time.time()-t1:.0f}s)', flush=True)

# 3팩터
print(f'  atk_3f: oca_z + op_margin_z + gp_growth_z', flush=True)
t1 = time.time()
w3_combos = [
    (0.5, 0.3, 0.2), (0.6, 0.2, 0.2), (0.4, 0.4, 0.2),
    (0.5, 0.2, 0.3), (0.4, 0.3, 0.3), (0.7, 0.2, 0.1),
    (0.3, 0.4, 0.3), (0.6, 0.3, 0.1),
]
results = test_3factor('atk_3f_oca_opm_gp', boost_dates, atk_weights, 5, 8, 3,
                       'oca_z', 'op_margin_z', 'gp_growth_z', w3_combos)
atk_all.extend(results)
print(f'    {len(results)}건 ({time.time()-t1:.0f}s)', flush=True)

# rev_z + oca_z + op_margin_z
print(f'  atk_3f: rev_z + oca_z + op_margin_z', flush=True)
t1 = time.time()
results = test_3factor('atk_3f_rev_oca_opm', boost_dates, atk_weights, 5, 8, 3,
                       'rev_z', 'oca_z', 'op_margin_z', w3_combos)
atk_all.extend(results)
print(f'    {len(results)}건 ({time.time()-t1:.0f}s)', flush=True)

atk_df = pd.DataFrame(atk_all)
atk_summary = atk_df.groupby('label').agg(
    avg_cal=('calmar', 'mean'), max_cal=('calmar', 'max'),
    avg_cagr=('cagr', 'mean'), count=('calmar', 'count'),
).sort_values('max_cal', ascending=False)

print(f'\n공격 조합별 성과:', flush=True)
for label, r in atk_summary.iterrows():
    print(f'  {label:<25} avg_cal={r["avg_cal"]:.3f}  max_cal={r["max_cal"]:.2f}  avg_cagr={r["avg_cagr"]:.1f}%', flush=True)

atk_df.to_csv(RESULT_DIR / 'v77_gsub_focused_attack.csv', index=False)


# ============================================================
# 방어 모드
# ============================================================
if RUN_MODE in ('defense', 'both'):
 print(f'\n{"="*70}', flush=True)
 print('방어 모드 G서브 집중 분석 (M-heavy 가중치)', flush=True)
print(f'{"="*70}', flush=True)

def_all = []

# 2팩터 후보
def_2f = [
    ('def_rev_opm', 'rev_z', 'op_margin_z'),          # v75-v76 실전
    ('def_oca_opm', 'oca_z', 'op_margin_z'),           # v77 G서브 5위
    ('def_oca_raccel', 'oca_z', 'rev_accel_z'),         # v77 G서브 1위
    ('def_rev_raccel', 'rev_z', 'rev_accel_z'),         # v77 G서브 2위
    ('def_raccel_opm', 'rev_accel_z', 'op_margin_z'),   # v77 G서브 3위
    ('def_raccel_gp', 'rev_accel_z', 'gp_growth_z'),    # v77 G서브 4위
]

for label, gs1, gs2 in def_2f:
    print(f'  {label}: {gs1} + {gs2}', flush=True)
    t1 = time.time()
    results = test_gsub_combo(label, defense_dates, def_weights, 5, 8, 5, gs1, gs2)
    def_all.extend(results)
    cals = [r['calmar'] for r in results]
    print(f'    {len(results)}건, avg_cal={np.mean(cals):.3f}, max_cal={np.max(cals):.2f} ({time.time()-t1:.0f}s)', flush=True)

# 3팩터
print(f'  def_3f: rev_accel_z + rev_z + op_margin_z', flush=True)
t1 = time.time()
results = test_3factor('def_3f_raccel_rev_opm', defense_dates, def_weights, 5, 8, 5,
                       'rev_accel_z', 'rev_z', 'op_margin_z', w3_combos)
def_all.extend(results)
print(f'    {len(results)}건 ({time.time()-t1:.0f}s)', flush=True)

print(f'  def_3f: rev_z + oca_z + op_margin_z', flush=True)
t1 = time.time()
results = test_3factor('def_3f_rev_oca_opm', defense_dates, def_weights, 5, 8, 5,
                       'rev_z', 'oca_z', 'op_margin_z', w3_combos)
def_all.extend(results)
print(f'    {len(results)}건 ({time.time()-t1:.0f}s)', flush=True)

def_df = pd.DataFrame(def_all)
def_summary = def_df.groupby('label').agg(
    avg_cal=('calmar', 'mean'), max_cal=('calmar', 'max'),
    avg_cagr=('cagr', 'mean'), count=('calmar', 'count'),
).sort_values('max_cal', ascending=False)

print(f'\n방어 조합별 성과:', flush=True)
for label, r in def_summary.iterrows():
    print(f'  {label:<25} avg_cal={r["avg_cal"]:.3f}  max_cal={r["max_cal"]:.2f}  avg_cagr={r["avg_cagr"]:.1f}%', flush=True)

def_df.to_csv(RESULT_DIR / 'v77_gsub_focused_defense.csv', index=False)

print(f'\n총 소요: {(time.time()-t0)/60:.1f}분', flush=True)

# 텔레그램
try:
    import requests
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
    msg = f'[v77 G서브 집중 분석 완료]\n소요: {(time.time()-t0)/60:.0f}분\n\n'
    msg += '공격 조합별 (max_cal 순):\n'
    for label, r in atk_summary.iterrows():
        msg += f'  {label}: max={r["max_cal"]:.2f} avg={r["avg_cal"]:.3f}\n'
    msg += '\n방어 조합별 (max_cal 순):\n'
    for label, r in def_summary.iterrows():
        msg += f'  {label}: max={r["max_cal"]:.2f} avg={r["avg_cal"]:.3f}\n'
    requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                  data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=30)
except Exception:
    pass
