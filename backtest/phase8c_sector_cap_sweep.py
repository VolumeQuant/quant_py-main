"""Phase 8c: 섹터 cap 수준 sweep + v79/v77.1 비교
cap: 2, 3, 5, 7, 무제한
strategy: v77.1, v79

v79의 기계 섹터 +27%p 편중이 얼마나 성과에 기여하는지, cap 완화 시 어떻게 되는지.
"""
import sys, os, json, glob, time
from pathlib import Path
from collections import defaultdict
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
boost_rk_full = {d: boost_rd[d]['rankings'] for d in dates}

ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()


def calc_regime(target_dates, confirm=7, crash_threshold=None):
    ret20 = kospi.pct_change(20)
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


def make_sector_cap(rk, cap):
    if cap is None or cap >= 99:
        return rk
    new = {}
    for d, lst in rk.items():
        sorted_lst = sorted(lst, key=lambda x: x.get('rank', 999))
        sc = defaultdict(int)
        kept = []
        for r in sorted_lst:
            sec = r.get('sector', 'UNK')
            if sc[sec] < cap:
                kept.append(r); sc[sec] += 1
        # rank 재부여 (TurboSim이 rank 기반 처리)
        for i, r in enumerate(kept, 1):
            r = dict(r); r['rank'] = i; r['composite_rank'] = i
            kept[i-1] = r
        new[d] = kept
    return new


PERIODS = {
    '7.8y':      ('20180702', '20260414'),
    '5.25y':     ('20210104', '20260414'),
    '2018H2-19': ('20180702', '20191231'),
    '2020-21':   ('20200102', '20211230'),
    '2022-23':   ('20220103', '20231228'),
    '2024-26':   ('20240102', '20260414'),
}

STRATEGIES = {
    'v77.1': {
        'regime_confirm': 5, 'crash': -0.20,
        'offense': {'v':0.05,'q':0.00,'g':0.65,'m':0.30,'g_rev':0.5,
                    'entry':7,'exit':8,'slots':3,'mom':'12m-1m'},
        'o_gs': ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2),
        'defense': {'v':0.30,'q':0.05,'g':0.10,'m':0.55,'g_rev':0.5,
                    'entry':3,'exit':6,'slots':7,'mom':'6m-1m'},
        'd_gs': ('rev_accel_z','op_margin_z',None,None,None,None),
    },
    'v79': {
        'regime_confirm': 7, 'crash': None,
        'offense': {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,
                    'entry':3,'exit':6,'slots':3,'mom':'12m'},
        'o_gs': ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2),
        'defense': {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
                    'entry':3,'exit':6,'slots':7,'mom':'6m-1m'},
        'd_gs': ('rev_z','oca_z',None,None,None,None),
    },
}

CAPS = [2, 3, 5, 7, 99]  # 99 = 무제한

# TSIM 생성 (cap × period)
t0 = time.time()
tsims = {}
for cap in CAPS:
    rk = make_sector_cap(boost_rk_full, cap)
    avg_n = np.mean([len(lst) for lst in rk.values()])
    print(f'  cap={cap}: 평균 종목수 {avg_n:.0f}')
    for pname, (s, e) in PERIODS.items():
        pd_ = [d for d in dates if s <= d <= e]
        if len(pd_) < 50: continue
        sub_rk = {d: rk[d] for d in pd_}
        tsims[(cap, pname)] = (pd_, TurboSimulator(sub_rk, pd_, ohlcv))
print(f'TSIM 초기화: {time.time()-t0:.1f}s ({len(tsims)}개)')


def run(strat, pd_, tsim):
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


rows = []
for cap in CAPS:
    for sname, strat in STRATEGIES.items():
        for pname in PERIODS:
            key = (cap, pname)
            if key not in tsims: continue
            pd_, tsim = tsims[key]
            try:
                r = run(strat, pd_, tsim)
                rows.append({'cap':cap, 'strategy':sname, 'period':pname,
                             'cal':r['calmar'], 'cagr':r['cagr'], 'mdd':r['mdd'],
                             'total':r.get('total',0)})
            except Exception as ee:
                print(f'ERR cap={cap} {sname} {pname}: {str(ee)[:60]}')

df = pd.DataFrame(rows)
df.to_csv('C:/dev/backtest/phase8c_cap_sweep.csv', index=False, encoding='utf-8-sig')

# 표 출력
print('\n=== Calmar (cap × strategy × period) ===')
for period in PERIODS:
    print(f'\n[{period}]')
    sub = df[df['period']==period].pivot(index='cap', columns='strategy', values='cal')
    print(sub.round(3).to_string())

print('\n=== CAGR (7.8y) ===')
sub = df[df['period']=='7.8y'].pivot(index='cap', columns='strategy', values='cagr')
print(sub.round(1).to_string())

print('\n=== MDD (7.8y) ===')
sub = df[df['period']=='7.8y'].pivot(index='cap', columns='strategy', values='mdd')
print(sub.round(1).to_string())

# v79 vs v77.1 차이 (cap별)
print('\n=== v79-v77.1 Calmar 차 (양수=v79 우세) ===')
for period in ['7.8y', '5.25y']:
    print(f'\n[{period}]')
    for cap in CAPS:
        v77 = df[(df['cap']==cap) & (df['strategy']=='v77.1') & (df['period']==period)]
        v79 = df[(df['cap']==cap) & (df['strategy']=='v79') & (df['period']==period)]
        if not v77.empty and not v79.empty:
            diff = v79['cal'].iloc[0] - v77['cal'].iloc[0]
            print(f'  cap={cap}: v77.1={v77["cal"].iloc[0]:.2f} v79={v79["cal"].iloc[0]:.2f} Δ={diff:+.2f}')
