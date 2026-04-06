"""v76 Phase 2b + 국면서치 + 안정성 + WF
Phase 2a 결과(CSV) 읽어서 후속 단계 실행
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

# 데이터 로드
ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*full*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet').iloc[:,0].dropna()
mc = pd.read_parquet(sorted(DATA_DIR.glob('market_cap_ALL_*.parquet'))[-1])
big = set(mc[mc['시가총액'] >= 1e11].index)
cols = [c for c in ohlcv.columns if c in big]
br = (ohlcv[cols] > ohlcv[cols].rolling(120).mean()).sum(axis=1) / ohlcv[cols].notna().sum(axis=1)

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    rk[d] = json.load(open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8')).get('rankings', [])

tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
print(f'TurboSim init: {time.time()-t0:.1f}초', flush=True)

# Phase 2a 결과 로드
atk_df = pd.read_csv(RESULT_DIR / 'v76_phase2a_attack.csv').sort_values('cal', ascending=False)
def_df = pd.read_csv(RESULT_DIR / 'v76_phase2a_defense.csv').sort_values('cal', ascending=False)
print(f'공격 Top5:', flush=True)
print(atk_df.head(5).to_string(index=False), flush=True)
print(f'방어 Top5:', flush=True)
print(def_df.head(5).to_string(index=False), flush=True)

# 국면 규칙 빌드
def build_regime(dates, signal_series, threshold, confirm):
    mode = False; streak = 0; ss = False; rd = {}
    for d in dates:
        ts = pd.Timestamp(d)
        val = signal_series.get(ts, None)
        s = val >= threshold if val is not None else (mode if isinstance(threshold, float) and threshold < 1 else True)
        if s == ss: streak += 1
        else: streak = 1; ss = s
        if streak >= confirm and mode != s: mode = s
        rd[d] = mode
    return rd

# 국면 규칙 후보
kospi_ma = {n: kospi.rolling(n).mean() for n in [120, 150, 200, 250]}
regime_rules = {}
# 이미 검증된 상위 규칙만 (32개 중 Top 7)
for ma_n in [150, 200]:
    signal = kospi / kospi_ma[ma_n]
    for confirm in [4, 5]:
        name = f'KP_MA{ma_n}_{confirm}d'
        regime_rules[name] = build_regime(dates, signal, 1.0, confirm)

for confirm in [3, 4]:
    name = f'B126_40_{confirm}d'
    regime_rules[name] = build_regime(dates, br, 0.40, confirm)

# KP_MA200_3d 추가 (참고용)
signal200 = kospi / kospi_ma[200]
regime_rules['KP_MA200_3d'] = build_regime(dates, signal200, 1.0, 3)

print(f'\n국면 규칙: {len(regime_rules)}개', flush=True)

# === 국면서치: 공격Top10 x 방어Top10 x 규칙 ===
print(f'\n{"="*50}', flush=True)
print('국면서치: 공격Top10 x 방어Top10 x 규칙', flush=True)
print(f'{"="*50}', flush=True)

atk_top = atk_df.head(5)
def_top = def_df.head(5)

regime_results = []
total = len(atk_top) * len(def_top) * len(regime_rules)
count = 0

for _, a in atk_top.iterrows():
    op = {'v': a['v']/100, 'q': a['q']/100, 'g': a['g']/100, 'm': a['m']/100,
          'g_rev': a['gr'], 'entry': 5, 'exit': 8, 'slots': 3, 'mom': a['mom']}
    for _, d in def_top.iterrows():
        dp = {'v': d['v']/100, 'q': d['q']/100, 'g': d['g']/100, 'm': d['m']/100,
              'g_rev': d['gr'], 'entry': 5, 'exit': 8, 'slots': 7, 'mom': d['mom']}
        for rule_name, rd in regime_rules.items():
            r = tsim.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
            sw = sum(1 for i in range(1, len(dates)) if rd[dates[i]] != rd[dates[i-1]])
            regime_results.append({
                'atk': f"V{int(a['v'])}Q{int(a['q'])}G{int(a['g'])}M{int(a['m'])}g{a['gr']:.1f}{a['mom']}",
                'def': f"V{int(d['v'])}Q{int(d['q'])}G{int(d['g'])}M{int(d['m'])}g{d['gr']:.1f}{d['mom']}",
                'rule': rule_name,
                'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                'sh': r['sharpe'], 'sort': r.get('sortino', 0), 'alpha': r.get('alpha', 0),
                'switches': sw,
            })
            count += 1
    if count % 200 == 0:
        print(f'  {count}/{total} ({time.time()-t0:.0f}초)', flush=True)

rdf = pd.DataFrame(regime_results).sort_values('cal', ascending=False)
rdf.to_csv(RESULT_DIR / 'v76_regime_search.csv', index=False)
print(f'\n국면서치 {len(regime_results)}개 완료 ({time.time()-t0:.0f}초)', flush=True)
print(f'\nTop 10:', flush=True)
print(rdf.head(10).to_string(index=False), flush=True)

# === 슬롯 최적화 (Top3 조합) ===
print(f'\n{"="*50}', flush=True)
print('슬롯 최적화', flush=True)
print(f'{"="*50}', flush=True)

slot_results = []
for _, row in rdf.head(3).iterrows():
    # parse atk/def params from string
    a = atk_top[atk_top.apply(lambda x: f"V{int(x['v'])}Q{int(x['q'])}G{int(x['g'])}M{int(x['m'])}g{x['gr']:.1f}{x['mom']}" == row['atk'], axis=1)]
    d = def_top[def_top.apply(lambda x: f"V{int(x['v'])}Q{int(x['q'])}G{int(x['g'])}M{int(x['m'])}g{x['gr']:.1f}{x['mom']}" == row['def'], axis=1)]
    if a.empty or d.empty:
        continue
    a = a.iloc[0]
    d = d.iloc[0]
    rd = regime_rules[row['rule']]

    for as_ in [2, 3, 4, 5]:
        for ds_ in [3, 4, 5, 6, 7, 8, 9]:
            op = {'v': a['v']/100, 'q': a['q']/100, 'g': a['g']/100, 'm': a['m']/100,
                  'g_rev': a['gr'], 'entry': 5, 'exit': 8, 'slots': as_, 'mom': a['mom']}
            dp_s = {'v': d['v']/100, 'q': d['q']/100, 'g': d['g']/100, 'm': d['m']/100,
                    'g_rev': d['gr'], 'entry': 5, 'exit': 8, 'slots': ds_, 'mom': d['mom']}
            r = tsim.run_regime(dp_s, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
            slot_results.append({
                'combo': f"{row['atk']}|{row['def']}|{row['rule']}",
                'as': as_, 'ds': ds_,
                'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'], 'sh': r['sharpe'],
            })

sdf = pd.DataFrame(slot_results).sort_values('cal', ascending=False)
print(f'슬롯 {len(slot_results)}개:', flush=True)
print(sdf.head(10).to_string(index=False), flush=True)

# === 안정성 + WF (슬롯 Top5 각각) ===
print(f'\n{"="*50}', flush=True)
print('안정성 + Walk-Forward (Top5 조합)', flush=True)
print(f'{"="*50}', flush=True)

final_candidates = []

for rank_idx, (_, row) in enumerate(sdf.head(5).iterrows()):
    parts = row['combo'].split('|')
    rule_name = parts[2]
    as_, ds_ = int(row['as']), int(row['ds'])

    a_match = atk_top[atk_top.apply(lambda x: f"V{int(x['v'])}Q{int(x['q'])}G{int(x['g'])}M{int(x['m'])}g{x['gr']:.1f}{x['mom']}" == parts[0], axis=1)]
    d_match = def_top[def_top.apply(lambda x: f"V{int(x['v'])}Q{int(x['q'])}G{int(x['g'])}M{int(x['m'])}g{x['gr']:.1f}{x['mom']}" == parts[1], axis=1)]
    if a_match.empty or d_match.empty:
        continue
    a = a_match.iloc[0]
    d = d_match.iloc[0]
    rd = regime_rules[rule_name]

    # 인접 안정성
    neighbors = []
    for dv in [-5, 0, 5]:
        for dq in [-5, 0, 5]:
            for dg in [-5, 0, 5]:
                v, q, g = int(a['v'])+dv, int(a['q'])+dq, int(a['g'])+dg
                m = 100-v-q-g
                if v < 0 or q < 0 or g < 0 or m < 0 or m > 100:
                    continue
                op = {'v': v/100, 'q': q/100, 'g': g/100, 'm': m/100,
                      'g_rev': a['gr'], 'entry': 5, 'exit': 8, 'slots': as_, 'mom': a['mom']}
                dp_n = {'v': d['v']/100, 'q': d['q']/100, 'g': d['g']/100, 'm': d['m']/100,
                        'g_rev': d['gr'], 'entry': 5, 'exit': 8, 'slots': ds_, 'mom': d['mom']}
                r = tsim.run_regime(dp_n, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
                    g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
                neighbors.append(r['calmar'])

    cal3 = sum(1 for c in neighbors if c >= 3.0)
    stability = cal3 / len(neighbors) * 100 if neighbors else 0

    # Walk-Forward
    op_wf = {'v': a['v']/100, 'q': a['q']/100, 'g': a['g']/100, 'm': (100-a['v']-a['q']-a['g'])/100,
             'g_rev': a['gr'], 'entry': 5, 'exit': 8, 'slots': as_, 'mom': a['mom']}
    dp_wf = {'v': d['v']/100, 'q': d['q']/100, 'g': d['g']/100, 'm': (100-d['v']-d['q']-d['g'])/100,
             'g_rev': d['gr'], 'entry': 5, 'exit': 8, 'slots': ds_, 'mom': d['mom']}

    wf_cals = []
    for wf_name, val_start, val_end in [('WF1', '20240102', '20241230'), ('WF2', '20250102', '20251230'), ('WF3', '20260102', '20260403')]:
        val_dates = [dd for dd in dates if val_start <= dd <= val_end]
        if len(val_dates) < 20:
            continue
        val_rk = {dd: rk[dd] for dd in val_dates}
        val_rd = {dd: rd[dd] for dd in val_dates}
        tsim_val = TurboSimulator(val_rk, val_dates, ohlcv, bench=bench)
        r = tsim_val.run_regime(dp_wf, op_wf, val_rd, stop_loss=-0.10, trailing_stop=-0.15,
            g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
        wf_cals.append(r['calmar'])

    wf_avg = np.mean(wf_cals) if wf_cals else 0
    wf_min = min(wf_cals) if wf_cals else 0

    print(f'\n#{rank_idx+1} {parts[0]} | {parts[1]} | {rule_name} S{as_}/{ds_}', flush=True)
    print(f'  성과: CAGR={row["cagr"]:.1f}% MDD={row["mdd"]:.1f}% Cal={row["cal"]:.2f}', flush=True)
    print(f'  안정성: {cal3}/{len(neighbors)} ({stability:.0f}%) Cal>=3.0', flush=True)
    print(f'  WF: avg={wf_avg:.2f} min={wf_min:.2f} ({len(wf_cals)}기간)', flush=True)

    final_candidates.append({
        'rank': rank_idx+1, 'atk': parts[0], 'def': parts[1], 'rule': rule_name,
        'as': as_, 'ds': ds_,
        'cagr': row['cagr'], 'mdd': row['mdd'], 'cal': row['cal'], 'sh': row['sh'],
        'stability': stability, 'wf_avg': wf_avg, 'wf_min': wf_min,
    })

# 최종 선택: 안정성 70%+ AND WF min > 0 중 Calmar Top
print(f'\n{"="*50}', flush=True)
print('최종 선택 (안정성 70%+ AND WF min > 0)', flush=True)
print(f'{"="*50}', flush=True)

qualified = [c for c in final_candidates if c['stability'] >= 70 and c['wf_min'] > 0]
if not qualified:
    qualified = [c for c in final_candidates if c['stability'] >= 50]
if not qualified:
    qualified = final_candidates

qualified.sort(key=lambda x: x['cal'], reverse=True)
for c in qualified:
    print(f'  #{c["rank"]} Cal={c["cal"]:.2f} 안정={c["stability"]:.0f}% WF_avg={c["wf_avg"]:.2f} WF_min={c["wf_min"]:.2f} | {c["atk"]} | {c["def"]} | {c["rule"]} S{c["as"]}/{c["ds"]}', flush=True)

best = qualified[0]
print(f'\n*** 최종 확정: #{best["rank"]} ***', flush=True)
print(f'공격: {best["atk"]} S{best["as"]}', flush=True)
print(f'방어: {best["def"]} S{best["ds"]}', flush=True)
print(f'규칙: {best["rule"]}', flush=True)
print(f'CAGR={best["cagr"]:.1f}% MDD={best["mdd"]:.1f}% Cal={best["cal"]:.2f}', flush=True)
print(f'안정성={best["stability"]:.0f}% WF_avg={best["wf_avg"]:.2f} WF_min={best["wf_min"]:.2f}', flush=True)
print(f'\n총 소요: {time.time()-t0:.0f}초', flush=True)
