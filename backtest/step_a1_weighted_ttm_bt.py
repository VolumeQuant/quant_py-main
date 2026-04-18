"""Phase A Step A-1: 가중 TTM 전체 BT
1) 가중 TTM(40/30/20/10) boost ranking 전체 재생성 (bt_extended + state 범위)
2) TurboSimulator로 baseline vs weighted 비교 (defense는 기존 재사용)
"""
import os, sys, time, subprocess, json, glob
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator

PROJECT = Path(__file__).parent.parent
FG = str(PROJECT / 'backtest' / 'fast_generate_rankings_v2.py')
PYTHON = sys.executable

# ── Step 1: 가중 TTM boost ranking 재생성 ──
WEIGHTED_STATE = str(PROJECT / 'backtest' / 'weighted_ttm_state')
WEIGHTED_BT_EXT = str(PROJECT / 'backtest' / 'weighted_ttm_bt_extended')

BOOST_ENV = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.05',
    'FACTOR_G_W': '0.50', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_SUB3': 'gp_growth_z',
    'G_W1': '0.5', 'G_W2': '0.3', 'G_W3': '0.2',
    'MOM_PERIOD': '12m',
    'TTM_WEIGHTS': '0.4,0.3,0.2,0.1',  # ← 핵심 변경
    'PYTHONIOENCODING': 'utf-8',
}

os.makedirs(WEIGHTED_STATE, exist_ok=True)
os.makedirs(WEIGHTED_BT_EXT, exist_ok=True)

# bt_extended 범위(2018-07~2020-12) + state 범위(2021-01~2026-04) 병렬
jobs = [
    ('wt_bt_ext', '20180702', '20201230', WEIGHTED_BT_EXT, BOOST_ENV),
    ('wt_state',  '20210104', '20260417', WEIGHTED_STATE,  BOOST_ENV),
]

print('=== Step A-1: 가중 TTM boost ranking 재생성 ===')
t0 = time.time()
processes = []
for label, s, e, sdir, env in jobs:
    merged = {**os.environ, **env}
    log_path = str(PROJECT / 'logs' / f'weighted_ttm_{label}.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logf = open(log_path, 'w', encoding='utf-8')
    cmd = [PYTHON, '-u', FG, s, e, f'--state-dir={sdir}']
    p = subprocess.Popen(cmd, cwd=str(PROJECT), env=merged,
                         stdout=logf, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    processes.append((label, p, logf, time.time()))
    print(f'  [{label}] PID={p.pid} ({s}~{e})', flush=True)

for label, p, logf, ts in processes:
    rc = p.wait()
    logf.close()
    elapsed = time.time() - ts
    print(f'  [{label}] rc={rc} ({elapsed/60:.1f}분)', flush=True)

regen_time = time.time() - t0
print(f'재생성 완료: {regen_time/60:.1f}분\n')

# ── Step 2: ranking 로드 ──
def load_rankings(dirs):
    data = {}
    for d in dirs:
        d = Path(d)
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8: continue
            if k not in data:
                with open(fp, 'r', encoding='utf-8') as f:
                    data[k] = json.load(f)
    return data

print('ranking 로드 중...')
# baseline: 기존 state/ + bt_extended/ (이미 존재)
bl_boost = load_rankings([
    PROJECT / 'backtest' / 'bt_extended',
    PROJECT / 'state',
])
# weighted: 새로 생성한 디렉토리
wt_boost = load_rankings([WEIGHTED_BT_EXT, WEIGHTED_STATE])

# defense: 기존 그대로 (A-0에서 95% 동일 확인)
defense = load_rankings([
    PROJECT / 'backtest' / 'bt_extended_defense',
    PROJECT / 'state' / 'defense',
])

# 공통 날짜
bl_dates = sorted(set(bl_boost) & set(defense))
wt_dates = sorted(set(wt_boost) & set(defense))
common_dates = sorted(set(bl_dates) & set(wt_dates))
print(f'baseline: {len(bl_dates)}일, weighted: {len(wt_dates)}일, 공통: {len(common_dates)}일')

bl_rk = {d: bl_boost[d]['rankings'] for d in common_dates}
wt_rk = {d: wt_boost[d]['rankings'] for d in common_dates}

# OHLCV + KOSPI
ohlcv_files = sorted((PROJECT / 'data_cache').glob('all_ohlcv_2017*.parquet'))
ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
kdf = pd.read_parquet(PROJECT / 'data_cache' / 'kospi_yf.parquet')
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

# ── Step 3: TurboSimulator 실행 ──
PERIODS = {
    '7.8y':      ('20180702', '20260414'),
    '5.25y':     ('20210104', '20260414'),
    '2018H2-19': ('20180702', '20191231'),
    '2020-21':   ('20200102', '20211230'),
    '2022-23':   ('20220103', '20231228'),
    '2024-26':   ('20240102', '20260414'),
}

V79_OFFENSE = {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,
               'entry':3,'exit':6,'slots':3,'mom':'12m'}
V79_DEFENSE = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
               'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}
V79_GS_O = ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
V79_GS_D = ('rev_z','oca_z',None,None,None,None)

print('\n=== BT 실행 ===')
results = []

for label, rk_data in [('baseline', bl_rk), ('weighted_40_30_20_10', wt_rk)]:
    for pname, (ps, pe) in PERIODS.items():
        pd_ = [d for d in common_dates if ps <= d <= pe]
        if len(pd_) < 50:
            continue
        try:
            tsim = TurboSimulator({d: rk_data[d] for d in pd_}, pd_, ohlcv)
            reg = calc_regime(pd_, confirm=7)
            r = tsim.run_regime(
                defense_params=V79_DEFENSE, offense_params=V79_OFFENSE,
                regime_dict=reg, trailing_stop=-0.15,
                g_sub1_o=V79_GS_O[0], g_sub2_o=V79_GS_O[1], g_sub3_o=V79_GS_O[2],
                g_w1_o=V79_GS_O[3], g_w2_o=V79_GS_O[4], g_w3_o=V79_GS_O[5],
                g_sub1_d=V79_GS_D[0], g_sub2_d=V79_GS_D[1], g_sub3_d=V79_GS_D[2],
                g_w1_d=V79_GS_D[3], g_w2_d=V79_GS_D[4], g_w3_d=V79_GS_D[5],
            )
            results.append({
                'strategy': label, 'period': pname,
                'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'],
                'total': r.get('total', 0), 'trades': r.get('n_trades', 0),
            })
            print(f'  {label:>25} {pname:>12}: Cal={r["calmar"]:.2f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}%', flush=True)
        except Exception as e:
            print(f'  {label:>25} {pname:>12}: ERROR {str(e)[:60]}', flush=True)

# ── Step 4: 비교 출력 ──
df = pd.DataFrame(results)
print('\n=== Calmar 비교 ===')
piv = df.pivot(index='period', columns='strategy', values='cal').reindex(list(PERIODS.keys()))
print(piv.round(3).to_string())

print('\n=== CAGR (%) ===')
piv_cagr = df.pivot(index='period', columns='strategy', values='cagr').reindex(list(PERIODS.keys()))
print(piv_cagr.round(1).to_string())

print('\n=== MDD (%) ===')
piv_mdd = df.pivot(index='period', columns='strategy', values='mdd').reindex(list(PERIODS.keys()))
print(piv_mdd.round(1).to_string())

print('\n=== 매매 횟수 ===')
piv_trades = df.pivot(index='period', columns='strategy', values='trades').reindex(list(PERIODS.keys()))
print(piv_trades.to_string())

# WF 판단
print('\n=== 종합 판단 ===')
wf_periods = ['2018H2-19','2020-21','2022-23','2024-26']
for s in piv.columns:
    wf = piv.loc[wf_periods, s].dropna()
    wf_min = wf.min() if len(wf) > 0 else 0
    wf_mean = wf.mean() if len(wf) > 0 else 0
    wf_cv = wf.std() / wf_mean if wf_mean > 0 else 999
    c5 = piv.loc['5.25y', s] if '5.25y' in piv.index else 0
    c7 = piv.loc['7.8y', s] if '7.8y' in piv.index else 0
    print(f'{s:>25}: 5.25y={c5:.2f}  7.8y={c7:.2f}  WF_min={wf_min:.2f}  WF_mean={wf_mean:.2f}  CV={wf_cv:.2f}')

# 결과 CSV 저장
csv_path = str(PROJECT / 'backtest' / 'step_a1_weighted_ttm_results.csv')
df.to_csv(csv_path, index=False, encoding='utf-8-sig')
print(f'\n결과 저장: {csv_path}')
print(f'총 소요: {(time.time()-t0)/60:.1f}분')
