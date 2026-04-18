"""Phase B Step B-2: 잠정 rcept_dt 주입 + BT 비교
괴리 0% 확인됨 → 값은 동일, rcept_dt만 잠정 공시일로 앞당김.
기존 코드 수정 0 — fs_dart의 rcept_dt 컬럼만 변경.
"""
import sys, os, json, glob, time, shutil
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess
import pandas as pd
import numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator

PROJECT = Path(__file__).parent.parent
CACHE_DIR = PROJECT / 'data_cache'
FG = str(PROJECT / 'backtest' / 'fast_generate_rankings_v2.py')
PYTHON = sys.executable

# ── Step 1: 잠정실적 로드 ──
prov_df = pd.read_parquet(CACHE_DIR / 'provisional_earnings.parquet')
print(f'잠정실적 로드: {len(prov_df)}건, {prov_df["ticker"].nunique()}종목')

# rcept_dt를 Timestamp으로 변환
prov_df['rcept_dt'] = pd.to_datetime(prov_df['rcept_dt'])
prov_df['base_date'] = pd.to_datetime(prov_df['base_date'])

# 종목별 분기별 잠정 rcept_dt 매핑: {(ticker, base_date) → provisional_rcept_dt}
prov_map = {}
for _, row in prov_df.iterrows():
    key = (row['ticker'], row['base_date'])
    prov_map[key] = row['rcept_dt']
print(f'잠정 rcept_dt 매핑: {len(prov_map)}건')

# ── Step 2: fs_dart 백업 + rcept_dt 수정 ──
backup_dir = CACHE_DIR / 'fs_dart_backup_pre_provisional'
if not backup_dir.exists():
    print(f'\nfs_dart 백업 중...')
    backup_dir.mkdir(parents=True)
    for fp in CACHE_DIR.glob('fs_dart_*.parquet'):
        shutil.copy2(fp, backup_dir / fp.name)
    print(f'  백업 완료: {len(list(backup_dir.glob("*.parquet")))}파일 → {backup_dir}')
else:
    print(f'백업 이미 존재: {backup_dir}')

# rcept_dt 수정 (잠정이 있는 행만)
modified_tickers = 0
modified_rows = 0

for fp in sorted(CACHE_DIR.glob('fs_dart_*.parquet')):
    ticker = fp.stem.replace('fs_dart_', '')

    # 이 종목에 잠정 데이터가 있는 분기 찾기
    ticker_prov = {bd: rdt for (tk, bd), rdt in prov_map.items() if tk == ticker}
    if not ticker_prov:
        continue

    df = pd.read_parquet(fp)
    if 'rcept_dt' not in df.columns:
        continue

    changed = False
    for base_date, prov_rcept in ticker_prov.items():
        # 해당 분기(base_date)의 분기(q) 데이터 행 찾기
        mask = (df['기준일'] == base_date) & (df['공시구분'] == 'q') & df['rcept_dt'].notna()
        if mask.any():
            existing_rcept = df.loc[mask, 'rcept_dt'].iloc[0]
            if pd.notna(existing_rcept):
                existing_ts = pd.Timestamp(existing_rcept)
                prov_ts = pd.Timestamp(prov_rcept)
                # 잠정이 정식보다 빠를 때만 교체
                if prov_ts < existing_ts:
                    df.loc[mask, 'rcept_dt'] = prov_ts
                    modified_rows += mask.sum()
                    changed = True

    if changed:
        df.to_parquet(fp, index=False)
        modified_tickers += 1

print(f'\nrcept_dt 수정: {modified_tickers}종목, {modified_rows}행')

# ── Step 3: Ranking 재생성 (가중 TTM과 같은 구조) ──
PROV_STATE = str(PROJECT / 'backtest' / 'provisional_state')
PROV_BT_EXT = str(PROJECT / 'backtest' / 'provisional_bt_extended')

BOOST_ENV = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.05',
    'FACTOR_G_W': '0.50', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_SUB3': 'gp_growth_z',
    'G_W1': '0.5', 'G_W2': '0.3', 'G_W3': '0.2',
    'MOM_PERIOD': '12m',
    'PYTHONIOENCODING': 'utf-8',
}

os.makedirs(PROV_STATE, exist_ok=True)
os.makedirs(PROV_BT_EXT, exist_ok=True)

print(f'\n=== Ranking 재생성 (잠정 rcept_dt 적용) ===')
t0 = time.time()
jobs = [
    ('prov_bt_ext', '20180702', '20201230', PROV_BT_EXT, BOOST_ENV),
    ('prov_state',  '20210104', '20260417', PROV_STATE,  BOOST_ENV),
]

processes = []
for label, s, e, sdir, env in jobs:
    merged = {**os.environ, **env}
    merged.pop('PRODUCTION_MODE', None)  # BT에서는 전체 데이터 사용
    log_path = str(PROJECT / 'logs' / f'provisional_{label}.log')
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
print(f'재생성 완료: {regen_time/60:.1f}분')

# ── Step 4: fs_dart 복원 (원본으로 되돌리기) ──
print(f'\nfs_dart 원본 복원 중...')
for fp in backup_dir.glob('*.parquet'):
    shutil.copy2(fp, CACHE_DIR / fp.name)
print(f'  복원 완료')

# ── Step 5: BT 비교 ──
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

print(f'\nranking 로드 중...')
bl_boost = load_rankings([PROJECT / 'backtest' / 'bt_extended', PROJECT / 'state'])
pv_boost = load_rankings([PROV_BT_EXT, PROV_STATE])
defense = load_rankings([PROJECT / 'backtest' / 'bt_extended_defense', PROJECT / 'state' / 'defense'])

common = sorted(set(bl_boost) & set(pv_boost) & set(defense))
print(f'baseline: {len(bl_boost)}일, provisional: {len(pv_boost)}일, 공통: {len(common)}일')

bl_rk = {d: bl_boost[d]['rankings'] for d in common}
pv_rk = {d: pv_boost[d]['rankings'] for d in common}

ohlcv = pd.read_parquet(sorted((PROJECT / 'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
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

PERIODS = {
    '7.8y':      ('20180702', '20260414'),
    '5.25y':     ('20210104', '20260414'),
    '2018H2-19': ('20180702', '20191231'),
    '2020-21':   ('20200102', '20211230'),
    '2022-23':   ('20220103', '20231228'),
    '2024-26':   ('20240102', '20260414'),
}

V79_O = {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V79_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}
GS_O = ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
GS_D = ('rev_z','oca_z',None,None,None,None)

print(f'\n=== BT 실행 ===')
results = []
for label, rk in [('baseline', bl_rk), ('provisional', pv_rk)]:
    for pname, (ps, pe) in PERIODS.items():
        pd_ = [d for d in common if ps <= d <= pe]
        if len(pd_) < 50: continue
        try:
            tsim = TurboSimulator({d: rk[d] for d in pd_}, pd_, ohlcv)
            reg = calc_regime(pd_, confirm=7)
            r = tsim.run_regime(
                defense_params=V79_D, offense_params=V79_O,
                regime_dict=reg, trailing_stop=-0.15,
                g_sub1_o=GS_O[0], g_sub2_o=GS_O[1], g_sub3_o=GS_O[2],
                g_w1_o=GS_O[3], g_w2_o=GS_O[4], g_w3_o=GS_O[5],
                g_sub1_d=GS_D[0], g_sub2_d=GS_D[1], g_sub3_d=GS_D[2],
                g_w1_d=GS_D[3], g_w2_d=GS_D[4], g_w3_d=GS_D[5],
            )
            results.append({'strategy': label, 'period': pname,
                           'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'],
                           'total': r.get('total', 0)})
            print(f'  {label:>15} {pname:>12}: Cal={r["calmar"]:.2f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}%', flush=True)
        except Exception as e:
            print(f'  {label:>15} {pname:>12}: ERROR {str(e)[:60]}', flush=True)

# 결과 출력
df = pd.DataFrame(results)
print(f'\n=== Calmar 비교 ===')
piv = df.pivot(index='period', columns='strategy', values='cal').reindex(list(PERIODS.keys()))
print(piv.round(3).to_string())

print(f'\n=== CAGR (%) ===')
piv_cagr = df.pivot(index='period', columns='strategy', values='cagr').reindex(list(PERIODS.keys()))
print(piv_cagr.round(1).to_string())

print(f'\n=== MDD (%) ===')
piv_mdd = df.pivot(index='period', columns='strategy', values='mdd').reindex(list(PERIODS.keys()))
print(piv_mdd.round(1).to_string())

# 종합
print(f'\n=== 종합 판단 ===')
wf = ['2018H2-19','2020-21','2022-23','2024-26']
for s in piv.columns:
    wf_vals = piv.loc[wf, s].dropna()
    c5 = piv.loc['5.25y', s] if '5.25y' in piv.index else 0
    c7 = piv.loc['7.8y', s] if '7.8y' in piv.index else 0
    wf_min = wf_vals.min() if len(wf_vals) > 0 else 0
    wf_mean = wf_vals.mean() if len(wf_vals) > 0 else 0
    print(f'{s:>15}: 5.25y={c5:.2f}  7.8y={c7:.2f}  WF_min={wf_min:.2f}  WF_mean={wf_mean:.2f}')

# Delta
if 'baseline' in piv.columns and 'provisional' in piv.columns:
    delta = piv['provisional'] - piv['baseline']
    print(f'\n=== Delta (provisional - baseline) ===')
    for p in PERIODS:
        if p in delta.index and pd.notna(delta[p]):
            print(f'  {p:>12}: Cal {delta[p]:+.3f}')

csv_path = str(PROJECT / 'backtest' / 'step_b2_provisional_results.csv')
df.to_csv(csv_path, index=False, encoding='utf-8-sig')
print(f'\n결과 저장: {csv_path}')
print(f'총 소요: {(time.time()-t0)/60:.1f}분')
