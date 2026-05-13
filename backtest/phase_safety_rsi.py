"""Phase 1 (안전망): RSI(14) 임계값 × 5조합 BT
가설: RSI > T 종목 매수 후보 차단 → 알파 개선?

방법:
1. 각 (date, ticker) RSI(14) 계산
2. 임계값 T별: RSI > T 종목을 ranking에서 제외 (재순위)
3. TurboSim BT 실행 (보스트만 변경, defense는 v80 고정)
4. v80 baseline Cal 3.937 대비 비교

후처리: KBI메탈 5/7 차단 여부 + 5/12 -9.4% 회피 효과 확인
"""
import sys, json, glob, copy, time
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
    """전체 종목 × 전체 날짜 RSI(14) 매트릭스"""
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # Wilder smoothing (EMA)
    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi


print('로딩...', flush=True)
boost_rd = load_rk(STATE)
defense_rd = load_rk(STATE / 'defense')
dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].sort_index()
ma170 = kospi.rolling(170).mean()

# 7.8년 기간
pd_ = [d for d in dates if '20180702' <= d <= '20260511']
regime = calc_regime(pd_, kospi, ma170)

# RSI 사전 계산 (전체 OHLCV)
print('RSI 계산 중...', flush=True)
t0 = time.time()
rsi_df = compute_rsi_matrix(ohlcv, period=14)
print(f'  완료 ({time.time()-t0:.1f}s, shape {rsi_df.shape})', flush=True)


def filter_ranking_by_rsi(ranking_list, ts, rsi_threshold):
    """rsi > threshold 종목 제외하고 재순위"""
    if rsi_threshold is None:
        return ranking_list
    new_list = []
    for r in ranking_list:
        t = r['ticker']
        if t in rsi_df.columns:
            rv = rsi_df.loc[ts, t] if ts in rsi_df.index else np.nan
            if pd.notna(rv) and rv > rsi_threshold:
                continue  # 제외
        new_list.append(r)
    # rank/wr 재부여 (TurboSim이 wr 사용)
    new_list.sort(key=lambda x: x.get('weighted_rank', x['rank']))
    for i, r in enumerate(new_list, 1):
        r['rank'] = i
        r['weighted_rank'] = float(i)
    return new_list


V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)

thresholds = [None, 95, 90, 85, 80, 75, 70]
results = []
print('\n=== RSI 안전망 BT ===')
for T in thresholds:
    label = 'baseline (차단없음)' if T is None else f'RSI > {T} 차단'
    # 새 ranking 생성
    new_rk = {}
    for d in pd_:
        ts = pd.Timestamp(d)
        new_rk[d] = filter_ranking_by_rsi(boost_rk[d], ts, T)
    tsim = TurboSimulator(new_rk, pd_, ohlcv)
    r = tsim.run_regime(
        defense_params=V80_D, offense_params=V80_O,
        regime_dict=regime,
        trailing_stop=-0.15, stop_loss=-0.10,
        g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
        g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
        g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
        g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
    )
    results.append({'label': label, 'threshold': T,
                    'cagr': r['cagr'], 'mdd': r['mdd'],
                    'calmar': r['calmar'], 'sharpe': r['sharpe'],
                    'sortino': r['sortino'], 'total': r['total']})
    print(f'  {label:30} Cal={r["calmar"]:.3f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.2f}% 누적={r["total"]:.0f}%', flush=True)

df = pd.DataFrame(results).sort_values('calmar', ascending=False).reset_index(drop=True)
df.to_csv('C:/dev/backtest/phase_safety_rsi_result.csv', index=False, encoding='utf-8-sig')

print('\n=== KBI메탈(024840) 5/7 RSI ===')
kbi_rsi = rsi_df.loc[pd.Timestamp('2026-05-07'), '024840'] if '024840' in rsi_df.columns else None
print(f'  RSI(14) 2026-05-07: {kbi_rsi:.1f}' if kbi_rsi else '  데이터 없음')
print()
print('각 임계값에서 KBI메탈 5/7 차단 여부:')
for T in [None, 95, 90, 85, 80, 75, 70]:
    blocked = (kbi_rsi is not None and T is not None and kbi_rsi > T)
    status = '🚫 차단' if blocked else '✅ 통과'
    if T is None:
        print(f'  baseline: {status}')
    else:
        print(f'  RSI > {T}: {status}')
