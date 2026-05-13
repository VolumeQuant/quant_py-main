"""Stage 5/6: 진입/이탈/슬롯 + SL/TS/쿨다운 grid

state 재생성 불필요 (run_v80 파라미터만 변경)
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


def run_bt_param(boost, defense, dates, ohlcv, kospi, ma170,
                 entry_b=3, exit_b=6, slots_b=3,
                 entry_d=3, exit_d=6, slots_d=5,
                 sl=-0.10, ts=-0.15, ts_cd=2, disparity_max=1.5):
    """진입/이탈/슬롯 + SL/TS 파라미터 BT"""
    tsim_b = TurboSimulator({d: boost[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_b._ensure_cache(0.15, 0.00, 0.55, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
    boost_flat = list(tsim_b._cached_flat)
    tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_d._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
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
            entry_p, exit_p, max_slots = entry_b, exit_b, slots_b
        else:
            pipe = defense_flat[i] if i < len(defense_flat) else None
            entry_p, exit_p, max_slots = entry_d, exit_d, slots_d
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
    print('=== Stage 5/6: 진입/이탈/슬롯 + SL/TS grid ===')
    OHLCV = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()
    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates = sorted(set(boost) & set(defense))

    # Stage 5: 진입/이탈/슬롯 (boost + defense 동시)
    print('\n--- Stage 5: 진입/이탈/슬롯 ---')
    s5_results = []
    t0 = time.time()
    for entry_b in [2, 3, 5]:
        for exit_b in [5, 6, 8, 10]:
            for slots_b in [2, 3, 5]:
                for entry_d in [2, 3, 5]:
                    for exit_d in [5, 6, 8, 10]:
                        for slots_d in [3, 5, 7]:
                            r = run_bt_param(boost, defense, dates, ohlcv, kospi, ma170,
                                             entry_b, exit_b, slots_b,
                                             entry_d, exit_d, slots_d)
                            s5_results.append({'eb':entry_b,'xb':exit_b,'sb':slots_b,
                                              'ed':entry_d,'xd':exit_d,'sd':slots_d, **r})
    t1 = time.time()
    print(f'  {len(s5_results)}조합 ({(t1-t0)/60:.1f}분)')
    s5_results.sort(key=lambda x: -x['calmar'])
    print('  Top 5:')
    for r in s5_results[:5]:
        print(f'    eb{r["eb"]} xb{r["xb"]} sb{r["sb"]} | ed{r["ed"]} xd{r["xd"]} sd{r["sd"]}: Cal {r["calmar"]:.3f}')

    # Stage 6: SL/TS/쿨다운 (Stage 5 best 사용)
    print('\n--- Stage 6: SL/TS/쿨다운 ---')
    best5 = s5_results[0]
    print(f'  Stage 5 best: eb{best5["eb"]} xb{best5["xb"]} sb{best5["sb"]} | ed{best5["ed"]} xd{best5["xd"]} sd{best5["sd"]}')
    s6_results = []
    t0 = time.time()
    for sl in [-0.05, -0.07, -0.10, -0.15, -0.20]:
        for ts in [-0.10, -0.15, -0.20, -0.25]:
            for cd in [0, 1, 2, 3, 5]:
                r = run_bt_param(boost, defense, dates, ohlcv, kospi, ma170,
                                 best5['eb'], best5['xb'], best5['sb'],
                                 best5['ed'], best5['xd'], best5['sd'],
                                 sl=sl, ts=ts, ts_cd=cd)
                s6_results.append({'sl':sl,'ts':ts,'cd':cd, **r})
    t1 = time.time()
    print(f'  {len(s6_results)}조합 ({(t1-t0)/60:.1f}분)')
    s6_results.sort(key=lambda x: -x['calmar'])
    print('  Top 5:')
    for r in s6_results[:5]:
        print(f'    SL{r["sl"]:+.2f} TS{r["ts"]:+.2f} cd{r["cd"]}: Cal {r["calmar"]:.3f}')

    pd.DataFrame(s5_results).to_csv(PROJECT/'backtest'/'stage5_entry_results.csv', index=False)
    pd.DataFrame(s6_results).to_csv(PROJECT/'backtest'/'stage6_sl_results.csv', index=False)
    print('\n저장: stage5_entry_results.csv, stage6_sl_results.csv')


if __name__ == '__main__':
    main()
