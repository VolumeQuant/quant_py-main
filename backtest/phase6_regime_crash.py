"""Phase 6: 국면 규칙 + Crash Cash 탐색
Top 15 공격 후보 × 국면 규칙

입력: phase5_grid_attack.py의 Top 15
"""
import sys, os, time, json, glob
from pathlib import Path
sys.path.insert(0, 'C:/dev/backtest')
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator


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


STATE = Path('C:/dev/state')
STATE_D = STATE / 'defense'
BT_EXT = Path('C:/dev/backtest/bt_extended')
BT_EXT_D = Path('C:/dev/backtest/bt_extended_defense')

print('ranking 로드...', flush=True)
boost_rankings = load_rankings([BT_EXT, STATE])
defense_rankings = load_rankings([BT_EXT_D, STATE_D])
dates = sorted(set(boost_rankings.keys()) & set(defense_rankings.keys()))
print(f'공통: {len(dates)}일', flush=True)

ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

# KOSPI for regime
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()


def make_regime(confirm_days=5, crash_threshold=None):
    """KOSPI > MA200, N일 확인. crash_threshold if 20일 수익률 < threshold → cash"""
    reg = {}
    md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = ma200.get(ts)
        if kv is None or mv is None or pd.isna(mv):
            reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm_days and md != s:
            md = s
        reg[d] = md
    return reg


# Top 15 공격 후보 (phase5a 결과)
try:
    attack_grid = pd.read_csv('C:/dev/backtest/phase5a_attack_grid.csv')
    top15 = attack_grid.head(15).to_dict('records')
    print(f'Top 15 공격 후보 로드', flush=True)
except FileNotFoundError:
    print('phase5a_attack_grid.csv 없음 — phase5_grid_attack.py 먼저 실행!', flush=True)
    sys.exit(1)

tsim_boost = TurboSimulator(boost_rankings, dates, ohlcv)

# 방어 기본값 (v77.1)
DEFENSE_DEFAULT = {
    'v':0.30, 'q':0.05, 'g':0.10, 'm':0.55, 'g_rev':0.5,
    'entry':3, 'exit':6, 'slots':7, 'mom':'6m-1m'
}

# 국면 규칙 후보
regime_rules = [
    ('attack_only', None, None),
    ('MA200_5d', 5, None),
    ('MA200_7d', 7, None),
    ('MA200_10d', 10, None),
]

results = []
for i, offense in enumerate(top15):
    ofs = {
        'v': offense['V']/100, 'q': offense['Q']/100, 'g': offense['G']/100, 'm': offense['M']/100,
        'g_rev': 0.5 if offense['gs'].startswith('3f') else 0.7,
        'entry': 5, 'exit': 8, 'slots': 5,  # E/X/S 기본 — Phase 2b에서 재서치
        'mom': offense['mom']
    }
    g_sub3 = 'gp_growth_z' if offense['gs'].startswith('3f') else None
    g_w1 = 0.5 if offense['gs'].startswith('3f') else None
    g_w2 = 0.3 if offense['gs'].startswith('3f') else None
    g_w3 = 0.2 if offense['gs'].startswith('3f') else None

    for rule_name, confirm, crash in regime_rules:
        if rule_name == 'attack_only':
            regime = {d: True for d in dates}
        else:
            regime = make_regime(confirm_days=confirm, crash_threshold=crash)

        try:
            r = tsim_boost.run_regime(
                defense_params=DEFENSE_DEFAULT, offense_params=ofs,
                regime_dict=regime, trailing_stop=-0.15,
                g_sub1_o='rev_z', g_sub2_o='oca_z',
                g_sub3_o=g_sub3, g_w1_o=g_w1, g_w2_o=g_w2, g_w3_o=g_w3,
                g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z',
            )
            results.append({
                'candidate_idx': i,
                'V': offense['V'], 'Q': offense['Q'], 'G': offense['G'], 'M': offense['M'],
                'mom': offense['mom'], 'gs': offense['gs'],
                'regime': rule_name,
                'cagr': r.get('cagr', 0), 'mdd': r.get('mdd', 0),
                'calmar': r.get('calmar', 0),
            })
        except Exception as e:
            print(f'  [{i}] {rule_name}: ERR {str(e)[:60]}', flush=True)

df = pd.DataFrame(results)
df = df.sort_values('calmar', ascending=False)
df.to_csv('C:/dev/backtest/phase6_regime_grid.csv', index=False, encoding='utf-8-sig')
print(f'\n=== Phase 6 Top 15 ===')
print(df.head(15).to_string(index=False))
