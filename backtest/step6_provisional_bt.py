"""Step 6: 잠정실적 BT — v80 2f(rev+oca) + Q=0 → PIT safe

v80에서 PIT safe인 이유:
  1. Growth: rev_z + oca_z만 사용 → 잠정에 있음
  2. Quality: Q=0 → 점수에 안 들어감
  3. gp_growth: G_SUB3=None → 점수에 안 들어감
  → fs_dart rcept_dt 수정해도 사용하는 팩터만 영향받음

절차:
  1. fs_dart 백업
  2. 잠정실적 rcept_dt로 매출/영업이익 행 수정
  3. ranking 재생성 (boost + defense, bt_extended + state)
  4. TurboSim으로 baseline vs provisional 비교
  5. fs_dart 복원 + 검증

기간 정의 주의: 2025년은 20251230까지!
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
prov_df['rcept_dt'] = pd.to_datetime(prov_df['rcept_dt'])
prov_df['base_date'] = pd.to_datetime(prov_df['base_date'])
prov_map = {}
for _, row in prov_df.iterrows():
    key = (row['ticker'], row['base_date'])
    prov_map[key] = row['rcept_dt']
print(f'잠정 rcept_dt 매핑: {len(prov_map)}건')

# ── Step 2: fs_dart 백업 + rcept_dt 수정 ──
backup_dir = CACHE_DIR / 'fs_dart_backup_step6'
if not backup_dir.exists():
    print(f'\nfs_dart 백업...', flush=True)
    backup_dir.mkdir(parents=True)
    for fp in CACHE_DIR.glob('fs_dart_*.parquet'):
        shutil.copy2(fp, backup_dir / fp.name)
    print(f'  백업 완료: {len(list(backup_dir.glob("*.parquet")))}파일')
else:
    # 이전 백업에서 복원 먼저 (깨끗한 상태 보장)
    print(f'기존 백업에서 fs_dart 원본 복원...', flush=True)
    for fp in backup_dir.glob('*.parquet'):
        shutil.copy2(fp, CACHE_DIR / fp.name)
    print(f'  복원 완료')

# 표본 확인: 수정 전 5종목
print(f'\n[표본] 수정 전 rcept_dt:', flush=True)
sample_tickers = ['005930', '000660', '005380', '051910', '035420']
for tk in sample_tickers:
    fp = CACHE_DIR / f'fs_dart_{tk}.parquet'
    if fp.exists():
        df = pd.read_parquet(fp)
        rev = df[(df['계정'] == '매출액') & (df['공시구분'] == 'q')].tail(2)
        for _, r in rev.iterrows():
            print(f'  {tk} {r["기준일"].date()} rcept_dt={r.get("rcept_dt")}')

# rcept_dt 수정
modified_tickers = 0
modified_rows = 0
for fp in sorted(CACHE_DIR.glob('fs_dart_*.parquet')):
    ticker = fp.stem.replace('fs_dart_', '')
    ticker_prov = {bd: rdt for (tk, bd), rdt in prov_map.items() if tk == ticker}
    if not ticker_prov:
        continue
    df = pd.read_parquet(fp)
    if 'rcept_dt' not in df.columns:
        continue
    changed = False
    for base_date, prov_rcept in ticker_prov.items():
        mask = (df['기준일'] == base_date) & (df['공시구분'] == 'q') & df['rcept_dt'].notna()
        if mask.any():
            existing_rcept = df.loc[mask, 'rcept_dt'].iloc[0]
            if pd.notna(existing_rcept):
                existing_ts = pd.Timestamp(existing_rcept)
                prov_ts = pd.Timestamp(prov_rcept)
                if prov_ts < existing_ts:
                    df.loc[mask, 'rcept_dt'] = prov_ts
                    modified_rows += mask.sum()
                    changed = True
    if changed:
        df.to_parquet(fp, index=False)
        modified_tickers += 1
print(f'\nrcept_dt 수정: {modified_tickers}종목, {modified_rows}행')

# 표본 확인: 수정 후
print(f'\n[표본] 수정 후 rcept_dt:', flush=True)
for tk in sample_tickers:
    fp = CACHE_DIR / f'fs_dart_{tk}.parquet'
    if fp.exists():
        df = pd.read_parquet(fp)
        rev = df[(df['계정'] == '매출액') & (df['공시구분'] == 'q')].tail(2)
        for _, r in rev.iterrows():
            print(f'  {tk} {r["기준일"].date()} rcept_dt={r.get("rcept_dt")}')

# ── Step 3: ranking 재생성 ──
PROV_STATE = str(PROJECT / 'backtest' / 'prov_state_v80')
PROV_BT_EXT = str(PROJECT / 'backtest' / 'prov_bt_extended_v80')

BOOST_ENV = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.00',
    'FACTOR_G_W': '0.55', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z',
    'G_REVENUE_WEIGHT': '0.6', 'MOM_PERIOD': '12m',
    'PYTHONIOENCODING': 'utf-8',
}

os.makedirs(PROV_STATE, exist_ok=True)
os.makedirs(PROV_BT_EXT, exist_ok=True)

print(f'\n=== Ranking 재생성 (잠정 rcept_dt 적용) ===', flush=True)
t0 = time.time()
jobs = [
    ('prov_bt_ext', '20180702', '20201230', PROV_BT_EXT, BOOST_ENV),
    ('prov_state', '20210104', '20260417', PROV_STATE, BOOST_ENV),
]
processes = []
for label, s, e, sdir, env in jobs:
    merged = {**os.environ, **env}
    merged.pop('PRODUCTION_MODE', None)
    log_path = str(PROJECT / 'logs' / f'step6_{label}.log')
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

print(f'재생성 완료: {(time.time()-t0)/60:.1f}분')

# ── Step 4: fs_dart 복원 ──
print(f'\nfs_dart 원본 복원...', flush=True)
for fp in backup_dir.glob('*.parquet'):
    shutil.copy2(fp, CACHE_DIR / fp.name)
print(f'  복원 완료')

# 복원 검증
print(f'\n[표본] 복원 후 rcept_dt (원본과 동일해야):', flush=True)
for tk in sample_tickers[:2]:
    fp = CACHE_DIR / f'fs_dart_{tk}.parquet'
    fp_bak = backup_dir / f'fs_dart_{tk}.parquet'
    if fp.exists() and fp_bak.exists():
        df1 = pd.read_parquet(fp)
        df2 = pd.read_parquet(fp_bak)
        match = df1.equals(df2)
        print(f'  {tk}: {"일치 ✅" if match else "불일치 ❌"}')

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
                with open(fp, 'r', encoding='utf-8') as f: data[k] = json.load(f)
    return data

print(f'\nranking 로드...', flush=True)
bl_boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
pv_boost = load_rankings([PROV_BT_EXT, PROV_STATE])
defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])

common = sorted(set(bl_boost) & set(pv_boost) & set(defense))
print(f'baseline: {len(bl_boost)}일, provisional: {len(pv_boost)}일, 공통: {len(common)}일')

bl_rk = {d: bl_boost[d]['rankings'] for d in common}
pv_rk = {d: pv_boost[d]['rankings'] for d in common}

ohlcv = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kospi = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kp = kospi.iloc[:, 0].fillna(kospi['kospi']).sort_index()
ma170 = kp.rolling(170).mean()

def calc_regime(target_dates):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kp.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 8 and md != s: md = s
        reg[d] = md
    return reg

# 올바른 기간 정의!
PERIODS = {
    '7.8y': ('20180702','20260414'),
    '5.25y': ('20210104','20260414'),
    '2018H2-19': ('20180702','20191231'),
    '2020-21': ('20200102','20211230'),
    '2022-23': ('20220103','20231228'),
    '2024-26': ('20240102','20260414'),
    '2019': ('20190102','20191230'),
    '2020': ('20200102','20201230'),
    '2021': ('20210104','20211230'),
    '2022': ('20220103','20221228'),
    '2023': ('20230102','20231228'),
    '2024': ('20240102','20241230'),
    '2025': ('20250102','20251230'),
    '2026': ('20260102','20260414'),
}

V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)

print(f'\n=== BT 실행 ===', flush=True)
results = []
for label, rk_data in [('baseline', bl_rk), ('provisional', pv_rk)]:
    for pname, (ps, pe) in PERIODS.items():
        pd_ = [d for d in common if ps <= d <= pe]
        if len(pd_) < 20: continue
        tsim = TurboSimulator({d: rk_data[d] for d in pd_}, pd_, ohlcv)
        reg = calc_regime(pd_)
        r = tsim.run_regime(
            defense_params=V80_D, offense_params=V80_O,
            regime_dict=reg, trailing_stop=-0.15,
            g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
            g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
            g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
            g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
        results.append({'version':label,'period':pname,
                       'cal':r['calmar'],'cagr':r['cagr'],'mdd':r['mdd']})
        print(f'  {label:>12} {pname:>12}: Cal={r["calmar"]:.2f} CAGR={r["cagr"]:.1f}%', flush=True)

df = pd.DataFrame(results)
order = ['7.8y','5.25y','2019','2020','2021','2022','2023','2024','2025','2026',
         '2018H2-19','2020-21','2022-23','2024-26']

print(f'\n=== Calmar 비교 ===')
piv = df.pivot(index='period',columns='version',values='cal').reindex([p for p in order if p in df['period'].values])
if 'baseline' in piv.columns and 'provisional' in piv.columns:
    piv['Delta'] = piv['provisional'] - piv['baseline']
print(piv.round(2).to_string())

print(f'\n=== CAGR 비교 ===')
piv_c = df.pivot(index='period',columns='version',values='cagr').reindex([p for p in order if p in df['period'].values])
if 'baseline' in piv_c.columns and 'provisional' in piv_c.columns:
    piv_c['Delta'] = piv_c['provisional'] - piv_c['baseline']
print(piv_c.round(1).to_string())

# WF
print(f'\n=== WF 안정성 ===')
wf_p = ['2018H2-19','2020-21','2022-23','2024-26']
for ver in ['baseline','provisional']:
    wf = [df[(df['version']==ver)&(df['period']==p)]['cal'].values[0] for p in wf_p if len(df[(df['version']==ver)&(df['period']==p)]) > 0]
    if wf:
        print(f'  {ver}: WF=[{", ".join(f"{c:.2f}" for c in wf)}] min={min(wf):.2f} mean={np.mean(wf):.2f} CV={np.std(wf)/np.mean(wf):.2f}')

df.to_csv(str(PROJECT/'backtest'/'step6_provisional_v80.csv'), index=False, encoding='utf-8-sig')
print(f'\n저장: backtest/step6_provisional_v80.csv')
print(f'총 소요: {(time.time()-t0)/60:.1f}분')
