"""안전망 Phase 3 (v2): ffill로 NaN 해결 후 이격도20 BT
"""
import sys, json, glob
from pathlib import Path
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

pd_ = [d for d in dates if '20180702' <= d <= '20260511']
regime = calc_regime(pd_, kospi, ma170)

# 휴장일 NaN을 전일 값으로 채움 (ffill)
print('지표 계산 (ffill 적용)...', flush=True)
ohlcv_ffill = ohlcv.ffill()
sma5 = ohlcv_ffill.rolling(5, min_periods=5).mean()
sma20 = ohlcv_ffill.rolling(20, min_periods=20).mean()
ratio5 = ohlcv / sma5  # 현재가 (원본)
ratio20 = ohlcv / sma20

# 검증: KBI메탈 이격도 (5/11)
ts = pd.Timestamp('2026-05-11')
print(f'\n=== KBI메탈(024840) 5/11 검증 (ffill 후) ===')
print(f'  가격: {ohlcv.loc[ts, "024840"]}')
print(f'  sma20: {sma20.loc[ts, "024840"]:.0f}')
print(f'  이격도20: {ratio20.loc[ts, "024840"]:.3f}')
print(f'  sma5: {sma5.loc[ts, "024840"]:.0f}')
print(f'  이격도5: {ratio5.loc[ts, "024840"]:.3f}')


def filter_by_metric(ranking_list, ts, metric_df, threshold):
    new_list = []
    for r in ranking_list:
        t = r['ticker']
        if t in metric_df.columns and ts in metric_df.index:
            v = metric_df.loc[ts, t]
            if pd.notna(v) and v > threshold:
                continue
        new_list.append(r)
    new_list.sort(key=lambda x: x.get('weighted_rank', x['rank']))
    for i, r in enumerate(new_list, 1):
        r['rank'] = i; r['weighted_rank'] = float(i)
    return new_list


V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)

def run_bt(new_rk_dict):
    tsim = TurboSimulator(new_rk_dict, pd_, ohlcv)
    return tsim.run_regime(
        defense_params=V80_D, offense_params=V80_O,
        regime_dict=regime,
        trailing_stop=-0.15, stop_loss=-0.10,
        g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
        g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
        g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
        g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
    )

results = []
r = run_bt({d: boost_rk[d] for d in pd_})
results.append({'label':'baseline','t':None,**{k:r[k] for k in ['cagr','mdd','calmar','sharpe','sortino','total']}})
print(f'\nbaseline: Cal={r["calmar"]:.3f}', flush=True)

print('\n=== 이격도20 (ffill) ===')
for T in [1.30, 1.35, 1.40, 1.45, 1.50, 1.55, 1.60, 1.65, 1.70, 1.80, 2.00]:
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_by_metric(boost_rk[d], ts, ratio20, T)
    r = run_bt(new_rk)
    results.append({'label':f'sma20>{T:.2f}','t':T,**{k:r[k] for k in ['cagr','mdd','calmar','sharpe','sortino','total']}})
    print(f'  sma20 > {T:.2f}: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.2f}% 누적={r["total"]:.0f}%', flush=True)

print('\n=== 이격도5 (ffill) ===')
for T in [1.15, 1.20, 1.25, 1.30, 1.40, 1.50]:
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_by_metric(boost_rk[d], ts, ratio5, T)
    r = run_bt(new_rk)
    results.append({'label':f'sma5>{T:.2f}','t':T,**{k:r[k] for k in ['cagr','mdd','calmar','sharpe','sortino','total']}})
    print(f'  sma5 > {T:.2f}: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.2f}% 누적={r["total"]:.0f}%', flush=True)

# 5/11 ranking 시뮬 — 이격도20 > 1.5
print('\n=== 5/11 ranking 시뮬 (이격도20 > 1.5) ===')
ts_511 = pd.Timestamp('2026-05-11')
filtered = filter_by_metric(boost_rk['20260511'], ts_511, ratio20, 1.5)
print('  필터 후 Top 5:')
for r in filtered[:5]:
    rat = ratio20.loc[ts_511, r['ticker']] if r['ticker'] in ratio20.columns else None
    rat_str = f'{rat:.2f}' if pd.notna(rat) else 'N/A'
    print(f'    {r["rank"]}위 {r["ticker"]} {r["name"]} (이격도20 {rat_str})')

df = pd.DataFrame(results).sort_values('calmar', ascending=False).reset_index(drop=True)
df.to_csv('C:/dev/backtest/phase_safety_sma20_v2_result.csv', index=False, encoding='utf-8-sig')
print('\n=== Top 5 (Cal 정렬) ===')
print(df.head(5).to_string(index=False))
