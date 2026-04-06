"""v76 Phase 2b: E/X/S 규칙 탐색 (공격Top15 + 방어Top15)"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
t0 = time.time()

ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*full*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    rk[d] = json.load(open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8')).get('rankings', [])

tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
print(f'init: {time.time()-t0:.1f}s', flush=True)

atk_df = pd.read_csv(RESULT_DIR / 'v76_phase2a_attack.csv').sort_values('cal', ascending=False)
def_df = pd.read_csv(RESULT_DIR / 'v76_phase2a_defense.csv').sort_values('cal', ascending=False)

rd_all = {d: True for d in dates}

# 공격 Top15 × E/X/S
print(f'\n=== 공격 E/X/S 탐색 ===', flush=True)
atk_results = []
for _, a in atk_df.head(15).iterrows():
    for e in [4, 5, 6]:
        for x in [7, 8, 9]:
            for s in [2, 3, 4]:
                p = {'v':a['v']/100,'q':a['q']/100,'g':a['g']/100,'m':a['m']/100,
                     'g_rev':a['gr'],'entry':e,'exit':x,'slots':s,'mom':a['mom']}
                r = tsim.run_regime(p, p, rd_all, stop_loss=-0.10, trailing_stop=-0.15,
                    g_sub1_d='oca_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
                atk_results.append({
                    'v':int(a['v']),'q':int(a['q']),'g':int(a['g']),'m':int(a['m']),
                    'gr':a['gr'],'mom':a['mom'],'e':e,'x':x,'s':s,
                    'cagr':r['cagr'],'mdd':r['mdd'],'cal':r['calmar'],'sh':r['sharpe']})
    print(f'  {len(atk_results)}개...', flush=True)

adf = pd.DataFrame(atk_results).sort_values('cal', ascending=False)
adf.to_csv(RESULT_DIR / 'v76_phase2b_attack_exs.csv', index=False)
print(f'공격 {len(atk_results)}개 완료 ({time.time()-t0:.0f}s)', flush=True)
print(adf.head(10).to_string(index=False), flush=True)

# 방어 Top15 × E/X/S
print(f'\n=== 방어 E/X/S 탐색 ===', flush=True)
rd_def = {d: False for d in dates}
def_results = []
for _, d in def_df.head(15).iterrows():
    for e in [4, 5, 6]:
        for x in [7, 8, 9]:
            for s in [4, 5, 6, 7]:
                p = {'v':d['v']/100,'q':d['q']/100,'g':d['g']/100,'m':d['m']/100,
                     'g_rev':d['gr'],'entry':e,'exit':x,'slots':s,'mom':d['mom']}
                r = tsim.run_regime(p, p, rd_def, stop_loss=-0.10, trailing_stop=-0.15,
                    g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='rev_z', g_sub2_o='op_margin_z')
                def_results.append({
                    'v':int(d['v']),'q':int(d['q']),'g':int(d['g']),'m':int(d['m']),
                    'gr':d['gr'],'mom':d['mom'],'e':e,'x':x,'s':s,
                    'cagr':r['cagr'],'mdd':r['mdd'],'cal':r['calmar'],'sh':r['sharpe']})
    print(f'  {len(def_results)}개...', flush=True)

ddf = pd.DataFrame(def_results).sort_values('cal', ascending=False)
ddf.to_csv(RESULT_DIR / 'v76_phase2b_defense_exs.csv', index=False)
print(f'방어 {len(def_results)}개 완료 ({time.time()-t0:.0f}s)', flush=True)
print(ddf.head(10).to_string(index=False), flush=True)

# E/X/S 패턴 분석
print(f'\n=== E/X/S 패턴 ===', flush=True)
at = adf.head(15)
print(f'공격 Top15: E={at["e"].value_counts().to_dict()} X={at["x"].value_counts().to_dict()} S={at["s"].value_counts().to_dict()}')
dt = ddf.head(15)
print(f'방어 Top15: E={dt["e"].value_counts().to_dict()} X={dt["x"].value_counts().to_dict()} S={dt["s"].value_counts().to_dict()}')
print(f'\n총: {time.time()-t0:.0f}s', flush=True)
