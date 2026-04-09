"""v77 G서브팩터 서치 — 15쌍 × 11비율 × 대표가중치 20개 × 4mom

Step 1: G서브 최적 쌍+비율 찾기
Step 2 (별도): Phase 2a에서 최적 G서브 고정 → 전체 가중치 서치
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from itertools import combinations
from turbo_simulator import TurboSimulator

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
RESULT_DIR.mkdir(exist_ok=True)
t0 = time.time()

# ── 데이터 로드 ──
ohlcv_files = sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))
ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

# ── 국면 분리 ──
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
print(f'전체: {len(dates)}일, 공격: {len(boost_dates)}일, 방어: {len(defense_dates)}일', flush=True)

# ── G 서브팩터 15쌍 ──
g_sub_names = ['rev_z', 'oca_z', 'rev_accel_z', 'gp_growth_z', 'op_margin_z', 'cfo_growth_z']
g_sub_pairs = list(combinations(g_sub_names, 2))
g_revs = [round(x * 0.1, 1) for x in range(11)]  # 0.0 ~ 1.0 step 0.1
print(f'G서브: {len(g_sub_pairs)}쌍 × {len(g_revs)}비율 = {len(g_sub_pairs) * len(g_revs)}세팅', flush=True)

# ── 대표 가중치 20개 (유니버스 무관, 다양한 팩터 비중 패턴) ──
repr_weights = [
    # V 중심
    (40, 10, 30, 20), (35, 15, 25, 25), (30, 10, 30, 30),
    # Q 중심
    (10, 40, 30, 20), (15, 35, 25, 25), (20, 30, 20, 30),
    # G 중심
    (10, 10, 60, 20), (15, 5, 50, 30), (5, 5, 70, 20), (10, 10, 55, 25),
    # M 중심
    (10, 10, 20, 60), (15, 10, 20, 55), (10, 5, 25, 60), (20, 10, 15, 55),
    # 균등
    (25, 25, 25, 25), (20, 20, 30, 30), (20, 20, 20, 40),
    # V+G, Q+M 등 투팩터 편중
    (30, 5, 50, 15), (5, 30, 15, 50), (15, 15, 45, 25),
]
mom_types = ['6m', '6m-1m', '12m', '12m-1m']

total_per_mode = len(g_sub_pairs) * len(g_revs) * len(repr_weights) * len(mom_types)
print(f'대표 가중치: {len(repr_weights)}개, 모멘텀: {len(mom_types)}')
print(f'총 조합: {total_per_mode}개/모드', flush=True)

# ── 서치 함수 ──
def search_gsub(mode_dates, mode_name, entry=5, exit_r=8, slots=3):
    rk_mode = {d: rk[d] for d in mode_dates}
    tsim = TurboSimulator(rk_mode, mode_dates, ohlcv, bench=bench)

    results = []
    done = 0
    total = len(g_sub_pairs) * len(g_revs)
    t1 = time.time()

    for gs1, gs2 in g_sub_pairs:
        for gr in g_revs:
            for v, q, g, m in repr_weights:
                for mom in mom_types:
                    r = tsim.run_fast(v/100, q/100, g/100, m/100, gr,
                                     entry_param=entry, exit_param=exit_r, max_slots=slots,
                                     mom_type=mom, stop_loss=-0.10, trailing_stop=-0.15,
                                     g_sub1=gs1, g_sub2=gs2)
                    results.append({
                        'gs1': gs1, 'gs2': gs2, 'gr': gr,
                        'v': v, 'q': q, 'g': g, 'm': m, 'mom': mom,
                        'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                        'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                    })
            done += 1
            if done % 30 == 0:
                elapsed = time.time() - t1
                rate = done / elapsed if elapsed > 0 else 1
                remain = (total - done) / rate / 60
                print(f'  [{mode_name}] {done}/{total} ({elapsed/60:.1f}분, 남은 ~{remain:.1f}분)', flush=True)

    df = pd.DataFrame(results)

    # 쌍+비율별 평균 Calmar (가중치/모멘텀 평균)
    summary = df.groupby(['gs1', 'gs2', 'gr']).agg(
        avg_cal=('cal', 'mean'),
        max_cal=('cal', 'max'),
        avg_cagr=('cagr', 'mean'),
        count=('cal', 'count'),
    ).reset_index().sort_values('avg_cal', ascending=False)

    # 쌍별 최적 비율
    pair_best = df.groupby(['gs1', 'gs2']).agg(
        best_cal=('cal', 'max'),
        avg_cal=('cal', 'mean'),
    ).reset_index().sort_values('best_cal', ascending=False)

    return df, summary, pair_best


# ── 공격 모드 ──
print(f'\n{"="*70}', flush=True)
print(f'G서브 서치: 공격 모드 (E5/X8/S3, {len(boost_dates)}일)', flush=True)
print(f'{"="*70}', flush=True)

atk_all, atk_summary, atk_pairs = search_gsub(boost_dates, '공격', entry=5, exit_r=8, slots=3)
atk_all.to_csv(RESULT_DIR / 'v77_gsub_attack_all.csv', index=False)
atk_summary.to_csv(RESULT_DIR / 'v77_gsub_attack_summary.csv', index=False)

print(f'\n공격 — 쌍별 최고 Calmar:', flush=True)
for _, r in atk_pairs.head(10).iterrows():
    print(f'  {r["gs1"]:<15} + {r["gs2"]:<15} best_cal={r["best_cal"]:.2f}  avg_cal={r["avg_cal"]:.2f}', flush=True)

print(f'\n공격 — 쌍+비율 Top 10:', flush=True)
for _, r in atk_summary.head(10).iterrows():
    print(f'  {r["gs1"]:<15} + {r["gs2"]:<15} gr={r["gr"]:.1f}  avg_cal={r["avg_cal"]:.2f}  max_cal={r["max_cal"]:.2f}', flush=True)


# ── 방어 모드 ──
print(f'\n{"="*70}', flush=True)
print(f'G서브 서치: 방어 모드 (E5/X8/S5, {len(defense_dates)}일)', flush=True)
print(f'{"="*70}', flush=True)

def_all, def_summary, def_pairs = search_gsub(defense_dates, '방어', entry=5, exit_r=8, slots=5)
def_all.to_csv(RESULT_DIR / 'v77_gsub_defense_all.csv', index=False)
def_summary.to_csv(RESULT_DIR / 'v77_gsub_defense_summary.csv', index=False)

print(f'\n방어 — 쌍별 최고 Calmar:', flush=True)
for _, r in def_pairs.head(10).iterrows():
    print(f'  {r["gs1"]:<15} + {r["gs2"]:<15} best_cal={r["best_cal"]:.2f}  avg_cal={r["avg_cal"]:.2f}', flush=True)

print(f'\n방어 — 쌍+비율 Top 10:', flush=True)
for _, r in def_summary.head(10).iterrows():
    print(f'  {r["gs1"]:<15} + {r["gs2"]:<15} gr={r["gr"]:.1f}  avg_cal={r["avg_cal"]:.2f}  max_cal={r["max_cal"]:.2f}', flush=True)


print(f'\n총 소요: {(time.time()-t0)/60:.1f}분', flush=True)

# 텔레그램 알림
try:
    import requests
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
    atk_top = atk_pairs.iloc[0]
    def_top = def_pairs.iloc[0]
    msg = (f'[v77 G서브 서치 완료]\n'
           f'공격: {atk_top["gs1"]}+{atk_top["gs2"]} cal={atk_top["best_cal"]:.2f}\n'
           f'방어: {def_top["gs1"]}+{def_top["gs2"]} cal={def_top["best_cal"]:.2f}\n'
           f'소요: {(time.time()-t0)/60:.0f}분')
    requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                  data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=10)
except Exception:
    pass
