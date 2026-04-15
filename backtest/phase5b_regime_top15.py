"""Phase 5b/6: Top 15 공격 후보 × 국면전환 × Crash Cash
5.25년 + 7.8년 평가
Phase 5a 결과 (Top 15) 로드하여 각각 regime 적용 후 비교
"""
import sys, os, json, glob
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

print('로딩...', flush=True)
boost_rd = load_rankings([BT_EXT, STATE])
defense_rd = load_rankings([BT_EXT_D, STATE_D])
dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
defense_rk = {d: defense_rd[d]['rankings'] for d in dates}
sub_dates = [d for d in dates if '20210104' <= d <= '20260414']
print(f'7.8년: {len(dates)}, 5.25년: {len(sub_dates)}')

ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

# KOSPI regime
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()

def calc_regime(target_dates, confirm=5):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma200.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg

# Top 15 로드
top15 = pd.read_csv('C:/dev/backtest/phase5a_attack_grid.csv').head(15).to_dict('records')

# TurboSim 2개 (7.8년 / 5.25년)
tsim_78 = TurboSimulator(boost_rk, dates, ohlcv)
tsim_525 = TurboSimulator({d: boost_rk[d] for d in sub_dates}, sub_dates, ohlcv)

# 방어 기본값 (v77.1)
DEFENSE_V77_1 = {'v':0.30,'q':0.05,'g':0.10,'m':0.55,'g_rev':0.5,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}

# 국면 규칙 3종
regimes_78 = {
    'attack_only': {d: True for d in dates},
    'MA200_5d': calc_regime(dates, 5),
    'MA200_7d': calc_regime(dates, 7),
}
regimes_525 = {
    'attack_only': {d: True for d in sub_dates},
    'MA200_5d': calc_regime(sub_dates, 5),
    'MA200_7d': calc_regime(sub_dates, 7),
}

def g_sub_params(gs):
    if gs == '3f_rev_oca_gp':
        return ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
    elif gs == '3f_rev_oca_opm':
        return ('rev_z','oca_z','op_margin_z',0.5,0.3,0.2)
    elif gs == '2f_rev_oca_0.7':
        return ('rev_z','oca_z',None,None,None,None)

print('\n=== Top 15 × 국면 규칙 × (5.25년, 7.8년) ===')
results = []
import time
t0 = time.time()

for i, c in enumerate(top15):
    ofs = {'v':c['V']/100, 'q':c['Q']/100, 'g':c['G']/100, 'm':c['M']/100,
           'g_rev':0.5 if '3f' in c['gs'] else 0.7,
           'entry':5, 'exit':8, 'slots':5, 'mom':c['mom']}
    gs = g_sub_params(c['gs'])

    for rule_name in ['attack_only', 'MA200_5d', 'MA200_7d']:
        # 7.8년
        try:
            if rule_name == 'attack_only':
                r78 = tsim_78.run_fast(
                    v_w=ofs['v'], q_w=ofs['q'], g_w=ofs['g'], m_w=ofs['m'], g_rev=ofs['g_rev'],
                    entry_param=5, exit_param=8, max_slots=5, mom_type=ofs['mom'], trailing_stop=-0.15,
                    g_sub1=gs[0], g_sub2=gs[1], g_sub3=gs[2], g_w1=gs[3], g_w2=gs[4], g_w3=gs[5],
                )
            else:
                r78 = tsim_78.run_regime(
                    defense_params=DEFENSE_V77_1, offense_params=ofs,
                    regime_dict=regimes_78[rule_name], trailing_stop=-0.15,
                    g_sub1_o=gs[0], g_sub2_o=gs[1], g_sub3_o=gs[2],
                    g_w1_o=gs[3], g_w2_o=gs[4], g_w3_o=gs[5],
                    g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z',
                )
            # 5.25년
            if rule_name == 'attack_only':
                r525 = tsim_525.run_fast(
                    v_w=ofs['v'], q_w=ofs['q'], g_w=ofs['g'], m_w=ofs['m'], g_rev=ofs['g_rev'],
                    entry_param=5, exit_param=8, max_slots=5, mom_type=ofs['mom'], trailing_stop=-0.15,
                    g_sub1=gs[0], g_sub2=gs[1], g_sub3=gs[2], g_w1=gs[3], g_w2=gs[4], g_w3=gs[5],
                )
            else:
                r525 = tsim_525.run_regime(
                    defense_params=DEFENSE_V77_1, offense_params=ofs,
                    regime_dict=regimes_525[rule_name], trailing_stop=-0.15,
                    g_sub1_o=gs[0], g_sub2_o=gs[1], g_sub3_o=gs[2],
                    g_w1_o=gs[3], g_w2_o=gs[4], g_w3_o=gs[5],
                    g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z',
                )
            results.append({
                'rank': i+1, 'V':c['V'],'Q':c['Q'],'G':c['G'],'M':c['M'],
                'mom':c['mom'], 'gs':c['gs'], 'regime':rule_name,
                'cal_78': r78['calmar'], 'cagr_78': r78['cagr'], 'mdd_78': r78['mdd'],
                'cal_525': r525['calmar'], 'cagr_525': r525['cagr'], 'mdd_525': r525['mdd'],
            })
        except Exception as e:
            print(f'  [{i}] {rule_name}: ERR {str(e)[:50]}', flush=True)

df = pd.DataFrame(results)
# 종합 점수: 5.25y Cal * 0.5 + 7.8y Cal * 0.5
df['score'] = df['cal_525']*0.5 + df['cal_78']*0.5
df = df.sort_values('score', ascending=False)
df.to_csv('C:/dev/backtest/phase5b_regime_grid.csv', index=False, encoding='utf-8-sig')

print(f'\n=== 종합 Top 15 (5.25y*0.5 + 7.8y*0.5) ===')
print(df.head(15).to_string(index=False))
print(f'\n총 소요: {(time.time()-t0)/60:.1f}분')
