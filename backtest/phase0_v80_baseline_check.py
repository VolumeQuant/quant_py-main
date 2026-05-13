"""Phase 0: v80 baseline 단일 BT — 새 state(옵션F만)로 정합성 검증.

목표: 옛 BT Cal 4.29 재현 또는 차이 확인 → 본격 grid 진입 가능 여부 판단.
설정: V15Q0G55M30, 2f(rev_z 0.6 + oca_z 0.4), MOM=12m, E3X6S3
      Defense: V30Q15G15M40, 2f(rev_z 0.7+oca_z 0.3), MOM=6m-1m, E3X6S5
      TS=-0.15, SL=-0.10 (rollback 적용)
"""
import sys, json, glob
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, 'C:/dev/backtest')
sys.stdout.reconfigure(encoding='utf-8')
from turbo_simulator import TurboSimulator

STATE = Path('C:/dev/state')

def load_rankings(d):
    data = {}
    for fp in sorted(d.glob('ranking_*.json')):
        k = fp.stem.replace('ranking_','')
        if len(k) != 8 or not k.isdigit(): continue
        if k not in data:
            data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


def calc_regime(target_dates, kospi, ma170, confirm=8):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d]=md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg


print('로딩...', flush=True)
boost_rd = load_rankings(STATE)
defense_rd = load_rankings(STATE / 'defense')
dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].sort_index()
ma170 = kospi.rolling(170).mean()

print(f'기간: {dates[0]} ~ {dates[-1]} ({len(dates)}일)', flush=True)

V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)

periods = [
    ('2024-2026 (2.3y)', '20240102', '20260511'),
    ('2021-2026 (5.3y)', '20210104', '20260511'),
    ('2018-2026 (7.8y)', '20180702', '20260511'),
]

print('\n=== v80 baseline 재현 BT (옵션F만 데이터) ===')
print(f'{"기간":20} {"CAGR":>8} {"MDD":>8} {"Calmar":>8} {"Sharpe":>8} {"누적":>12}')

for label, ps, pe in periods:
    pd_ = [d for d in dates if ps <= d <= pe]
    regime = calc_regime(pd_, kospi, ma170)
    tsim = TurboSimulator({d: boost_rk[d] for d in pd_}, pd_, ohlcv)
    r = tsim.run_regime(
        defense_params=V80_D, offense_params=V80_O,
        regime_dict=regime,
        trailing_stop=-0.15, stop_loss=-0.10,
        g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
        g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
        g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
        g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
    )
    print(f'{label:20} {r["cagr"]:>7.1f}% {r["mdd"]:>7.2f}% {r["calmar"]:>8.3f} {r["sharpe"]:>8.3f} {r["total"]:>11.1f}%')

print()
print('비교 기준:')
print('  MEMORY 기록 v80 7.8y: Cal ~3.97, CAGR ~121%, MDD ~38%')
print('  집PC 옵션F BT 7.8y: Cal 4.29')
print('  오늘 BT (이전 검증): Cal 3.976')
print()
print('정합성 OK 조건: 7.8y Cal 3.5~4.5 사이')
