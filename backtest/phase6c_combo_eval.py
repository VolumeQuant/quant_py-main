"""Phase 6c: 공격 Top 5 × 방어 Top 5 조합 평가 (국면전환 포함)
25 조합 × 5.25y/7.8y = 종합 Score 선정

효율: TSIM 전역 1회 프리로드 + regime은 unique confirm별 사전계산.
(25조합이라 워커 오버헤드보다 캐시 프리로드가 유리)
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
t_load = time.time()
boost_rd = load_rankings([BT_EXT, STATE])
defense_rd = load_rankings([BT_EXT_D, STATE_D])
dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
sub_dates = [d for d in dates if '20210104' <= d <= '20260414']
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()
print(f'  데이터 로드: {time.time()-t_load:.1f}s', flush=True)


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


# Top 5 공격/방어 로드
off_top5 = pd.read_csv('C:/dev/backtest/phase6_exs_crash.csv').head(5).to_dict('records')
def_top5 = pd.read_csv('C:/dev/backtest/phase6b_defense_grid.csv').head(5).to_dict('records')


def gs_o(gs_label):
    if gs_label == '3f_rev_oca_gp': return ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
    if gs_label == '3f_rev_oca_opm': return ('rev_z','oca_z','op_margin_z',0.5,0.3,0.2)
    return ('rev_z','oca_z',None,None,None,None)


def gs_d(gs_label):
    if gs_label == '2f_rev_oca_0.7': return ('rev_z','oca_z',None,None,None,None)
    if gs_label == '2f_rev_accel_opm_0.5': return ('rev_accel_z','op_margin_z',None,None,None,None)
    return ('rev_z','oca_z',None,None,None,None)


# === 캐시 프리로드 ===
t_tsim = time.time()
tsim_78 = TurboSimulator(boost_rk, dates, ohlcv)
tsim_525 = TurboSimulator({d: boost_rk[d] for d in sub_dates}, sub_dates, ohlcv)
print(f'  TSIM 초기화: {time.time()-t_tsim:.1f}s', flush=True)

# regime: unique confirm별 사전계산
unique_confirms = set()
for o in off_top5:
    c = int(o['regime'].replace('MA200_','').replace('d','')) if 'MA200' in o.get('regime', '') else 7
    unique_confirms.add(c)
print(f'  unique confirms: {sorted(unique_confirms)}', flush=True)

t_reg = time.time()
regime_cache_78 = {c: calc_regime(dates, c) for c in unique_confirms}
regime_cache_525 = {c: calc_regime(sub_dates, c) for c in unique_confirms}
print(f'  regime 캐시: {time.time()-t_reg:.1f}s', flush=True)

# === 조합 실행 ===
results = []
t0 = time.time()
print(f'\n조합 실행: {len(off_top5)} × {len(def_top5)} = {len(off_top5)*len(def_top5)}', flush=True)

for oi, o in enumerate(off_top5):
    confirm = int(o['regime'].replace('MA200_','').replace('d','')) if 'MA200' in o.get('regime', '') else 7
    gso = gs_o(o['gs'])
    ofs = {'v':o['V']/100,'q':o['Q']/100,'g':o['G']/100,'m':o['M']/100,
           'g_rev':0.5 if '3f' in o['gs'] else 0.7,
           'entry':int(o['E']),'exit':int(o['X']),'slots':int(o['S']),'mom':o['mom']}
    reg_78 = regime_cache_78[confirm]
    reg_525 = regime_cache_525[confirm]

    for di, d in enumerate(def_top5):
        gsd = gs_d(d['gs'])
        g_rev_d = 0.7 if 'rev_oca' in d['gs'] else 0.5
        dfs = {'v':d['V']/100,'q':d['Q']/100,'g':d['G']/100,'m':d['M']/100,
               'g_rev':g_rev_d,
               'entry':int(d['E']),'exit':int(d['X']),'slots':int(d['S']),'mom':d['mom']}
        try:
            r78 = tsim_78.run_regime(
                defense_params=dfs, offense_params=ofs, regime_dict=reg_78, trailing_stop=-0.15,
                g_sub1_o=gso[0],g_sub2_o=gso[1],g_sub3_o=gso[2],g_w1_o=gso[3],g_w2_o=gso[4],g_w3_o=gso[5],
                g_sub1_d=gsd[0],g_sub2_d=gsd[1],g_sub3_d=gsd[2],g_w1_d=gsd[3],g_w2_d=gsd[4],g_w3_d=gsd[5],
            )
            r525 = tsim_525.run_regime(
                defense_params=dfs, offense_params=ofs, regime_dict=reg_525, trailing_stop=-0.15,
                g_sub1_o=gso[0],g_sub2_o=gso[1],g_sub3_o=gso[2],g_w1_o=gso[3],g_w2_o=gso[4],g_w3_o=gso[5],
                g_sub1_d=gsd[0],g_sub2_d=gsd[1],g_sub3_d=gsd[2],g_w1_d=gsd[3],g_w2_d=gsd[4],g_w3_d=gsd[5],
            )
            results.append({
                'off_idx':oi, 'def_idx':di,
                'oV':o['V'],'oQ':o['Q'],'oG':o['G'],'oM':o['M'],'o_mom':o['mom'],'o_gs':o['gs'],
                'oE':int(o['E']),'oX':int(o['X']),'oS':int(o['S']),'regime':o.get('regime','MA200_7d'),
                'dV':d['V'],'dQ':d['Q'],'dG':d['G'],'dM':d['M'],'d_mom':d['mom'],'d_gs':d['gs'],
                'dE':int(d['E']),'dX':int(d['X']),'dS':int(d['S']),
                'cal_78':r78['calmar'],'cagr_78':r78['cagr'],'mdd_78':r78['mdd'],
                'cal_525':r525['calmar'],'cagr_525':r525['cagr'],'mdd_525':r525['mdd'],
            })
        except Exception as ee:
            print(f'  [{oi},{di}] ERR {str(ee)[:60]}', flush=True)

df = pd.DataFrame(results)
df['score'] = df['cal_525']*0.5 + df['cal_78']*0.5
df = df.sort_values('score', ascending=False)
df.to_csv('C:/dev/backtest/phase6c_combo.csv', index=False, encoding='utf-8-sig')

print(f'\n=== 공격 Top 5 × 방어 Top 5 ({len(results)} 조합) ===')
cols = ['off_idx','def_idx','oV','oG','o_mom','o_gs','dV','dG','d_mom','d_gs','cal_78','cal_525','score']
print(df[cols].head(15).to_string(index=False))
print(f'\n소요: {(time.time()-t0)/60:.1f}분')
