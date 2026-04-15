"""Phase 8: v77.1 (현재 프로덕션) vs v79 후보 (Phase 6c Top 1 cfg 1) 직접 비교

구간:
  - 5.25y (2021-01~2026-04)
  - 7.8y (2018-07~2026-04)
  - WF 4구간 (2018H2-19, 2020-21, 2022-23, 2024-26)

전략:
  v77.1 (현재): 공격 V5Q0G65M30 12m-1m gp E7X8S3 / 방어 V30Q5G10M55 6m-1m rev_accel+opm E3X6S7 + Crash -0.20
  v79 후보   : 공격 V15Q5G50M30 12m gp E3X6S3 / 방어 V30Q15G15M40 6m-1m rev+oca E3X6S7 + (Crash None / -0.20 비교)
  regime: KP_MA200_7d (v79 확정)
"""
import sys, os, json, glob, time
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
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()
ret20 = kospi.pct_change(20)


def calc_regime(target_dates, confirm=7, crash_threshold=None):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma200.get(ts); r20 = ret20.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        final = md
        if md and crash_threshold is not None and r20 is not None and not pd.isna(r20):
            if r20 < crash_threshold:
                final = False
        reg[d] = final
    return reg


# 구간 정의
PERIODS = {
    '7.8y':      ('20180702', '20260414'),
    '5.25y':     ('20210104', '20260414'),
    '2018H2-19': ('20180702', '20191231'),
    '2020-21':   ('20200102', '20211230'),
    '2022-23':   ('20220103', '20231228'),
    '2024-26':   ('20240102', '20260414'),
}

# TSIM per period (캐시)
t0 = time.time()
tsims = {}
for name, (s, e) in PERIODS.items():
    pd_ = [d for d in dates if s <= d <= e]
    if len(pd_) < 50: continue
    tsims[name] = (pd_, TurboSimulator({d: boost_rk[d] for d in pd_}, pd_, ohlcv))
print(f'TSIM 초기화: {time.time()-t0:.1f}s ({len(tsims)}개)', flush=True)


# ======== 전략 정의 ========
STRATEGIES = {
    'v77.1_current': {
        'regime_confirm': 5,  # v77.1은 5d 확인
        'crash': -0.20,
        'offense': {'v':0.05,'q':0.00,'g':0.65,'m':0.30,'g_rev':0.5,
                    'entry':7,'exit':8,'slots':3,'mom':'12m-1m'},
        'o_gs': ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2),
        'defense': {'v':0.30,'q':0.05,'g':0.10,'m':0.55,'g_rev':0.5,
                    'entry':3,'exit':6,'slots':7,'mom':'6m-1m'},
        'd_gs': ('rev_accel_z','op_margin_z',None,None,None,None),
    },
    'v79_cand_no_crash': {
        'regime_confirm': 7,  # v79 = 7d
        'crash': None,
        'offense': {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,
                    'entry':3,'exit':6,'slots':3,'mom':'12m'},
        'o_gs': ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2),
        'defense': {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
                    'entry':3,'exit':6,'slots':7,'mom':'6m-1m'},
        'd_gs': ('rev_z','oca_z',None,None,None,None),
    },
    'v79_cand_crash20': {
        'regime_confirm': 7,
        'crash': -0.20,
        'offense': {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,
                    'entry':3,'exit':6,'slots':3,'mom':'12m'},
        'o_gs': ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2),
        'defense': {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
                    'entry':3,'exit':6,'slots':7,'mom':'6m-1m'},
        'd_gs': ('rev_z','oca_z',None,None,None,None),
    },
}


def run(strat, period_name):
    pd_, tsim = tsims[period_name]
    reg = calc_regime(pd_, strat['regime_confirm'], strat['crash'])
    gso, gsd = strat['o_gs'], strat['d_gs']
    r = tsim.run_regime(
        defense_params=strat['defense'], offense_params=strat['offense'],
        regime_dict=reg, trailing_stop=-0.15,
        g_sub1_o=gso[0],g_sub2_o=gso[1],g_sub3_o=gso[2],
        g_w1_o=gso[3],g_w2_o=gso[4],g_w3_o=gso[5],
        g_sub1_d=gsd[0],g_sub2_d=gsd[1],g_sub3_d=gsd[2],
        g_w1_d=gsd[3],g_w2_d=gsd[4],g_w3_d=gsd[5],
    )
    return r


# ======== 실행 ========
print(f'\n=== 전략 × 구간 성과 ===')
rows = []
for sname, strat in STRATEGIES.items():
    for pname in PERIODS:
        if pname not in tsims: continue
        try:
            r = run(strat, pname)
            rows.append({'strategy':sname, 'period':pname,
                         'cal':r['calmar'], 'cagr':r['cagr'], 'mdd':r['mdd'],
                         'total':r.get('total',0)})
        except Exception as ee:
            print(f'  [{sname} {pname}] ERR {str(ee)[:60]}', flush=True)

df = pd.DataFrame(rows)
df.to_csv('C:/dev/backtest/phase8_final_compare.csv', index=False, encoding='utf-8-sig')

# 피벗
print('\n--- Calmar 비교 ---')
piv_cal = df.pivot(index='period', columns='strategy', values='cal').reindex(list(PERIODS.keys()))
print(piv_cal.round(3).to_string())

print('\n--- CAGR (%) ---')
piv_cagr = df.pivot(index='period', columns='strategy', values='cagr').reindex(list(PERIODS.keys()))
print(piv_cagr.round(1).to_string())

print('\n--- MDD (%) ---')
piv_mdd = df.pivot(index='period', columns='strategy', values='mdd').reindex(list(PERIODS.keys()))
print(piv_mdd.round(1).to_string())

print('\n--- Total Return (%) ---')
piv_tot = df.pivot(index='period', columns='strategy', values='total').reindex(list(PERIODS.keys()))
print(piv_tot.round(1).to_string())

# 종합 점수
print('\n--- 종합 판단 ---')
wf_periods = ['2018H2-19','2020-21','2022-23','2024-26']
for s in piv_cal.columns:
    wf_min = piv_cal.loc[wf_periods, s].min()
    wf_mean = piv_cal.loc[wf_periods, s].mean()
    print(f'{s:20s}  5.25y={piv_cal.loc["5.25y",s]:.2f}  7.8y={piv_cal.loc["7.8y",s]:.2f}  '
          f'WF_min={wf_min:.2f}  WF_mean={wf_mean:.2f}')
