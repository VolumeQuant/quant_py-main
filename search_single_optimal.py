"""단일 최적 전략 탐색 + 국면 분석 + Walk-Forward"""
import sys, io, json, glob, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main/backtest')

import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, TurboRunner

PROJECT = Path('C:/dev/claude-code/quant_py-main')
CACHE_DIR = PROJECT / 'data_cache'

_ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
_full_files = [f for f in _ohlcv_files if '_full' in f.stem]
if _full_files:
    _ohlcv_files = _full_files
prices = pd.read_parquet(
    sorted(_ohlcv_files, key=lambda f: f.stem.split('_')[2])[0]
).replace(0, np.nan)

# bt_2b (rev_accel)
bt2b_r = {}
for fp in sorted((PROJECT / 'state' / 'bt_2b').glob('ranking_*.json')):
    d = fp.stem.replace('ranking_', '')
    with open(fp, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    bt2b_r[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt2b_d = sorted(bt2b_r.keys())

# 일반 bt
bt_r = {}
for y in range(2021, 2026):
    for fp in sorted((PROJECT / 'state' / f'bt_{y}').glob('ranking_*.json')):
        d = fp.stem.replace('ranking_', '')
        with open(fp, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        bt_r[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt_d = sorted(bt_r.keys())

# Regime
regime_df = pd.read_parquet(CACHE_DIR / 'regime_daily.parquet')
regime_map = {}
for idx, row in regime_df.iterrows():
    d = idx.strftime('%Y%m%d')
    q = row.get('quadrant')
    vr = row.get('vix_regime')
    if q and vr:
        regime_map[d] = (q, vr)

tsim_2b = TurboSimulator(bt2b_r, bt2b_d, prices)
tsim_bt = TurboSimulator(bt_r, bt_d, prices)

t0 = time.time()

def fmt(r):
    return f"CAGR={r['cagr']:>+6.1f}% MDD={r['mdd']:>5.1f}% Calmar={r['calmar']:>5.2f} Sharpe={r['sharpe']:>5.2f}"

# ============================================================
# PART 1: 국면별 Core vs Boost 성과
# ============================================================
print('=' * 60)
print('  PART 1: 국면별 Core vs Boost')
print('=' * 60)

for q_name in ['Q1', 'Q2', 'Q3', 'Q4']:
    q_dates_2b = [d for d in bt2b_d if regime_map.get(d, (None,))[0] == q_name]
    q_dates_bt = [d for d in bt_d if regime_map.get(d, (None,))[0] == q_name]
    if len(q_dates_2b) < 20:
        print(f'  {q_name}: 데이터 부족 ({len(q_dates_2b)}일)')
        continue

    q_r_2b = {d: bt2b_r[d] for d in q_dates_2b}
    q_r_bt = {d: bt_r[d] for d in q_dates_bt if d in bt_r}

    ts_c = TurboSimulator(q_r_2b, q_dates_2b, prices)
    ts_c._ensure_cache(0.25, 0.20, 0.35, 0.20, 0.2, 20)
    rc = TurboRunner(ts_c)
    r_c = rc.run(5, 7, 5, corr_threshold=0.5)

    if len(q_dates_bt) >= 20:
        ts_b = TurboSimulator(q_r_bt, q_dates_bt, prices)
        ts_b._ensure_cache(0.15, 0.05, 0.65, 0.15, 1.0, 20)
        rb = TurboRunner(ts_b)
        r_b = rb.run(3, 4, 3, corr_threshold=None)
        print(f'  {q_name} ({len(q_dates_2b)}일):')
        print(f'    Core:  {fmt(r_c)}')
        print(f'    Boost: {fmt(r_b)}')
    else:
        print(f'  {q_name} ({len(q_dates_2b)}일): Core only {fmt(r_c)}')

# ============================================================
# PART 2: 단일 전략 대규모 탐색
# ============================================================
print('\n' + '=' * 60)
print('  PART 2: 단일 전략 대규모 탐색')
print('=' * 60)

results = []
count = 0

# bt_2b 기반
for v in [20, 25, 30]:
    for q in [10, 15, 20, 25]:
        for g in [25, 30, 35, 40, 45, 50]:
            m = 100 - v - q - g
            if m < 10 or m > 35:
                continue
            for g_rev in [0.0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]:
                tsim_2b._ensure_cache(v/100, q/100, g/100, m/100, g_rev, 20)
                runner = TurboRunner(tsim_2b)
                for entry in [3, 4, 5]:
                    for exit_ in [5, 6, 7, 8, 10]:
                        if exit_ <= entry:
                            continue
                        for slots in [3, 4, 5]:
                            if entry > slots:
                                continue
                            for corr in [None, 0.5]:
                                r = runner.run(entry, exit_, slots, corr_threshold=corr)
                                count += 1
                                if r['cagr'] > 50 and r['calmar'] > 2.0:
                                    results.append({
                                        'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev,
                                        'entry': entry, 'exit': exit_, 'slots': slots,
                                        'corr': corr, 'bt': '2b', **r
                                    })

# 일반 bt (g_rev=1.0)
for v in [20, 25, 30]:
    for q in [5, 10, 15, 20]:
        for g in [30, 40, 50, 60]:
            m = 100 - v - q - g
            if m < 10 or m > 35:
                continue
            tsim_bt._ensure_cache(v/100, q/100, g/100, m/100, 1.0, 20)
            runner = TurboRunner(tsim_bt)
            for entry in [3, 4, 5]:
                for exit_ in [4, 5, 6, 7, 8]:
                    if exit_ <= entry:
                        continue
                    for slots in [3, 4, 5]:
                        if entry > slots:
                            continue
                        for corr in [None, 0.5]:
                            r = runner.run(entry, exit_, slots, corr_threshold=corr)
                            count += 1
                            if r['cagr'] > 50 and r['calmar'] > 2.0:
                                results.append({
                                    'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': 1.0,
                                    'entry': entry, 'exit': exit_, 'slots': slots,
                                    'corr': corr, 'bt': 'normal', **r
                                })

print(f'총 테스트: {count}개, 후보: {len(results)}개 (CAGR>50% & Calmar>2.0)')

# Calmar Top 20
results.sort(key=lambda x: -x['calmar'])
print(f'\n=== Calmar Top 20 ===')
hdr = f"{'#':>3} {'weights':<16} {'g_rev':>5} {'E':>2}{'X':>3}{'S':>2} {'corr':>5} {'bt':>4} {'CAGR':>7} {'MDD':>6} {'Calmar':>7} {'Sharpe':>7}"
print(hdr)
print('-' * len(hdr))
for i, r in enumerate(results[:20]):
    w = f"V{r['v']}Q{r['q']}G{r['g']}M{r['m']}"
    c = str(r['corr']) if r['corr'] else 'None'
    print(f"{i+1:>3} {w:<16} {r['g_rev']:>5.2f} {r['entry']:>2}{r['exit']:>3}{r['slots']:>2} {c:>5} {r['bt']:>4} {r['cagr']:>+6.1f}% {r['mdd']:>5.1f}% {r['calmar']:>7.2f} {r['sharpe']:>7.2f}")

# CAGR Top 20
results_cagr = sorted(results, key=lambda x: -x['cagr'])
print(f'\n=== CAGR Top 20 ===')
print(hdr)
print('-' * len(hdr))
for i, r in enumerate(results_cagr[:20]):
    w = f"V{r['v']}Q{r['q']}G{r['g']}M{r['m']}"
    c = str(r['corr']) if r['corr'] else 'None'
    print(f"{i+1:>3} {w:<16} {r['g_rev']:>5.02f} {r['entry']:>2}{r['exit']:>3}{r['slots']:>2} {c:>5} {r['bt']:>4} {r['cagr']:>+6.1f}% {r['mdd']:>5.1f}% {r['calmar']:>7.2f} {r['sharpe']:>7.2f}")

# 황금 조합
golden = [r for r in results if r['cagr'] >= 80 and r['mdd'] <= 25 and r['calmar'] >= 3.0]
golden.sort(key=lambda x: -x['calmar'])
print(f'\n=== 황금 (CAGR>=80 & MDD<=25 & Calmar>=3.0): {len(golden)}개 ===')
for i, r in enumerate(golden[:10]):
    w = f"V{r['v']}Q{r['q']}G{r['g']}M{r['m']}"
    c = str(r['corr']) if r['corr'] else 'None'
    print(f"  {w} g={r['g_rev']} E{r['entry']}/X{r['exit']}/S{r['slots']} corr={c} bt={r['bt']}: CAGR={r['cagr']:+.1f}% MDD={r['mdd']:.1f}% Calmar={r['calmar']:.2f}")

if not golden:
    relaxed = [r for r in results if r['cagr'] >= 70 and r['mdd'] <= 28 and r['calmar'] >= 2.8]
    relaxed.sort(key=lambda x: -x['calmar'])
    print(f'  조건 완화 (CAGR>=70 & MDD<=28 & Calmar>=2.8): {len(relaxed)}개')
    for i, r in enumerate(relaxed[:10]):
        w = f"V{r['v']}Q{r['q']}G{r['g']}M{r['m']}"
        c = str(r['corr']) if r['corr'] else 'None'
        print(f"  {w} g={r['g_rev']} E{r['entry']}/X{r['exit']}/S{r['slots']} corr={c}: CAGR={r['cagr']:+.1f}% MDD={r['mdd']:.1f}% Calmar={r['calmar']:.2f}")

# ============================================================
# PART 3: Walk-Forward Top 5
# ============================================================
print('\n' + '=' * 60)
print('  PART 3: Walk-Forward')
print('=' * 60)

wf_list = [
    ('CoreV25', bt2b_r, bt2b_d, 0.25, 0.20, 0.35, 0.20, 0.2, 5, 7, 5, 0.5),
    ('Boost', bt_r, bt_d, 0.15, 0.05, 0.65, 0.15, 1.0, 3, 4, 3, None),
]
for i, r in enumerate(results[:3]):
    rk = bt2b_r if r['bt'] == '2b' else bt_r
    dk = bt2b_d if r['bt'] == '2b' else bt_d
    wf_list.append((f"Cal{i+1}", rk, dk, r['v']/100, r['q']/100, r['g']/100, r['m']/100,
                     r['g_rev'], r['entry'], r['exit'], r['slots'], r['corr']))
if golden:
    r = golden[0]
    rk = bt2b_r if r['bt'] == '2b' else bt_r
    dk = bt2b_d if r['bt'] == '2b' else bt_d
    wf_list.append(('Golden1', rk, dk, r['v']/100, r['q']/100, r['g']/100, r['m']/100,
                     r['g_rev'], r['entry'], r['exit'], r['slots'], r['corr']))

years = [('2021', '20210104', '20211230'), ('2022', '20220103', '20221229'),
         ('2023', '20230102', '20231228'), ('2024', '20240102', '20241230'),
         ('2025', '20250102', '20251230'), ('2026', '20260102', '20260320')]

print(f"\n{'strat':<10}", end='')
for yr, _, _ in years:
    print(f' {yr:>8}', end='')
print(f" {'total':>8}")
print('-' * 70)

for name, rankings, dates, v, q, g, m, g_rev, entry, exit_, slots, corr in wf_list:
    print(f'{name:<10}', end='')
    for yr, start, end in years:
        yr_dates = [d for d in dates if start <= d <= end]
        yr_rankings = {d: rankings[d] for d in yr_dates if d in rankings}
        if len(yr_dates) < 10:
            print(f" {'N/A':>8}", end='')
            continue
        ts = TurboSimulator(yr_rankings, yr_dates, prices)
        ts._ensure_cache(v, q, g, m, g_rev, 20)
        rr = TurboRunner(ts)
        r = rr.run(entry, exit_, slots, corr_threshold=corr)
        print(f' {r["cagr"]:>+7.1f}%', end='')
    ts = TurboSimulator(rankings, dates, prices)
    ts._ensure_cache(v, q, g, m, g_rev, 20)
    rr = TurboRunner(ts)
    r = rr.run(entry, exit_, slots, corr_threshold=corr)
    print(f' {r["cagr"]:>+7.1f}%')

# MDD
print(f"\n{'MDD':<10}", end='')
for yr, _, _ in years:
    print(f' {yr:>8}', end='')
print(f" {'total':>8}")
print('-' * 70)

for name, rankings, dates, v, q, g, m, g_rev, entry, exit_, slots, corr in wf_list:
    print(f'{name:<10}', end='')
    for yr, start, end in years:
        yr_dates = [d for d in dates if start <= d <= end]
        yr_rankings = {d: rankings[d] for d in yr_dates if d in rankings}
        if len(yr_dates) < 10:
            print(f" {'N/A':>8}", end='')
            continue
        ts = TurboSimulator(yr_rankings, yr_dates, prices)
        ts._ensure_cache(v, q, g, m, g_rev, 20)
        rr = TurboRunner(ts)
        r = rr.run(entry, exit_, slots, corr_threshold=corr)
        print(f' {r["mdd"]:>7.1f}%', end='')
    ts = TurboSimulator(rankings, dates, prices)
    ts._ensure_cache(v, q, g, m, g_rev, 20)
    rr = TurboRunner(ts)
    r = rr.run(entry, exit_, slots, corr_threshold=corr)
    print(f' {r["mdd"]:>7.1f}%')

elapsed = (time.time() - t0) / 60
print(f'\n소요: {elapsed:.1f}분')
print('완료!')
