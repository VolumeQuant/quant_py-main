"""v76 국면 규칙 탐색 — 공격Top5 × 방어Top5 × 46규칙"""
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
kospi = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet').iloc[:,0].dropna()

mc = pd.read_parquet(sorted(DATA_DIR.glob('market_cap_ALL_*.parquet'))[-1])
big = set(mc[mc['시가총액'] >= 1e11].index)
cols = [c for c in ohlcv.columns if c in big]
br = (ohlcv[cols] > ohlcv[cols].rolling(120).mean()).sum(axis=1) / ohlcv[cols].notna().sum(axis=1)

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    rk[d] = json.load(open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8')).get('rankings', [])

tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
print(f'init: {time.time()-t0:.1f}s', flush=True)

atk_df = pd.read_csv(RESULT_DIR / 'v76_phase2a_attack.csv').sort_values('cal', ascending=False)
def_df = pd.read_csv(RESULT_DIR / 'v76_phase2a_defense.csv').sort_values('cal', ascending=False)

# 국면 규칙 빌드
kospi_ma = {n: kospi.rolling(n).mean() for n in [60, 120, 150, 200, 250]}

# KOSDAQ
kosdaq_f = DATA_DIR / 'kosdaq_yf.parquet'
kosdaq = pd.read_parquet(kosdaq_f).iloc[:,0].dropna() if kosdaq_f.exists() else None
kosdaq_ma = {}
if kosdaq is not None:
    for n in [60, 120]:
        kosdaq_ma[n] = kosdaq.rolling(n).mean()

def build_regime(dates, rule_fn, confirm):
    mode = False; streak = 0; ss = False; rd = {}
    for d in dates:
        ts = pd.Timestamp(d)
        try:
            s = rule_fn(ts)
        except:
            s = mode
        if s == ss: streak += 1
        else: streak = 1; ss = s
        if streak >= confirm and mode != s: mode = s
        rd[d] = mode
    return rd

regime_rules = {}

# Breadth
for thresh in [0.30, 0.35, 0.40, 0.45, 0.50]:
    for confirm in [2, 3, 4, 5]:
        name = f'B126_{int(thresh*100)}_{confirm}d'
        regime_rules[name] = build_regime(dates, lambda ts, t=thresh: br.get(ts, 0.5) >= t, confirm)

# KOSPI MA
for ma_n in [60, 120, 150, 200, 250]:
    ma = kospi_ma[ma_n]
    for confirm in [2, 3, 4, 5]:
        name = f'KP_MA{ma_n}_{confirm}d'
        regime_rules[name] = build_regime(dates, lambda ts, m=ma: kospi.get(ts, 0) > m.get(ts, 0) if ts in kospi.index else True, confirm)

# KOSPI+KOSDAQ 동시
if kosdaq is not None:
    for ma_n in [60, 120]:
        kp_ma = kospi_ma[ma_n]
        kd_ma = kosdaq_ma[ma_n]
        for confirm in [3, 4, 5]:
            name = f'KK_MA{ma_n}_{confirm}d'
            regime_rules[name] = build_regime(dates,
                lambda ts, km=kp_ma, dm=kd_ma: (kospi.get(ts,0) > km.get(ts,0) and kosdaq.get(ts,0) > dm.get(ts,0)) if ts in kospi.index else True,
                confirm)

print(f'국면 규칙: {len(regime_rules)}개', flush=True)

# 공격Top5 × 방어Top5 × 규칙
results = []
total = 5 * 5 * len(regime_rules)
count = 0

for _, a in atk_df.head(5).iterrows():
    op = {'v':a['v']/100,'q':a['q']/100,'g':a['g']/100,'m':a['m']/100,
          'g_rev':a['gr'],'entry':5,'exit':8,'slots':3,'mom':a['mom']}
    for _, d in def_df.head(5).iterrows():
        dp = {'v':d['v']/100,'q':d['q']/100,'g':d['g']/100,'m':d['m']/100,
              'g_rev':d['gr'],'entry':5,'exit':8,'slots':7,'mom':d['mom']}
        for rule_name, rd in regime_rules.items():
            r = tsim.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
            sw = sum(1 for i in range(1,len(dates)) if rd[dates[i]] != rd[dates[i-1]])
            boost_pct = sum(1 for v in rd.values() if v) / len(rd) * 100
            results.append({
                'atk': f"V{int(a['v'])}Q{int(a['q'])}G{int(a['g'])}M{int(a['m'])}g{a['gr']:.1f}{a['mom']}",
                'def': f"V{int(d['v'])}Q{int(d['q'])}G{int(d['g'])}M{int(d['m'])}g{d['gr']:.1f}{d['mom']}",
                'rule': rule_name,
                'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                'sh': r['sharpe'], 'sort': r.get('sortino', 0), 'alpha': r.get('alpha', 0),
                'sw': sw, 'boost': boost_pct,
            })
            count += 1
        if count % 100 == 0:
            print(f'  {count}/{total} ({time.time()-t0:.0f}s)', flush=True)

rdf = pd.DataFrame(results).sort_values('cal', ascending=False)
rdf.to_csv(RESULT_DIR / 'v76_regime_search_full.csv', index=False)
print(f'\n국면서치 {len(results)}개 완료 ({time.time()-t0:.0f}s)', flush=True)
print(f'\nTop 15:', flush=True)
print(rdf.head(15).to_string(index=False), flush=True)

# 규칙별 최고 성과
print(f'\n=== 규칙별 Top1 ===', flush=True)
for rule in rdf.groupby('rule')['cal'].max().sort_values(ascending=False).head(10).index:
    row = rdf[rdf['rule']==rule].sort_values('cal', ascending=False).iloc[0]
    print(f'  {rule:<18} Cal={row["cal"]:.2f} CAGR={row["cagr"]:.1f}% MDD={row["mdd"]:.1f}% sw={row["sw"]}', flush=True)

print(f'\n총: {time.time()-t0:.0f}s', flush=True)
