"""2018H2 매매 종목 추적 — 어떤 종목이 -48.8% 손실 만들었는지"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from compare_optf_bt import load_rankings, calc_regime
from turbo_simulator import TurboSimulator

PROJECT = Path(__file__).parent.parent

def main():
    OHLCV_PATH = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()

    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates = sorted(set(boost) & set(defense))
    dates = [d for d in dates if '20180702' <= d <= '20181231']
    print(f'2018H2: {len(dates)}일 ({dates[0]} ~ {dates[-1]})')

    reg = calc_regime(dates, kospi, ma170)
    boost_d = sum(1 for d in dates if reg.get(d, False))
    print(f'국면: boost {boost_d}일 / defense {len(dates)-boost_d}일')

    # 매매 시뮬 (단순화 — sl=-0.10, ts=-0.15)
    tsim_b = TurboSimulator({d: boost[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_b._ensure_cache(0.15, 0.00, 0.55, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
    boost_flat = list(tsim_b._cached_flat)
    tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_d._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
    defense_flat = list(tsim_d._cached_flat)
    price_arr = tsim_b._price_arr
    date_rows = tsim_b._date_row_indices
    cols_inv = {v: k for k, v in tsim_b._ticker_to_col.items()}

    n_dates = len(dates)
    portfolio = {}  # col → (entry_price, entry_date)
    peak_prices = {}
    cooldown = {}
    prev_regime = None
    sl, ts, ts_cd = -0.10, -0.15, 2
    trades = []  # (ticker, entry_date, entry_price, exit_date, exit_price, ret_pct, exit_reason)

    for i in range(2, n_dates):
        d = dates[i]
        cr = reg.get(d, False)
        if prev_regime is not None and cr != prev_regime:
            cur_row = date_rows[i]
            for col, (ep, ed) in list(portfolio.items()):
                cur_p = price_arr[cur_row, col]
                if cur_p == cur_p and ep > 0:
                    ret = cur_p / ep - 1.0
                    trades.append((cols_inv[col], ed, ep, d, cur_p, ret*100, 'regime'))
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

        if pipe is None: continue
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
        for col, (ep, ed) in portfolio.items():
            cur_p = price_arr[cur_row, col]
            if cur_p != cur_p or cur_p <= 0: continue
            reason = None
            if ep > 0 and (cur_p / ep - 1.0) <= sl: reason = 'sl'
            if reason is None:
                pk = peak_prices.get(col, ep)
                if pk > 0 and (cur_p / pk - 1.0) <= ts: reason = 'ts'
            if reason is None and wrank_arr[col] > exit_p:
                reason = 'rank'
            if reason: to_remove.append((col, reason, cur_p))

        for col, reason, cur_p in to_remove:
            ep, ed = portfolio[col]
            ret = cur_p / ep - 1.0 if ep > 0 else 0
            trades.append((cols_inv[col], ed, ep, d, cur_p, ret*100, reason))
            del portfolio[col]
            if col in peak_prices: del peak_prices[col]
            if reason == 'ts': cooldown[col] = ts_cd

        slots_avail = max_slots - len(portfolio)
        if slots_avail > 0:
            for k in range(len(cand_cols)):
                if slots_avail <= 0: break
                if cand_wranks[k] <= entry_p:
                    c = cand_cols[k]
                    if c not in portfolio and c not in cooldown:
                        # 이격도 1.5
                        ma20_start = max(0, cur_row - 19)
                        ma20_w = price_arr[ma20_start:cur_row+1, c]
                        ma20_w = ma20_w[ma20_w == ma20_w]
                        if len(ma20_w) >= 5:
                            ma20 = ma20_w.mean()
                            cur_p = price_arr[cur_row, c]
                            if ma20 > 0 and cur_p / ma20 > 1.5: continue
                        portfolio[c] = (cand_prices[k], d)
                        peak_prices[c] = cand_prices[k]
                        slots_avail -= 1

    # 마지막 시점 종료
    cur_row = date_rows[-1]
    last_d = dates[-1]
    for col, (ep, ed) in portfolio.items():
        cur_p = price_arr[cur_row, col]
        if cur_p == cur_p:
            ret = cur_p / ep - 1.0 if ep > 0 else 0
            trades.append((cols_inv[col], ed, ep, last_d, cur_p, ret*100, 'end'))

    print(f'\n=== 2018H2 매매 기록 ({len(trades)}건) ===')
    for tk, ed, ep, xd, xp, ret, reason in sorted(trades, key=lambda x: x[5]):
        print(f'  {tk}: {ed}({int(ep)}) → {xd}({int(xp)}) {ret:>+7.1f}% [{reason}]')

    # 손익 분포
    losses = [t for t in trades if t[5] < 0]
    wins = [t for t in trades if t[5] >= 0]
    print(f'\n=== 통계 ===')
    print(f'  총 매매: {len(trades)}')
    print(f'  손실: {len(losses)} 평균 {sum(t[5] for t in losses)/max(len(losses),1):.1f}%')
    print(f'  이익: {len(wins)} 평균 {sum(t[5] for t in wins)/max(len(wins),1):.1f}%')
    print(f'  최대 손실: {min(t[5] for t in trades) if trades else 0:.1f}%')

if __name__ == '__main__':
    main()
