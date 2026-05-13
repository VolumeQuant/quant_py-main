"""안전망 Phase 3: 이격도20일 미세 조정 + KBI 차단 실제 검증
- 이격도20: 1.30, 1.35, 1.40, 1.45, 1.50, 1.55, 1.60, 1.65, 1.70 (9조합)
- + KBI메탈 시점별 이격도20 확인
- + 5/11 표본 ranking 시뮬 (실제 진입 가능 종목)
"""
import sys, json, glob, time
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

# 이격도 20일
sma20 = ohlcv.rolling(20, min_periods=20).mean()
ratio20 = ohlcv / sma20

# 이격도 5일 (Phase 2 best도 비교)
sma5 = ohlcv.rolling(5, min_periods=5).mean()
ratio5 = ohlcv / sma5


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
# baseline
r = run_bt({d: boost_rk[d] for d in pd_})
results.append({'label': 'baseline', 't': None, **{k: r[k] for k in ['cagr','mdd','calmar','sharpe','sortino','total']}})
print(f'\nbaseline: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.2f}%', flush=True)

print('\n=== 이격도20 미세 조정 ===', flush=True)
for T in [1.30, 1.35, 1.40, 1.45, 1.50, 1.55, 1.60, 1.65, 1.70]:
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_by_metric(boost_rk[d], ts, ratio20, T)
    r = run_bt(new_rk)
    results.append({'label': f'sma20>{T:.2f}', 't': T, **{k: r[k] for k in ['cagr','mdd','calmar','sharpe','sortino','total']}})
    print(f'  sma20 > {T:.2f}: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.2f}% 누적={r["total"]:.0f}%', flush=True)

# KBI메탈 시점별 이격도20 검증
print('\n=== KBI메탈 시점별 이격도20 ===', flush=True)
for d in ['20260427','20260428','20260429','20260430','20260504','20260506','20260507','20260508','20260511']:
    ts = pd.Timestamp(d)
    px = ohlcv.loc[ts, '024840'] if ts in ohlcv.index else None
    sma = sma20.loc[ts, '024840'] if ts in sma20.index else None
    ratio = ratio20.loc[ts, '024840'] if ts in ratio20.index else None
    if pd.notna(px) and pd.notna(sma):
        blocked = '🚫' if ratio > 1.5 else '✅'
        print(f'  {d}: 가격 {px:.0f}, 20일평균 {sma:.0f}, 이격도 {ratio:.2f} {blocked}', flush=True)
    else:
        print(f'  {d}: 데이터 없음', flush=True)

# 5/11 ranking 시뮬: 이격도20 > 1.5 적용 시 매수 후보 변화
print('\n=== 5/11 ranking 시뮬 (이격도20 > 1.5 적용) ===', flush=True)
ts_511 = pd.Timestamp('2026-05-11')
original = boost_rk['20260511']
filtered = filter_by_metric(original, ts_511, ratio20, 1.5)

# 원본 Top 5
print('  원본 Top 5:')
for r in original[:5]:
    rat = ratio20.loc[ts_511, r['ticker']] if r['ticker'] in ratio20.columns else None
    rat_str = f'{rat:.2f}' if pd.notna(rat) else 'N/A'
    print(f'    {r["rank"]}위 {r["ticker"]} {r["name"]} (이격도20 {rat_str})')
print()
print('  필터 후 Top 5:')
for r in filtered[:5]:
    rat = ratio20.loc[ts_511, r['ticker']] if r['ticker'] in ratio20.columns else None
    rat_str = f'{rat:.2f}' if pd.notna(rat) else 'N/A'
    print(f'    {r["rank"]}위 {r["ticker"]} {r["name"]} (이격도20 {rat_str})')

# 결과 정리
df = pd.DataFrame(results).sort_values('calmar', ascending=False).reset_index(drop=True)
df.to_csv('C:/dev/backtest/phase_safety_sma20_result.csv', index=False, encoding='utf-8-sig')
print('\n=== Top 5 (Cal 정렬) ===')
print(df.head(5).to_string(index=False))
