"""Phase 8b: v79 성과 민감도 분석

A. 제룡전기(033100) 제외 — 단일 종목 의존도 확인
B. 섹터 제한: Top 10에서 동일 섹터 최대 3종목 (원본 73% 쏠림 완화)

각각 v77.1 / v79 두 전략에 대해 5.25y, 7.8y, WF 4구간 비교.
"""
import sys, os, json, glob, time, copy
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


# =========== 랭킹 변형 ===========
def make_exclude(rk, ticker):
    """특정 ticker 전부 제거"""
    new = {}
    for d, lst in rk.items():
        new[d] = [r for r in lst if r.get('ticker') != ticker]
    return new

def make_sector_cap(rk, max_per_sector=3):
    """각 날짜 rank 순서대로 보되 동일 섹터 max_per_sector개까지만 유지"""
    new = {}
    for d, lst in rk.items():
        sorted_lst = sorted(lst, key=lambda x: x.get('rank', 999))
        sector_count = defaultdict(int)
        kept = []
        for r in sorted_lst:
            sec = r.get('sector', 'UNK')
            if sector_count[sec] < max_per_sector:
                kept.append(r)
                sector_count[sec] += 1
        new[d] = kept
    return new


# =========== 구간 ===========
PERIODS = {
    '7.8y':      ('20180702', '20260414'),
    '5.25y':     ('20210104', '20260414'),
    '2018H2-19': ('20180702', '20191231'),
    '2020-21':   ('20200102', '20211230'),
    '2022-23':   ('20220103', '20231228'),
    '2024-26':   ('20240102', '20260414'),
}

# =========== 전략 ===========
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


# =========== 3가지 universe ===========
rankings_variants = {
    'original':   boost_rk_full,
    'no_jeryong': make_exclude(boost_rk_full, '033100'),
    'sector_cap3': make_sector_cap(boost_rk_full, 3),
}

# 제외/제한 통계
print('\n--- universe 변형 통계 ---')
for name, rk in rankings_variants.items():
    avg_n = np.mean([len(lst) for lst in rk.values()])
    print(f'  {name:12s}: 평균 종목수 {avg_n:.0f}')

# =========== TSIM per (variant, period) ===========
t_init = time.time()
tsims = {}
for vname, rk in rankings_variants.items():
    for pname, (s, e) in PERIODS.items():
        pd_ = [d for d in dates if s <= d <= e]
        if len(pd_) < 50: continue
        key = (vname, pname)
        sub_rk = {d: rk[d] for d in pd_}
        tsims[key] = (pd_, TurboSimulator(sub_rk, pd_, ohlcv))
print(f'TSIM 초기화: {time.time()-t_init:.1f}s ({len(tsims)}개)', flush=True)


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


# =========== 실행 ===========
print('\n=== 실행 ===')
rows = []
for variant in ['original', 'no_jeryong', 'sector_cap3']:
    for sname, strat in STRATEGIES.items():
        for pname in PERIODS:
            key = (variant, pname)
            if key not in tsims: continue
            pd_, tsim = tsims[key]
            try:
                r = run(strat, pd_, tsim)
                rows.append({
                    'variant':variant, 'strategy':sname, 'period':pname,
                    'cal':r['calmar'], 'cagr':r['cagr'], 'mdd':r['mdd'],
                    'total':r.get('total',0),
                })
            except Exception as ee:
                print(f'  [{variant} {sname} {pname}] ERR {str(ee)[:60]}', flush=True)

df = pd.DataFrame(rows)
df.to_csv('C:/dev/backtest/phase8b_sensitivity.csv', index=False, encoding='utf-8-sig')

# =========== 표 출력 ===========
print('\n--- Calmar (variant × strategy × period) ---')
for period in PERIODS:
    print(f'\n[{period}]')
    sub = df[df['period']==period].pivot(index='variant', columns='strategy', values='cal')
    print(sub.round(3).to_string())

# 종합
print('\n--- 종합: variant × strategy × (7.8y, 5.25y, WF_mean, WF_min) ---')
wf_periods = ['2018H2-19','2020-21','2022-23','2024-26']
summary_rows = []
for variant in ['original', 'no_jeryong', 'sector_cap3']:
    for sname in STRATEGIES:
        sub = df[(df['variant']==variant) & (df['strategy']==sname)].set_index('period')
        if sub.empty: continue
        wf_cal = sub.loc[[p for p in wf_periods if p in sub.index], 'cal']
        summary_rows.append({
            'variant': variant, 'strategy': sname,
            'cal_78': sub.loc['7.8y', 'cal'] if '7.8y' in sub.index else np.nan,
            'cal_525': sub.loc['5.25y', 'cal'] if '5.25y' in sub.index else np.nan,
            'wf_min': wf_cal.min() if len(wf_cal) else np.nan,
            'wf_mean': wf_cal.mean() if len(wf_cal) else np.nan,
            'cagr_78': sub.loc['7.8y', 'cagr'] if '7.8y' in sub.index else np.nan,
            'total_78': sub.loc['7.8y', 'total'] if '7.8y' in sub.index else np.nan,
        })
sdf = pd.DataFrame(summary_rows)
print(sdf.round(2).to_string(index=False))

# 변화 추적: v77.1 vs v79 차이가 유지되는지
print('\n--- v79 vs v77.1 Cal 차이 (variant별, 양수=v79 우세) ---')
for variant in ['original', 'no_jeryong', 'sector_cap3']:
    row_v77 = sdf[(sdf['variant']==variant) & (sdf['strategy']=='v77.1')].iloc[0] if not sdf[(sdf['variant']==variant) & (sdf['strategy']=='v77.1')].empty else None
    row_v79 = sdf[(sdf['variant']==variant) & (sdf['strategy']=='v79')].iloc[0] if not sdf[(sdf['variant']==variant) & (sdf['strategy']=='v79')].empty else None
    if row_v77 is not None and row_v79 is not None:
        diff_78 = row_v79['cal_78'] - row_v77['cal_78']
        diff_525 = row_v79['cal_525'] - row_v77['cal_525']
        print(f'  {variant:12s}: 7.8y Δ={diff_78:+.2f} (v79-{row_v77["cal_78"]:.2f}={row_v79["cal_78"]:.2f})  '
              f'5.25y Δ={diff_525:+.2f} ({row_v77["cal_525"]:.2f}→{row_v79["cal_525"]:.2f})')
