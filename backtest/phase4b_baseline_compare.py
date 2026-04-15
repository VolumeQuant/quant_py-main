"""Phase 4b: 수정본 BT로 v77.1, v77 기존, v78, v78 attack-only 비교

이전 단계 인사이트 반영:
- 수정본으로 v77.1 Cal 4.58→2.59 (-43%) 하락
- 원인 분리: PIT / price ffill / 유니버스 확대

목적: 어느 파라미터가 수정본 데이터에서 최고인지 확인 → Phase 5 중심점 결정
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
print(f'공통: {len(dates)}일')

ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

# KOSPI regime
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()

def calc_regime(confirm=5, attack_only=False):
    if attack_only:
        return {d: True for d in dates}
    reg = {}; md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma200.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg

tsim = TurboSimulator(boost_rk, dates, ohlcv)

# 후보 전략
candidates = [
    # (label, offense, defense, g_sub_o, g_sub_d, attack_only, confirm)
    ('v77.1 (V5Q0G65M30,gp,12m-1m,E7X8S3)',
     {'v':0.05,'q':0.00,'g':0.65,'m':0.30,'g_rev':0.5,'entry':7,'exit':8,'slots':3,'mom':'12m-1m'},
     {'v':0.30,'q':0.05,'g':0.10,'m':0.55,'g_rev':0.5,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'},
     ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2),
     ('rev_accel_z','op_margin_z',None,None,None,None),
     False, 5),
    ('v78 regime (V20Q0G45M35,opm,12m,E10X11S5)',
     {'v':0.20,'q':0.00,'g':0.45,'m':0.35,'g_rev':0.5,'entry':10,'exit':11,'slots':5,'mom':'12m'},
     {'v':0.30,'q':0.15,'g':0.25,'m':0.30,'g_rev':0.7,'entry':3,'exit':4,'slots':5,'mom':'6m'},
     ('rev_z','oca_z','op_margin_z',0.5,0.3,0.2),
     ('rev_z','oca_z',None,None,None,None),
     False, 5),
    ('v78 attack-only (V20Q0G45M35)',
     {'v':0.20,'q':0.00,'g':0.45,'m':0.35,'g_rev':0.5,'entry':10,'exit':11,'slots':5,'mom':'12m'},
     None, ('rev_z','oca_z','op_margin_z',0.5,0.3,0.2),
     None, True, 5),
    ('v77 attack-only (V5Q0G65M30)',
     {'v':0.05,'q':0.00,'g':0.65,'m':0.30,'g_rev':0.5,'entry':7,'exit':8,'slots':3,'mom':'12m-1m'},
     None, ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2),
     None, True, 5),
]

def run_and_print(label, offense, defense, g_o, g_d, attack_only, confirm):
    regime = calc_regime(confirm, attack_only)
    if attack_only:
        # run_fast 사용
        r = tsim.run_fast(
            v_w=offense['v'], q_w=offense['q'], g_w=offense['g'], m_w=offense['m'],
            g_rev=offense['g_rev'], entry_param=offense['entry'], exit_param=offense['exit'],
            max_slots=offense['slots'], mom_type=offense['mom'], trailing_stop=-0.15,
            g_sub1=g_o[0], g_sub2=g_o[1], g_sub3=g_o[2], g_w1=g_o[3], g_w2=g_o[4], g_w3=g_o[5],
        )
    else:
        r = tsim.run_regime(
            defense_params=defense, offense_params=offense,
            regime_dict=regime, trailing_stop=-0.15,
            g_sub1_o=g_o[0], g_sub2_o=g_o[1], g_sub3_o=g_o[2],
            g_w1_o=g_o[3], g_w2_o=g_o[4], g_w3_o=g_o[5],
            g_sub1_d=g_d[0], g_sub2_d=g_d[1], g_sub3_d=g_d[2],
            g_w1_d=g_d[3], g_w2_d=g_d[4], g_w3_d=g_d[5],
        )
    return r

# 5.25년 & 7.8년 비교
print('\n=== 5.25년 (2021-01~2026-04) vs 7.8년 (2018-07~2026-04) ===')
print(f'{"전략":<50} {"5.25y CAGR":>10} {"MDD":>6} {"Cal":>5} | {"7.8y CAGR":>10} {"MDD":>6} {"Cal":>5}')
print('-'*110)

# 5.25년 sub
sub_dates = [d for d in dates if '20210104' <= d <= '20260414']
sub_boost = {d: boost_rk[d] for d in sub_dates}
sub_def = {d: defense_rk[d] for d in sub_dates}
tsim_525 = TurboSimulator(sub_boost, sub_dates, ohlcv)

# 7.8년
tsim_78 = tsim

for label, offense, defense, g_o, g_d, attack_only, confirm in candidates:
    # 5.25년
    if attack_only:
        reg_525 = {d: True for d in sub_dates}
        r_525 = tsim_525.run_fast(
            v_w=offense['v'], q_w=offense['q'], g_w=offense['g'], m_w=offense['m'],
            g_rev=offense['g_rev'], entry_param=offense['entry'], exit_param=offense['exit'],
            max_slots=offense['slots'], mom_type=offense['mom'], trailing_stop=-0.15,
            g_sub1=g_o[0], g_sub2=g_o[1], g_sub3=g_o[2], g_w1=g_o[3], g_w2=g_o[4], g_w3=g_o[5],
        )
    else:
        # 국면 계산
        reg_525 = {}
        md = False; stk = 0; ss = None
        for d in sub_dates:
            ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma200.get(ts)
            if kv is None or pd.isna(mv): reg_525[d] = md; continue
            s = kv > mv
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= confirm and md != s: md = s
            reg_525[d] = md
        r_525 = tsim_525.run_regime(
            defense_params=defense, offense_params=offense, regime_dict=reg_525, trailing_stop=-0.15,
            g_sub1_o=g_o[0], g_sub2_o=g_o[1], g_sub3_o=g_o[2],
            g_w1_o=g_o[3], g_w2_o=g_o[4], g_w3_o=g_o[5],
            g_sub1_d=g_d[0], g_sub2_d=g_d[1], g_sub3_d=g_d[2],
            g_w1_d=g_d[3], g_w2_d=g_d[4], g_w3_d=g_d[5],
        )

    # 7.8년
    r_78 = run_and_print(label, offense, defense, g_o, g_d, attack_only, confirm)
    print(f'{label:<50} {r_525["cagr"]:>9.1f}% {r_525["mdd"]:>5.1f}% {r_525["calmar"]:>4.2f} | {r_78["cagr"]:>9.1f}% {r_78["mdd"]:>5.1f}% {r_78["calmar"]:>4.2f}')

print('\n완료')
