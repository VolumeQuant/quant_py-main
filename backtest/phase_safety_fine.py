"""안전망 Phase 2: RSI 미세 조정 + 이격도 단독 BT
- RSI: 82, 83, 84, 85, 86, 87, 88
- 이격도 5일: 1.2, 1.3, 1.4, 1.5, 1.7, 2.0
- 이격도 20일: 1.3, 1.5, 1.8, 2.0, 2.5
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


def compute_rsi_matrix(prices, period=14):
    delta = prices.diff()
    gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute_sma_ratio(prices, period):
    """현재가 / N일 평균"""
    sma = prices.rolling(period, min_periods=period).mean()
    return prices / sma


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

print('지표 계산...', flush=True)
rsi_df = compute_rsi_matrix(ohlcv, 14)
sma5_ratio = compute_sma_ratio(ohlcv, 5)
sma20_ratio = compute_sma_ratio(ohlcv, 20)
print('  완료', flush=True)


def filter_by_metric(ranking_list, ts, metric_df, threshold, direction='gt'):
    """metric > threshold (또는 < threshold) 종목 제외 후 재순위"""
    new_list = []
    for r in ranking_list:
        t = r['ticker']
        if t in metric_df.columns and ts in metric_df.index:
            v = metric_df.loc[ts, t]
            if pd.notna(v):
                if direction == 'gt' and v > threshold:
                    continue
                if direction == 'lt' and v < threshold:
                    continue
        new_list.append(r)
    new_list.sort(key=lambda x: x.get('weighted_rank', x['rank']))
    for i, r in enumerate(new_list, 1):
        r['rank'] = i; r['weighted_rank'] = float(i)
    return new_list


V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)


def run_bt(new_rk_dict, label):
    tsim = TurboSimulator(new_rk_dict, pd_, ohlcv)
    r = tsim.run_regime(
        defense_params=V80_D, offense_params=V80_O,
        regime_dict=regime,
        trailing_stop=-0.15, stop_loss=-0.10,
        g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
        g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
        g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
        g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
    )
    return {'label': label, 'cagr': r['cagr'], 'mdd': r['mdd'],
            'calmar': r['calmar'], 'sharpe': r['sharpe'],
            'sortino': r['sortino'], 'total': r['total']}


results = []
# baseline
print('\n=== Baseline ===', flush=True)
results.append(run_bt({d: boost_rk[d] for d in pd_}, 'baseline'))
print(f'  baseline Cal={results[-1]["calmar"]:.3f}', flush=True)

print('\n=== RSI 미세 조정 ===', flush=True)
for T in [82, 83, 84, 85, 86, 87, 88]:
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_by_metric(boost_rk[d], ts, rsi_df, T)
    r = run_bt(new_rk, f'RSI > {T}')
    kbi_rsi = rsi_df.loc[pd.Timestamp('2026-05-07'), '024840'] if '024840' in rsi_df.columns else None
    blocked = '🚫' if (kbi_rsi is not None and kbi_rsi > T) else '✅'
    results.append(r)
    print(f'  RSI > {T}: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% 누적={r["total"]:.0f}% KBI:{blocked}', flush=True)

print('\n=== 이격도 5일 ===', flush=True)
for T in [1.2, 1.3, 1.4, 1.5, 1.7, 2.0]:
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_by_metric(boost_rk[d], ts, sma5_ratio, T)
    r = run_bt(new_rk, f'sma5 > {T}')
    kbi_v = sma5_ratio.loc[pd.Timestamp('2026-05-07'), '024840'] if '024840' in sma5_ratio.columns else None
    blocked = '🚫' if (kbi_v is not None and kbi_v > T) else '✅'
    results.append(r)
    print(f'  sma5 > {T}: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% 누적={r["total"]:.0f}% KBI({kbi_v:.2f}):{blocked}', flush=True)

print('\n=== 이격도 20일 ===', flush=True)
for T in [1.3, 1.5, 1.8, 2.0, 2.5]:
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_by_metric(boost_rk[d], ts, sma20_ratio, T)
    r = run_bt(new_rk, f'sma20 > {T}')
    kbi_v = sma20_ratio.loc[pd.Timestamp('2026-05-07'), '024840'] if '024840' in sma20_ratio.columns else None
    blocked = '🚫' if (kbi_v is not None and kbi_v > T) else '✅'
    results.append(r)
    print(f'  sma20 > {T}: Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% 누적={r["total"]:.0f}% KBI({kbi_v:.2f}):{blocked}', flush=True)

df = pd.DataFrame(results).sort_values('calmar', ascending=False).reset_index(drop=True)
df.to_csv('C:/dev/backtest/phase_safety_fine_result.csv', index=False, encoding='utf-8-sig')
print('\n=== Top 10 (Calmar 정렬) ===')
print(df.head(10).to_string(index=False))
