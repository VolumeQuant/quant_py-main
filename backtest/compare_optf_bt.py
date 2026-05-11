"""v80 BT 비교: 기존 (bt_extended + state) vs 옵션F (bt_optf_boost + bt_optf_defense).

v80.2 파라미터 적용:
  Boost: V15Q0G55M30, 2f(0.6), 12m, E3X6S3, SL=-7%, TS=-10%
  Defense: V30Q15G15M40, 2f(0.7), 6m-1m, E3X6S5, SL=-7%, TS=-10%
  TS 쿨다운: 2일 (v80.1)
  국면: KP_MA170_8d
"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, _calc_metrics

PROJECT = Path(__file__).parent.parent


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


def calc_regime(target_dates, kospi, ma170):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 8 and md != s: md = s
        reg[d] = md
    return reg


def run_v80(boost_rk, defense_rk, dates, ohlcv, kospi, ma170,
            sl=-0.07, ts=-0.10, ts_cd=2):
    """v80.2 + TS 쿨다운 2일."""
    reg = calc_regime(dates, kospi, ma170)
    tsim_b = TurboSimulator({d: boost_rk[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_b._ensure_cache(0.15, 0.00, 0.55, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
    boost_flat = list(tsim_b._cached_flat)

    tsim_d = TurboSimulator({d: defense_rk[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_d._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
    defense_flat = list(tsim_d._cached_flat)

    # 두 시뮬레이터가 같은 종목 인덱스 공유하도록 같은 ohlcv 사용
    price_arr = tsim_b._price_arr
    date_rows = tsim_b._date_row_indices
    n_dates = len(dates)

    portfolio = {}
    peak_prices = {}
    cooldown = {}
    daily_rets = [0.0] * n_dates
    bench_rets = [0.0] * n_dates
    holdings_count = [0] * n_dates
    prev_regime = None

    for i in range(2, n_dates):
        d = dates[i]
        cr = reg.get(d, False)

        if prev_regime is not None and cr != prev_regime:
            portfolio.clear()
            peak_prices.clear()
            cooldown.clear()
        prev_regime = cr

        if cr:
            pipe = boost_flat[i] if i < len(boost_flat) else None
            entry_p, exit_p, max_slots = 3, 6, 3
        else:
            pipe = defense_flat[i] if i < len(defense_flat) else None
            entry_p, exit_p, max_slots = 3, 6, 5

        if pipe is None:
            holdings_count[i] = len(portfolio)
            continue

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
                else:
                    peak_prices[col] = cur_p

        to_remove = []
        for col, ep in portfolio.items():
            cur_p = price_arr[cur_row, col]
            if cur_p != cur_p or cur_p <= 0: continue
            reason = None
            if sl is not None and ep > 0:
                if (cur_p / ep - 1.0) <= sl: reason = 'sl'
            if reason is None and ts is not None:
                pk = peak_prices.get(col, ep)
                if pk > 0 and (cur_p / pk - 1.0) <= ts: reason = 'ts'
            if reason is None and wrank_arr[col] > exit_p:
                reason = 'rank'
            if reason: to_remove.append((col, reason))

        for col, reason in to_remove:
            del portfolio[col]
            if col in peak_prices: del peak_prices[col]
            if reason == 'ts' and ts_cd > 0:
                cooldown[col] = ts_cd

        slots_avail = max_slots - len(portfolio)
        if slots_avail > 0:
            for k in range(len(cand_cols)):
                if slots_avail <= 0: break
                if cand_wranks[k] <= entry_p:
                    c = cand_cols[k]
                    if c not in portfolio and c not in cooldown:
                        portfolio[c] = cand_prices[k]
                        peak_prices[c] = cand_prices[k]
                        slots_avail -= 1

        n_hold = len(portfolio)
        holdings_count[i] = n_hold

        if i + 1 < n_dates and n_hold > 0:
            next_row = date_rows[i + 1]
            if next_row >= 0 and cur_row >= 0:
                total_ret = 0.0
                count = 0
                for col in portfolio:
                    c_p = price_arr[next_row, col]
                    p_p = price_arr[cur_row, col]
                    if c_p == c_p and p_p == p_p and p_p > 0:
                        total_ret += c_p / p_p - 1.0
                        count += 1
                daily_rets[i] = total_ret / count if count > 0 else 0.0

    return _calc_metrics(daily_rets, bench_rets, holdings_count)


def main():
    print('=== 옵션F BT 비교 ===')
    ohlcv_files = sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))
    ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()

    # 기존 v80 BT
    print('\n--- 기존 (bt_extended + state) ---')
    boost_old = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
    def_old = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
    dates_old = sorted(set(boost_old) & set(def_old))
    dates_old = [d for d in dates_old if '20180702' <= d <= '20260430']
    print(f'  거래일: {len(dates_old)}')
    r_old = run_v80(boost_old, def_old, dates_old, ohlcv, kospi, ma170)
    print(f'  Cal={r_old["calmar"]:.3f} CAGR={r_old["cagr"]:.1f}% MDD={r_old["mdd"]:.1f}%')

    # 옵션F BT
    print('\n--- 옵션F (bt_optf_boost + bt_optf_defense) ---')
    boost_new = load_rankings([PROJECT/'backtest'/'bt_optf_boost'])
    def_new = load_rankings([PROJECT/'backtest'/'bt_optf_defense'])
    dates_new = sorted(set(boost_new) & set(def_new))
    dates_new = [d for d in dates_new if '20180702' <= d <= '20260430']
    print(f'  거래일: {len(dates_new)}')
    r_new = run_v80(boost_new, def_new, dates_new, ohlcv, kospi, ma170)
    print(f'  Cal={r_new["calmar"]:.3f} CAGR={r_new["cagr"]:.1f}% MDD={r_new["mdd"]:.1f}%')

    print('\n--- 비교 ---')
    print(f'  Cal:  {r_old["calmar"]:.3f} → {r_new["calmar"]:.3f}  (Δ {r_new["calmar"]-r_old["calmar"]:+.3f})')
    print(f'  CAGR: {r_old["cagr"]:.1f}% → {r_new["cagr"]:.1f}% (Δ {r_new["cagr"]-r_old["cagr"]:+.1f}%p)')
    print(f'  MDD:  {r_old["mdd"]:.1f}% → {r_new["mdd"]:.1f}% (Δ {r_new["mdd"]-r_old["mdd"]:+.1f}%p)')


if __name__ == '__main__':
    main()
