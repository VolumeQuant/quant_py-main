"""Phase 6: Top 5 × E/X/S 재탐색 + Crash Cash 효과
Phase 5b Top 5 후보 대상
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
defense_rk = {d: defense_rd[d]['rankings'] for d in dates}
sub_dates = [d for d in dates if '20210104' <= d <= '20260414']
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()
ret20 = kospi.pct_change(20)

def calc_regime_crash(target_dates, confirm=5, crash_threshold=None):
    """crash_threshold 설정 시 ret20 < threshold → False (attack 중 제외)"""
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma200.get(ts); r20 = ret20.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        # Crash Cash: attack 모드에서 ret20 급락 시 defense 강제 전환
        final = md
        if md and crash_threshold is not None and r20 is not None and not pd.isna(r20):
            if r20 < crash_threshold:
                final = False
        reg[d] = final
    return reg

# Top 5 (Phase 5b 기준)
top5 = pd.read_csv('C:/dev/backtest/phase5b_regime_grid.csv').head(5).to_dict('records')

tsim_78 = TurboSimulator(boost_rk, dates, ohlcv)
tsim_525 = TurboSimulator({d: boost_rk[d] for d in sub_dates}, sub_dates, ohlcv)

DEFENSE_V77_1 = {'v':0.30,'q':0.05,'g':0.10,'m':0.55,'g_rev':0.5,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}

def g_sub_params(gs):
    if gs == '3f_rev_oca_gp': return ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
    if gs == '3f_rev_oca_opm': return ('rev_z','oca_z','op_margin_z',0.5,0.3,0.2)
    return ('rev_z','oca_z',None,None,None,None)

# E/X/S 조합
ex_combos = [
    (3, 5, 5), (5, 8, 5), (5, 10, 5), (7, 8, 3), (7, 10, 5), (10, 11, 5),
    (3, 6, 3), (3, 8, 5), (5, 7, 3), (10, 15, 7), (5, 12, 5), (7, 12, 5),
]

# Crash 파라미터: None (없음), -0.20 (v77.1 수준)
crash_options = [None, -0.20]

print(f'\n=== Top 5 × E/X/S({len(ex_combos)}) × Crash({len(crash_options)}) ===', flush=True)
results = []
t0 = time.time()

for i, c in enumerate(top5):
    confirm = int(c['regime'].replace('MA200_','').replace('d','')) if 'MA200' in c['regime'] else 5
    gs = g_sub_params(c['gs'])
    for e, x, s in ex_combos:
        for cr in crash_options:
            ofs = {'v':c['V']/100,'q':c['Q']/100,'g':c['G']/100,'m':c['M']/100,
                   'g_rev':0.5 if '3f' in c['gs'] else 0.7,
                   'entry':e,'exit':x,'slots':s,'mom':c['mom']}
            try:
                reg_78 = calc_regime_crash(dates, confirm, cr)
                reg_525 = calc_regime_crash(sub_dates, confirm, cr)
                r78 = tsim_78.run_regime(
                    defense_params=DEFENSE_V77_1, offense_params=ofs, regime_dict=reg_78, trailing_stop=-0.15,
                    g_sub1_o=gs[0],g_sub2_o=gs[1],g_sub3_o=gs[2],
                    g_w1_o=gs[3],g_w2_o=gs[4],g_w3_o=gs[5],
                    g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z',
                )
                r525 = tsim_525.run_regime(
                    defense_params=DEFENSE_V77_1, offense_params=ofs, regime_dict=reg_525, trailing_stop=-0.15,
                    g_sub1_o=gs[0],g_sub2_o=gs[1],g_sub3_o=gs[2],
                    g_w1_o=gs[3],g_w2_o=gs[4],g_w3_o=gs[5],
                    g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z',
                )
                results.append({
                    'top5_idx': i+1,
                    'V':c['V'],'Q':c['Q'],'G':c['G'],'M':c['M'],
                    'mom':c['mom'],'gs':c['gs'],'regime':c['regime'],
                    'E':e,'X':x,'S':s,'crash':cr if cr else 'None',
                    'cal_78':r78['calmar'],'cagr_78':r78['cagr'],'mdd_78':r78['mdd'],
                    'cal_525':r525['calmar'],'cagr_525':r525['cagr'],'mdd_525':r525['mdd'],
                })
            except Exception as ee:
                print(f'  [{i}] E{e}X{x}S{s} crash{cr}: ERR {str(ee)[:50]}', flush=True)

df = pd.DataFrame(results)
df['score'] = df['cal_525']*0.5 + df['cal_78']*0.5
df = df.sort_values('score', ascending=False)
df.to_csv('C:/dev/backtest/phase6_exs_crash.csv', index=False, encoding='utf-8-sig')

print(f'\n=== Top 15 ({len(results)} 조합 중) ===')
print(df.head(15).to_string(index=False))
print(f'\n총 소요: {(time.time()-t0)/60:.1f}분')
