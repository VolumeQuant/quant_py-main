"""Stage 2/3: Boost/Defense V/Q/G/M 가중치 grid

state 재생성 불필요 (서브팩터 점수만 재가중)
TurboSimulator._ensure_cache로 가중치 변경.
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, _calc_metrics
from compare_optf_bt import load_rankings, calc_regime

PROJECT = Path(__file__).parent.parent


def run_bt(boost, defense, dates, ohlcv, kospi, ma170,
           V_b, Q_b, G_b, M_b, V_d, Q_d, G_d, M_d,
           g_rev_b=0.6, g_rev_d=0.7, mom_b='12m', mom_d='6m-1m',
           sl=-0.10, ts=-0.15, ts_cd=2, disparity_max=1.5):
    """V/Q/G/M 가중치 변경 BT (이격도 포함)"""
    tsim_b = TurboSimulator({d: boost[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_b._ensure_cache(V_b, Q_b, G_b, M_b, g_rev_b, 20, mom_b, 'rev_z', 'oca_z')
    boost_flat = list(tsim_b._cached_flat)
    tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_d._ensure_cache(V_d, Q_d, G_d, M_d, g_rev_d, 20, mom_d, 'rev_z', 'oca_z')
    defense_flat = list(tsim_d._cached_flat)
    price_arr = tsim_b._price_arr
    date_rows = tsim_b._date_row_indices
    n_dates = len(dates)
    reg = calc_regime(dates, kospi, ma170)

    portfolio = {}; peak_prices = {}; cooldown = {}
    daily_rets = [0.0] * n_dates; bench_rets = [0.0] * n_dates; holdings_count = [0] * n_dates
    prev_regime = None
    for i in range(2, n_dates):
        d = dates[i]
        cr = reg.get(d, False)
        if prev_regime is not None and cr != prev_regime:
            portfolio.clear(); peak_prices.clear(); cooldown.clear()
        prev_regime = cr
        if cr:
            pipe = boost_flat[i] if i < len(boost_flat) else None
            entry_p, exit_p, max_slots = 3, 6, 3
        else:
            pipe = defense_flat[i] if i < len(defense_flat) else None
            entry_p, exit_p, max_slots = 3, 6, 5
        if pipe is None:
            holdings_count[i] = len(portfolio); continue
        wrank_arr, cand_cols, cand_prices, cand_wranks = pipe
        cur_row = date_rows[i]
        if cur_row < 0: continue
        expired = []
        for col in cooldown:
            cooldown[col] -= 1
            if cooldown[col] <= 0: expired.append(col)
        for col in expired: del cooldown[col]
        for col in portfolio:
            cur_p = price_arr[cur_row, col]
            if cur_p == cur_p and cur_p > 0:
                if col in peak_prices:
                    if cur_p > peak_prices[col]: peak_prices[col] = cur_p
                else: peak_prices[col] = cur_p
        to_remove = []
        for col, ep in portfolio.items():
            cur_p = price_arr[cur_row, col]
            if cur_p != cur_p or cur_p <= 0: continue
            reason = None
            if sl is not None and ep > 0 and (cur_p / ep - 1.0) <= sl: reason = 'sl'
            if reason is None and ts is not None:
                pk = peak_prices.get(col, ep)
                if pk > 0 and (cur_p / pk - 1.0) <= ts: reason = 'ts'
            if reason is None and wrank_arr[col] > exit_p: reason = 'rank'
            if reason: to_remove.append((col, reason))
        for col, reason in to_remove:
            del portfolio[col]
            if col in peak_prices: del peak_prices[col]
            if reason == 'ts' and ts_cd > 0: cooldown[col] = ts_cd
        slots_avail = max_slots - len(portfolio)
        if slots_avail > 0:
            for k in range(len(cand_cols)):
                if slots_avail <= 0: break
                if cand_wranks[k] <= entry_p:
                    c = cand_cols[k]
                    if c not in portfolio and c not in cooldown:
                        if disparity_max is not None:
                            ma20_start = max(0, cur_row - 19)
                            ma20_w = price_arr[ma20_start:cur_row+1, c]
                            ma20_w = ma20_w[ma20_w == ma20_w]
                            if len(ma20_w) >= 5:
                                ma20 = ma20_w.mean()
                                cur_p = price_arr[cur_row, c]
                                if ma20 > 0 and cur_p / ma20 > disparity_max: continue
                        portfolio[c] = cand_prices[k]
                        peak_prices[c] = cand_prices[k]
                        slots_avail -= 1
        n_hold = len(portfolio)
        holdings_count[i] = n_hold
        if i + 1 < n_dates and n_hold > 0:
            next_row = date_rows[i + 1]
            if next_row >= 0 and cur_row >= 0:
                total_ret = 0.0; count = 0
                for col in portfolio:
                    c_p = price_arr[next_row, col]
                    p_p = price_arr[cur_row, col]
                    if c_p == c_p and p_p == p_p and p_p > 0:
                        total_ret += c_p / p_p - 1.0; count += 1
                daily_rets[i] = total_ret / count if count > 0 else 0.0
    return _calc_metrics(daily_rets, bench_rets, holdings_count)


def main():
    print('=== Stage 2/3: V/Q/G/M 가중치 grid ===')
    OHLCV = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()
    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates = sorted(set(boost) & set(defense))
    print(f'  거래일: {len(dates)}')

    # Stage 2: Boost — V {0,5,10,15,20,25}, Q {0,5,10}, G {40,50,55,60,70}, M {15,20,25,30,40}
    # 합 = 100. defense는 baseline 고정.
    print('\n--- Stage 2: Boost grid ---')
    boost_results = []
    t0 = time.time()
    for V in [0, 5, 10, 15, 20, 25]:
        for Q in [0, 5, 10]:
            for G in [40, 50, 55, 60, 70]:
                M = 100 - V - Q - G
                if M < 10 or M > 40: continue
                # Baseline defense
                r = run_bt(boost, defense, dates, ohlcv, kospi, ma170,
                           V/100, Q/100, G/100, M/100, 0.30, 0.15, 0.15, 0.40)
                boost_results.append({'kind':'boost', 'V':V, 'Q':Q, 'G':G, 'M':M, **r})
    t1 = time.time()
    boost_results.sort(key=lambda x: -x['calmar'])
    print(f'  {len(boost_results)}조합 완료 ({(t1-t0)/60:.1f}분)')
    print('  Top 5:')
    for r in boost_results[:5]:
        print(f'    V{r["V"]:>2} Q{r["Q"]:>2} G{r["G"]:>2} M{r["M"]:>2}: Cal {r["calmar"]:.3f}  CAGR {r["cagr"]:.1f}%  MDD {r["mdd"]:.1f}%')

    # Stage 3: Defense — V {15,20,25,30,35,40}, Q {5,10,15,20}, G {10,15,20,25}, M {25,30,35,40,50}
    print('\n--- Stage 3: Defense grid ---')
    # Boost = Stage 2 best
    best_b = boost_results[0]
    print(f'  Boost = {best_b["V"]}/{best_b["Q"]}/{best_b["G"]}/{best_b["M"]} 고정')

    def_results = []
    t0 = time.time()
    for V in [15, 20, 25, 30, 35, 40]:
        for Q in [5, 10, 15, 20]:
            for G in [10, 15, 20, 25]:
                M = 100 - V - Q - G
                if M < 25 or M > 55: continue
                r = run_bt(boost, defense, dates, ohlcv, kospi, ma170,
                           best_b['V']/100, best_b['Q']/100, best_b['G']/100, best_b['M']/100,
                           V/100, Q/100, G/100, M/100)
                def_results.append({'kind':'defense', 'V':V, 'Q':Q, 'G':G, 'M':M, **r})
    t1 = time.time()
    def_results.sort(key=lambda x: -x['calmar'])
    print(f'  {len(def_results)}조합 완료 ({(t1-t0)/60:.1f}분)')
    print('  Top 5:')
    for r in def_results[:5]:
        print(f'    V{r["V"]:>2} Q{r["Q"]:>2} G{r["G"]:>2} M{r["M"]:>2}: Cal {r["calmar"]:.3f}  CAGR {r["cagr"]:.1f}%  MDD {r["mdd"]:.1f}%')

    # 저장
    pd.DataFrame(boost_results).to_csv(PROJECT/'backtest'/'stage2_boost_results.csv', index=False)
    pd.DataFrame(def_results).to_csv(PROJECT/'backtest'/'stage3_def_results.csv', index=False)
    print('\n저장: stage2_boost_results.csv, stage3_def_results.csv')


if __name__ == '__main__':
    main()
