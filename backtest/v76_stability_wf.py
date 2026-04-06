"""v76 안정성 + Walk-Forward 검증
국면서치 Top10에 대해 인접안정성 + WF 3기간 수행
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
t0 = time.time()

ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*full*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet').iloc[:, 0].dropna()
mc = pd.read_parquet(sorted(DATA_DIR.glob('market_cap_ALL_*.parquet'))[-1])
big = set(mc[mc['시가총액'] >= 1e11].index)
cols = [c for c in ohlcv.columns if c in big]
br = (ohlcv[cols] > ohlcv[cols].rolling(120).mean()).sum(axis=1) / ohlcv[cols].notna().sum(axis=1)

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    rk[d] = json.load(open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8')).get('rankings', [])

tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
print(f'init: {time.time()-t0:.1f}s', flush=True)

# 국면서치 결과 로드
regime_csv = RESULT_DIR / 'v76_regime_final.csv'
rdf = pd.read_csv(regime_csv).sort_values('cal', ascending=False)

# E/X/S 결과 로드 (있으면)
exs_atk_f = RESULT_DIR / 'v76_phase2b_attack_exs.csv'
exs_def_f = RESULT_DIR / 'v76_phase2b_defense_exs.csv'

# 국면 규칙 재빌드
kospi_ma = {n: kospi.rolling(n).mean() for n in [60, 120, 150, 200, 250]}

def build_regime(dates, rule_fn, confirm):
    mode = False; streak = 0; ss = False; rd = {}
    for d in dates:
        ts = pd.Timestamp(d)
        try: s = rule_fn(ts)
        except: s = mode
        if s == ss: streak += 1
        else: streak = 1; ss = s
        if streak >= confirm and mode != s: mode = s
        rd[d] = mode
    return rd

def get_regime_dict(rule_name):
    parts = rule_name.split('_')
    if rule_name.startswith('B126'):
        thresh = int(parts[1]) / 100
        confirm = int(parts[2].replace('d', ''))
        return build_regime(dates, lambda ts, t=thresh: br.get(ts, 0.5) >= t, confirm)
    elif rule_name.startswith('KP_MA'):
        ma_n = int(parts[1].replace('MA', ''))
        confirm = int(parts[2].replace('d', ''))
        ma = kospi_ma[ma_n]
        return build_regime(dates, lambda ts, m=ma: kospi.get(ts, 0) > m.get(ts, 0) if ts in kospi.index else True, confirm)
    elif rule_name.startswith('KK_MA'):
        # KK needs kosdaq too
        return {d: True for d in dates}  # fallback
    return {d: True for d in dates}

def parse_params(param_str):
    """V10Q0G75M15g0.612m-1m -> dict"""
    import re
    m = re.match(r'V(\d+)Q(\d+)G(\d+)M(\d+)g([\d.]+)(.*)', param_str)
    if not m: return None
    v, q, g, mm, gr, mom = int(m[1]), int(m[2]), int(m[3]), int(m[4]), float(m[5]), m[6]
    return {'v': v/100, 'q': q/100, 'g': g/100, 'm': mm/100, 'g_rev': gr, 'mom': mom}

# Top10에 대해 안정성 + WF
print(f'\n=== Top10 안정성 + WF ===', flush=True)
candidates = []

for rank_idx, (_, row) in enumerate(rdf.head(10).iterrows()):
    atk_p = parse_params(row['atk'])
    def_p = parse_params(row['def'])
    if not atk_p or not def_p:
        continue

    rd = get_regime_dict(row['rule'])

    # E/X/S는 Phase 2a 기본값 사용 (E5/X8)
    atk_p.update({'entry': 5, 'exit': 8, 'slots': 3})
    def_p.update({'entry': 5, 'exit': 8, 'slots': 7})

    # 인접안정성 (공격 가중치 ±5)
    neighbors = []
    v0, q0, g0 = int(atk_p['v']*100), int(atk_p['q']*100), int(atk_p['g']*100)
    for dv in [-5, 0, 5]:
        for dq in [-5, 0, 5]:
            for dg in [-5, 0, 5]:
                v, q, g = v0+dv, q0+dq, g0+dg
                m = 100-v-q-g
                if v < 0 or q < 0 or g < 0 or m < 0 or m > 100: continue
                op = dict(atk_p); op['v'], op['q'], op['g'], op['m'] = v/100, q/100, g/100, m/100
                r = tsim.run_regime(def_p, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
                    g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
                neighbors.append(r['calmar'])

    cal3 = sum(1 for c in neighbors if c >= 3.0)
    stability = cal3 / len(neighbors) * 100 if neighbors else 0

    # Walk-Forward 3기간
    wf_results = []
    for wf_name, vs, ve in [('2024', '20240102', '20241230'), ('2025', '20250102', '20251230'), ('2026', '20260102', '20260403')]:
        vd = [d for d in dates if vs <= d <= ve]
        if len(vd) < 20: continue
        vrk = {d: rk[d] for d in vd}
        vrd = {d: rd[d] for d in vd}
        tv = TurboSimulator(vrk, vd, ohlcv, bench=bench)
        r = tv.run_regime(def_p, atk_p, vrd, stop_loss=-0.10, trailing_stop=-0.15,
            g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
        wf_results.append({'period': wf_name, 'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']})

    wf_avg = np.mean([w['cal'] for w in wf_results]) if wf_results else 0
    wf_min = min([w['cal'] for w in wf_results]) if wf_results else 0

    print(f'\n#{rank_idx+1} {row["atk"]} | {row["def"]} | {row["rule"]}', flush=True)
    print(f'  Cal={row["cal"]:.2f} CAGR={row["cagr"]:.1f}% MDD={row["mdd"]:.1f}%', flush=True)
    print(f'  안정성: {cal3}/{len(neighbors)} ({stability:.0f}%)', flush=True)
    for w in wf_results:
        print(f'  WF {w["period"]}: Cal={w["cal"]:.2f} CAGR={w["cagr"]:.1f}%', flush=True)
    print(f'  WF avg={wf_avg:.2f} min={wf_min:.2f}', flush=True)

    candidates.append({
        'rank': rank_idx+1, 'atk': row['atk'], 'def': row['def'], 'rule': row['rule'],
        'cal': row['cal'], 'cagr': row['cagr'], 'mdd': row['mdd'],
        'sh': row['sh'], 'sort': row.get('sort', 0), 'alpha': row.get('alpha', 0),
        'stability': stability, 'wf_avg': wf_avg, 'wf_min': wf_min,
    })

# 최종 선택
print(f'\n{"="*60}', flush=True)
print('최종 후보 (안정성 70%+ AND WF_min > 0, Calmar순)', flush=True)
print(f'{"="*60}', flush=True)

qualified = [c for c in candidates if c['stability'] >= 70 and c['wf_min'] > 0]
if not qualified:
    qualified = [c for c in candidates if c['stability'] >= 50]
if not qualified:
    qualified = candidates

qualified.sort(key=lambda x: x['cal'], reverse=True)
for c in qualified:
    print(f'  #{c["rank"]} Cal={c["cal"]:.2f} stab={c["stability"]:.0f}% WF={c["wf_avg"]:.2f}/{c["wf_min"]:.2f} | {c["atk"]} | {c["def"]} | {c["rule"]}', flush=True)

best = qualified[0]
print(f'\n*** v76 최종 확정 ***', flush=True)
print(f'공격: {best["atk"]}', flush=True)
print(f'방어: {best["def"]}', flush=True)
print(f'규칙: {best["rule"]}', flush=True)
print(f'CAGR={best["cagr"]:.1f}% MDD={best["mdd"]:.1f}% Cal={best["cal"]:.2f} Sh={best["sh"]:.2f}', flush=True)
print(f'안정성={best["stability"]:.0f}% WF_avg={best["wf_avg"]:.2f} WF_min={best["wf_min"]:.2f}', flush=True)
print(f'\n총: {time.time()-t0:.0f}s', flush=True)
