"""Stage 1: 국면 판단 grid — MA{120,150,170,200,250} × 확인일수{3,5,7,8,10,15}

state 재생성 불필요 (ranking 그대로 + 국면 계산만 변경)
이격도 1.5 적용, SL/TS 현재 -10%/-15%
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from compare_optf_bt import load_rankings, run_v80

PROJECT = Path(__file__).parent.parent

# calc_regime 재정의 (MA, 확인일수 파라미터)
def calc_regime_param(target_dates, kospi, ma_window, confirm_days):
    ma = kospi.rolling(ma_window).mean()
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = ma.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm_days and md != s: md = s
        reg[d] = md
    return reg


def run_v80_with_regime(boost_rk, defense_rk, dates, ohlcv, kospi, regime,
                        sl=-0.10, ts=-0.15, ts_cd=2, disparity_max=1.5):
    """run_v80 인라인 — 외부 regime 사용"""
    from turbo_simulator import TurboSimulator, _calc_metrics
    tsim_b = TurboSimulator({d: boost_rk[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_b._ensure_cache(0.15, 0.00, 0.55, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
    boost_flat = list(tsim_b._cached_flat)
    tsim_d = TurboSimulator({d: defense_rk[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_d._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
    defense_flat = list(tsim_d._cached_flat)
    price_arr = tsim_b._price_arr
    date_rows = tsim_b._date_row_indices
    n_dates = len(dates)
    portfolio = {}; peak_prices = {}; cooldown = {}
    daily_rets = [0.0] * n_dates; bench_rets = [0.0] * n_dates; holdings_count = [0] * n_dates
    prev_regime = None
    for i in range(2, n_dates):
        d = dates[i]
        cr = regime.get(d, False)
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
    print('=== Stage 1: 국면 grid (MA × 확인일수) ===')
    OHLCV = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()

    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates = sorted(set(boost) & set(defense))
    print(f'  거래일: {len(dates)}')

    MAS = [120, 150, 170, 200, 250]
    DAYS = [3, 5, 7, 8, 10, 15]

    results = []
    t0 = time.time()
    for ma_w in MAS:
        for cd in DAYS:
            t_one = time.time()
            reg = calc_regime_param(dates, kospi, ma_w, cd)
            r = run_v80_with_regime(boost, defense, dates, ohlcv, kospi, reg,
                                     sl=-0.10, ts=-0.15, ts_cd=2, disparity_max=1.5)
            elapsed_one = time.time() - t_one
            results.append({'MA': ma_w, 'days': cd, **r, 'elapsed': round(elapsed_one,1)})
            mark = ' ★' if (ma_w==170 and cd==8) else ''
            print(f'  MA{ma_w:>3} {cd:>2}d: Cal {r["calmar"]:>5.3f}  CAGR {r["cagr"]:>5.1f}%  MDD {r["mdd"]:>4.1f}%  ({elapsed_one:.0f}s){mark}')

    elapsed = time.time() - t0
    print(f'\n총 {len(results)}조합, {elapsed/60:.1f}분')

    # Top 5
    results.sort(key=lambda x: -x['calmar'])
    print('\n=== Top 5 ===')
    for r in results[:5]:
        print(f'  MA{r["MA"]:>3} {r["days"]:>2}d: Cal {r["calmar"]:.3f}  CAGR {r["cagr"]:.1f}%  MDD {r["mdd"]:.1f}%')

    # 저장
    out = PROJECT / 'backtest' / 'stage1_regime_results.csv'
    pd.DataFrame(results).to_csv(out, index=False)
    print(f'\n저장: {out}')


if __name__ == '__main__':
    main()
