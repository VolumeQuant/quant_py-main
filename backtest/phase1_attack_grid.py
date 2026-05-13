"""Phase 1: Attack grid — TurboSim attack-only (defense는 v80 고정)
새 state(옵션F만) 데이터로 VQGM × G_SUB × MOM 탐색.

축소 범위 (v80 plateau 인근):
  V: 0,5,10,15,20,25 (6)
  Q: 0,5 (2)
  G: 45,50,55,60,65 (5)
  M: 25,30,35,40 (4)
  조건: V+Q+G+M=100
  G_SUB: 2f(rev+oca, g_rev 0.6/0.7), 3f(rev+oca+gp), 3f(rev+oca+rev_accel)
  MOM: 12m, 12m-1m (Phase 5a에서 이게 가장 좋았음)
"""
import sys, json, glob, time
from pathlib import Path
from itertools import product
sys.path.insert(0, 'C:/dev/backtest')
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator

STATE = Path('C:/dev/state')

def load_rk(d):
    data = {}
    for fp in sorted(d.glob('ranking_*.json')):
        k = fp.stem.replace('ranking_','')
        if len(k) != 8 or not k.isdigit(): continue
        if k not in data:
            data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


def calc_regime(target_dates, kospi, ma170, confirm=8):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d]=md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg


print('로딩...', flush=True)
boost_rd = load_rk(STATE)
defense_rd = load_rk(STATE / 'defense')
dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].sort_index()
ma170 = kospi.rolling(170).mean()

# 7.8년만 — grid에서는 단일 기간
pd_ = [d for d in dates if '20180702' <= d <= '20260511']
regime = calc_regime(pd_, kospi, ma170)
tsim = TurboSimulator({d: boost_rk[d] for d in pd_}, pd_, ohlcv)
print(f'7.8년: {len(pd_)}일, 시뮬레이터 초기화 완료', flush=True)

# Defense는 v80 고정
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}

# 조합
VW = [0, 5, 10, 15, 20, 25]
QW = [0, 5]
GW = [45, 50, 55, 60, 65]
MW = [25, 30, 35, 40]
MOMS = ['12m', '12m-1m']
G_SUBS = [
    # (label, sub1, sub2, sub3, w1, w2, w3, g_rev_w_for_2f)
    ('2f_06', 'rev_z', 'oca_z', None, None, None, None, 0.6),
    ('2f_07', 'rev_z', 'oca_z', None, None, None, None, 0.7),
    ('3f_oca_gp', 'rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2, None),
    ('3f_oca_accel', 'rev_z', 'oca_z', 'rev_accel_z', 0.5, 0.3, 0.2, None),
]

combos = []
for v, q, g, m in product(VW, QW, GW, MW):
    if v+q+g+m != 100: continue
    for mom in MOMS:
        for gs in G_SUBS:
            combos.append((v, q, g, m, mom, gs))

print(f'조합 수: {len(combos)}', flush=True)

results = []
t0 = time.time()
for i, (v, q, g, m, mom, gs) in enumerate(combos):
    label, s1, s2, s3, w1, w2, w3, grw = gs
    ofs = {'v': v/100, 'q': q/100, 'g': g/100, 'm': m/100,
           'g_rev': grw if grw else 0.6, 'entry': 3, 'exit': 6, 'slots': 3, 'mom': mom}
    try:
        r = tsim.run_regime(
            defense_params=V80_D, offense_params=ofs,
            regime_dict=regime,
            trailing_stop=-0.15, stop_loss=-0.10,
            g_sub1_o=s1, g_sub2_o=s2, g_sub3_o=s3,
            g_w1_o=w1, g_w2_o=w2, g_w3_o=w3,
            g_sub1_d='rev_z', g_sub2_d='oca_z', g_sub3_d=None,
            g_w1_d=None, g_w2_d=None, g_w3_d=None,
        )
        results.append({
            'v': v, 'q': q, 'g': g, 'm': m, 'mom': mom, 'gs': label,
            'cagr': r['cagr'], 'mdd': r['mdd'], 'calmar': r['calmar'],
            'sharpe': r['sharpe'], 'sortino': r['sortino']
        })
    except Exception as e:
        print(f'  실패 ({v},{q},{g},{m},{mom},{label}): {e}', flush=True)
    if (i+1) % 30 == 0:
        elapsed = time.time() - t0
        rate = (i+1) / elapsed
        remaining = (len(combos)-i-1) / rate / 60
        print(f'  [{i+1}/{len(combos)}] {elapsed:.0f}s, {remaining:.1f}min 남음', flush=True)

df = pd.DataFrame(results).sort_values('calmar', ascending=False).reset_index(drop=True)
df['rank'] = df.index + 1
df.to_csv('C:/dev/backtest/phase1_attack_result.csv', index=False, encoding='utf-8-sig')
print(f'\n=== Phase 1 Top 20 ===')
print(df.head(20).to_string(index=False))
print()
print(f'\nv80 baseline 위치:')
v80 = df[(df['v']==15)&(df['q']==0)&(df['g']==55)&(df['m']==30)&(df['mom']=='12m')&(df['gs']=='2f_06')]
if len(v80):
    print(v80.to_string(index=False))
print(f'\n총 {len(combos)}조합 소요: {(time.time()-t0)/60:.1f}분')
