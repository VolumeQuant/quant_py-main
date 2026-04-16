"""5옵션 × 연도별 성과 — CAGR, MDD, Sortino, Sharpe, Calmar"""
import sys, os, json, glob, time
from pathlib import Path
sys.path.insert(0, 'C:/dev/backtest')
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator


def load_rankings_from_dir(boost_dir, defense_dir):
    data = {}
    for d in [Path(boost_dir), Path(defense_dir)]:
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8: continue
            if k not in data:
                data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


def apply_filter(rankings_data, mode):
    filtered = {}
    for date_str, data in rankings_data.items():
        ranks = data.get('rankings', [])
        if mode == 'C':
            kept = ranks
        elif mode == 'baseline':
            kept = [r for r in ranks if r.get('value_s', 0) >= -1.5
                    and r.get('quality_s', 0) >= -1.5 and r.get('momentum_s', 0) >= -1.5]
        elif mode == 'A':
            kept = [r for r in ranks if r.get('value_s', 0) >= -2.0
                    and r.get('quality_s', 0) >= -2.0 and r.get('momentum_s', 0) >= -2.0]
        elif mode == 'B':
            kept = [r for r in ranks if r.get('quality_s', 0) >= -1.5
                    and r.get('momentum_s', 0) >= -1.5]
        elif mode == 'D':
            def d_pass(r):
                v, q, m = r.get('value_s', 0), r.get('quality_s', 0), r.get('momentum_s', 0)
                any_below = v < -1.5 or q < -1.5 or m < -1.5
                return not (any_below and (q + m) / 2 <= 0)
            kept = [r for r in ranks if d_pass(r)]
        else:
            kept = ranks
        filtered[date_str] = kept
    return filtered


C_BOOST = Path('C:/dev/backtest/extreme_C_boost')
C_DEFENSE = Path('C:/dev/backtest/extreme_C_defense')
C_BOOST_EXT = Path('C:/dev/backtest/extreme_C_boost_ext')
C_DEFENSE_EXT = Path('C:/dev/backtest/extreme_C_defense_ext')

print('로딩...', flush=True)
boost_rd = load_rankings_from_dir(C_BOOST_EXT, C_BOOST)
defense_rd = load_rankings_from_dir(C_DEFENSE_EXT, C_DEFENSE)
dates = sorted(set(boost_rd) & set(defense_rd))

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


OFFENSE = {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,'entry':3,'exit':6,'slots':3,'mom':'12m'}
DEFENSE = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}
O_GS = ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
D_GS = ('rev_z','oca_z',None,None,None,None)

# 연도별 구간
YEARS = [
    ('2018H2', '20180702', '20181231'),
    ('2019', '20190102', '20191230'),
    ('2020', '20200102', '20201230'),
    ('2021', '20210104', '20211230'),
    ('2022', '20220103', '20221229'),
    ('2023', '20230102', '20231228'),
    ('2024', '20240102', '20241230'),
    ('2025', '20250102', '20251230'),
    ('2026YTD', '20260102', '20260415'),
]

OPTIONS = ['baseline', 'A', 'B', 'C', 'D']

print('연도별 BT 시작...\n', flush=True)
all_rows = []

for opt in OPTIONS:
    boost_filtered = apply_filter({d: boost_rd[d] for d in dates}, opt)

    for label, s, e in YEARS:
        yd = [d for d in dates if s <= d <= e]
        if len(yd) < 20: continue

        reg = calc_regime(yd, 7)
        sub_rk = {d: boost_filtered[d] for d in yd}
        try:
            tsim = TurboSimulator(sub_rk, yd, ohlcv)
            r = tsim.run_regime(
                defense_params=DEFENSE, offense_params=OFFENSE,
                regime_dict=reg, trailing_stop=-0.15,
                g_sub1_o=O_GS[0],g_sub2_o=O_GS[1],g_sub3_o=O_GS[2],
                g_w1_o=O_GS[3],g_w2_o=O_GS[4],g_w3_o=O_GS[5],
                g_sub1_d=D_GS[0],g_sub2_d=D_GS[1],g_sub3_d=D_GS[2],
                g_w1_d=D_GS[3],g_w2_d=D_GS[4],g_w3_d=D_GS[5],
            )
            all_rows.append({
                'option': opt, 'year': label,
                'cagr': r.get('cagr', 0), 'mdd': r.get('mdd', 0),
                'calmar': r.get('calmar', 0),
                'sharpe': r.get('sharpe', 0), 'sortino': r.get('sortino', 0),
                'total': r.get('total', 0),
            })
        except Exception as ee:
            all_rows.append({'option': opt, 'year': label,
                             'cagr': 0, 'mdd': 0, 'calmar': 0, 'sharpe': 0, 'sortino': 0, 'total': 0})

df = pd.DataFrame(all_rows)

# 피벗 출력
for metric in ['calmar', 'cagr', 'mdd', 'sharpe', 'sortino']:
    print(f'\n=== {metric.upper()} (연도별) ===')
    piv = df.pivot(index='year', columns='option', values=metric)
    piv = piv.reindex([y[0] for y in YEARS if any(r['year']==y[0] for r in all_rows)])
    piv = piv[OPTIONS]
    print(piv.round(2).to_string())

# 전체 기간 요약 (기존 Phase 8 결과와 비교용)
print(f'\n=== 전체 기간 종합 ===')
for opt in OPTIONS:
    sub = df[df['option']==opt]
    avg_cal = sub['calmar'].mean()
    min_cal = sub['calmar'].min()
    avg_sharpe = sub['sharpe'].mean()
    print(f'  {opt:>10}: 평균Cal={avg_cal:.2f} 최소Cal={min_cal:.2f} 평균Sharpe={avg_sharpe:.2f}')
