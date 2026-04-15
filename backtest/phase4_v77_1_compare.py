"""Phase 4: v77.1 현재 vs 수정본 성과 측정
5.25년 + 7.8년 BT, 공격/방어 + Crash Cash 포함
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
# TurboSim은 {date: [ranking_list]} 기대
boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
defense_rk = {d: defense_rd[d]['rankings'] for d in dates}
print(f'공통: {len(dates)} ({dates[0]}~{dates[-1]})')

ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

# v77.1 파라미터
OFFENSE = {'v':0.05,'q':0.00,'g':0.65,'m':0.30,'g_rev':0.5,'entry':7,'exit':8,'slots':3,'mom':'12m-1m'}
DEFENSE = {'v':0.30,'q':0.05,'g':0.10,'m':0.55,'g_rev':0.5,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}

# KOSPI 국면
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()

def calc_regime(confirm=5):
    reg = {}
    md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = ma200.get(ts)
        if kv is None or pd.isna(mv):
            reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s:
            md = s
        reg[d] = md
    return reg

regime = calc_regime(5)

# TurboSim
tsim = TurboSimulator(boost_rk, dates, ohlcv)

# 실행
print('\n=== v77.1 Regime (수정본 ranking 기반) ===')
print(f'{"기간":<25} {"CAGR":>8} {"MDD":>8} {"Cal":>6}')
print('-'*55)

for label, drange in [('7.8년 (2018-07~)', None), ('5.25년 (2021-01~)', ('20210104', '20260414'))]:
    sub_dates = dates if drange is None else [d for d in dates if drange[0] <= d <= drange[1]]
    sub_regime = {d: regime[d] for d in sub_dates}
    # run_regime은 전체 dates 배열 사용하므로 필터링 필요
    # 임시로 TurboSim 재생성
    if drange:
        sub_boost = {d: boost_rk[d] for d in sub_dates}
        sub_def = {d: defense_rk[d] for d in sub_dates}
        tsim_sub = TurboSimulator(sub_boost, sub_dates, ohlcv)
    else:
        tsim_sub = tsim

    try:
        r = tsim_sub.run_regime(
            defense_params=DEFENSE, offense_params=OFFENSE,
            regime_dict=sub_regime, trailing_stop=-0.15,
            g_sub1_o='rev_z', g_sub2_o='oca_z', g_sub3_o='gp_growth_z',
            g_w1_o=0.5, g_w2_o=0.3, g_w3_o=0.2,
            g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z',
        )
        print(f'{label:<25} {r["cagr"]:>7.1f}% {r["mdd"]:>7.1f}% {r["calmar"]:>5.2f}')
    except Exception as e:
        print(f'{label}: ERR {e}')

print('\n완료')
