"""Phase 6b: 방어 Grid — 공격 Phase 6 Top 1 고정, 방어 파라미터 탐색 (병렬)

공격 고정: V15Q5G50M30, gp, 12m, MA200_7d, E3X6S3, Crash=None

방어 탐색 범위 (v77~v78 인사이트, 병렬이므로 복구):
  V: 20, 25, 30, 35, 40 (5)
  Q: 0, 5, 10, 15 (4)
  G: 0, 5, 10, 15, 20, 25, 30 (7)
  M: 30, 35, 40, 45, 50, 55, 60 (7)
  V+Q+G+M=100 제약
  G서브: 2팩터 rev+oca (v78), rev_accel+op_margin (v77) (2)
  MOM: 6m, 6m-1m (2)
  E/X/S: (3,4,5), (3,6,7), (5,8,5) (3)

병렬: 4워커 × ProcessPoolExecutor (grid_search_final.py 패턴)
"""
import sys, os, time, json, glob
from pathlib import Path
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, 'C:/dev/backtest')
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np


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

# 공격 고정 (Phase 6 Top 1)
OFFENSE = {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,'entry':3,'exit':6,'slots':3,'mom':'12m'}
O_GS = ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)

# 방어 탐색 범위
VW = [20, 25, 30, 35, 40]
QW = [0, 5, 10, 15]
GW = [0, 5, 10, 15, 20, 25, 30]
MW = [30, 35, 40, 45, 50, 55, 60]
D_MOMS = ['6m', '6m-1m']
D_GSUBS = [
    ('2f_rev_oca_0.7',        'rev_z',       'oca_z',       None, None, None, None, 0.7),
    ('2f_rev_accel_opm_0.5',  'rev_accel_z', 'op_margin_z', None, None, None, None, 0.5),
]
D_EXS = [(3,4,5), (3,6,7), (5,8,5)]

# === 병렬 워커 ===
_W_TSIM78 = None
_W_TSIM525 = None
_W_REGIME78 = None
_W_REGIME525 = None


def _init_worker():
    """워커당 1회 데이터 로드 (ranking + OHLCV + TurboSim + regime)"""
    global _W_TSIM78, _W_TSIM525, _W_REGIME78, _W_REGIME525
    from turbo_simulator import TurboSimulator

    boost_rd = load_rankings([BT_EXT, STATE])
    defense_rd = load_rankings([BT_EXT_D, STATE_D])
    dates = sorted(set(boost_rd) & set(defense_rd))
    boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
    sub_dates = [d for d in dates if '20210104' <= d <= '20260414']
    ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

    kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
    kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
    ma200 = kospi.rolling(200).mean()

    def calc_regime(target_dates, confirm=7):
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

    _W_REGIME78 = calc_regime(dates, 7)
    _W_REGIME525 = calc_regime(sub_dates, 7)
    _W_TSIM78 = TurboSimulator(boost_rk, dates, ohlcv)
    _W_TSIM525 = TurboSimulator({d: boost_rk[d] for d in sub_dates}, sub_dates, ohlcv)


def _eval_combo(combo):
    """워커: 1개 방어 조합 → 7.8y + 5.25y 결과"""
    global _W_TSIM78, _W_TSIM525, _W_REGIME78, _W_REGIME525
    v, q, g, m, mom, gs, e, x, s = combo
    defense = {'v':v/100,'q':q/100,'g':g/100,'m':m/100,'g_rev':gs[7],
               'entry':e,'exit':x,'slots':s,'mom':mom}
    try:
        r78 = _W_TSIM78.run_regime(
            defense_params=defense, offense_params=OFFENSE,
            regime_dict=_W_REGIME78, trailing_stop=-0.15,
            g_sub1_o=O_GS[0], g_sub2_o=O_GS[1], g_sub3_o=O_GS[2],
            g_w1_o=O_GS[3], g_w2_o=O_GS[4], g_w3_o=O_GS[5],
            g_sub1_d=gs[1], g_sub2_d=gs[2], g_sub3_d=gs[3],
            g_w1_d=gs[4], g_w2_d=gs[5], g_w3_d=gs[6],
        )
        r525 = _W_TSIM525.run_regime(
            defense_params=defense, offense_params=OFFENSE,
            regime_dict=_W_REGIME525, trailing_stop=-0.15,
            g_sub1_o=O_GS[0], g_sub2_o=O_GS[1], g_sub3_o=O_GS[2],
            g_w1_o=O_GS[3], g_w2_o=O_GS[4], g_w3_o=O_GS[5],
            g_sub1_d=gs[1], g_sub2_d=gs[2], g_sub3_d=gs[3],
            g_w1_d=gs[4], g_w2_d=gs[5], g_w3_d=gs[6],
        )
        return {
            'V':v,'Q':q,'G':g,'M':m,'mom':mom,'gs':gs[0],
            'E':e,'X':x,'S':s,
            'cal_78':r78['calmar'],'cagr_78':r78['cagr'],'mdd_78':r78['mdd'],
            'cal_525':r525['calmar'],'cagr_525':r525['cagr'],'mdd_525':r525['mdd'],
        }
    except Exception as ee:
        return None


def main():
    # 유효 조합 생성
    combos = []
    for v, q, g, m in product(VW, QW, GW, MW):
        if v + q + g + m == 100:
            for mom in D_MOMS:
                for gs in D_GSUBS:
                    for e, x, s in D_EXS:
                        combos.append((v, q, g, m, mom, gs, e, x, s))
    print(f'방어 조합 수: {len(combos)}', flush=True)

    t0 = time.time()
    N_WORKERS = 4
    results = []
    done = 0

    print(f'병렬: {N_WORKERS}워커 실행 시작...', flush=True)
    with ProcessPoolExecutor(max_workers=N_WORKERS, initializer=_init_worker) as ex:
        futures = {ex.submit(_eval_combo, c): c for c in combos}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(r)
            done += 1
            if done % 50 == 0 or done == len(combos):
                el = time.time() - t0
                rate = done / el if el > 0 else 1
                rem = (len(combos) - done) / rate if rate > 0 else 0
                print(f'  [{done}/{len(combos)}] {el:.0f}s elapsed, ETA {rem:.0f}s', flush=True)

    df = pd.DataFrame(results)
    df['score'] = df['cal_525']*0.5 + df['cal_78']*0.5
    df = df.sort_values('score', ascending=False)
    df.to_csv('C:/dev/backtest/phase6b_defense_grid.csv', index=False, encoding='utf-8-sig')

    print(f'\n=== 방어 Top 15 ===')
    print(df.head(15).to_string(index=False))
    print(f'\n총 소요: {(time.time()-t0)/60:.1f}분')


if __name__ == '__main__':
    main()
