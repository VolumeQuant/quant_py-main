# -*- coding: utf-8 -*-
"""Phase 7b/8: production raw 슬롯 확대 정밀 grid + 대형주 fork + 융합 시뮬"""
import json, sys, re, glob
from pathlib import Path
from collections import defaultdict
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

ohlcv = pd.read_parquet('data_cache/all_ohlcv_20170601_20260529.parquet')
ohlcv.index = pd.to_datetime(ohlcv.index)
bt_dir = Path('backtest/bt_extended_backup_20260513')
files = sorted(bt_dir.glob('ranking_2*.json'))
mc_files = {p.split('_')[-1].replace('.parquet',''): p
            for p in glob.glob('data_cache/market_cap_ALL_*.parquet')}


def run_bt(mcap_cutoff, weights, n_slots=3, exit_rank=4, return_per_ticker=False,
           return_drawdown=False):
    vw, qw, gw, mw = weights
    slot_w = 1 / n_slots
    ticker_pnl = defaultdict(float)
    prev_holdings = {}
    daily_pnl = []   # 일자, 일일 returns sum
    turnover_count = 0

    for f in files:
        d = json.loads(f.read_text(encoding='utf-8'))
        date_str = d.get('date','')
        if not date_str:
            m = re.search(r'ranking_(\d{8})', f.name)
            if m: date_str = m.group(1)
        try: dt = pd.to_datetime(date_str)
        except: continue
        mc_key = date_str
        if mc_key not in mc_files:
            for delta in range(1, 6):
                alt = (dt - pd.Timedelta(days=delta)).strftime('%Y%m%d')
                if alt in mc_files: mc_key = alt; break
        if mc_key not in mc_files: continue
        try: mc_dict = pd.read_parquet(mc_files[mc_key])['시가총액'].to_dict()
        except: continue
        rows = d.get('rankings', [])
        if not rows: continue
        scored = []
        for r in rows:
            if mcap_cutoff and mc_dict.get(r['ticker'], 0) < mcap_cutoff: continue
            s = (r.get('value_s') or 0)*vw + (r.get('quality_s') or 0)*qw + \
                (r.get('growth_s') or 0)*gw + (r.get('momentum_s') or 0)*mw
            scored.append((r['ticker'], s))
        if not scored: continue
        scored.sort(key=lambda x: -x[1])
        new_picks = [t for t, _ in scored[:n_slots]]
        in_top_exit = set(t for t, _ in scored[:exit_rank])
        next_dts = ohlcv.index[ohlcv.index > dt]
        if len(next_dts) == 0: continue
        next_dt = next_dts[0]
        new_holdings = {}
        for tk, entry in prev_holdings.items():
            if tk in in_top_exit: new_holdings[tk] = entry
            else:
                try:
                    exit_c = ohlcv.loc[dt, tk] if tk in ohlcv.columns else None
                    if exit_c and entry and pd.notna(exit_c):
                        ticker_pnl[tk] += (exit_c/entry - 1) * slot_w
                        turnover_count += 1
                except: pass
        for tk in new_picks:
            if tk in new_holdings: continue
            if len(new_holdings) >= n_slots: break
            try:
                ec = ohlcv.loc[next_dt, tk] if tk in ohlcv.columns else None
                if ec and pd.notna(ec): new_holdings[tk] = ec
            except: pass
        prev_holdings = new_holdings
    last_dt = ohlcv.index[-1]
    for tk, entry in prev_holdings.items():
        try:
            exit_c = ohlcv.loc[last_dt, tk] if tk in ohlcv.columns else None
            if exit_c and entry and pd.notna(exit_c):
                ticker_pnl[tk] += (exit_c/entry - 1) * slot_w
        except: pass
    total = sum(ticker_pnl.values()) * 100
    result = {'total': total, 'turnover': turnover_count}
    if return_per_ticker: result['pnl'] = dict(ticker_pnl)
    return result


def measure(mcap, weights, n_slots, exit_rank):
    r = run_bt(mcap, weights, n_slots, exit_rank, return_per_ticker=True)
    pnl = r['pnl']
    sorted_p = sorted(pnl.values(), reverse=True)
    top5 = sum(sorted_p[:5]) * 100
    top10 = sum(sorted_p[:10]) * 100
    return r['total'], r['total'] - top5, r['total'] - top10, r['turnover']


# ===========================================
# Phase 7b: production raw 슬롯 정밀 grid
# ===========================================
print('=== Phase 7b: production raw V15Q00G55M30 슬롯 정밀 grid ===\n')
print(f'{"슬롯":<5} {"Exit":<6} {"Total":>9} {"-Top5":>9} {"-Top10":>9} {"회전":>8}')
print('-' * 55)
prod_raw_w = (0.15, 0.0, 0.55, 0.30)
prod_results = []
for n_slots in [3, 5, 6, 7, 8, 10]:
    for exit_rank in [n_slots+1, n_slots+3, n_slots+5, n_slots+10]:
        t, ft5, ft10, tn = measure(0, prod_raw_w, n_slots, exit_rank)
        print(f'{n_slots:<5} {exit_rank:<6} {t:>+8.0f}% {ft5:>+8.0f}% {ft10:>+8.0f}% {tn:>7}')
        prod_results.append({'slots': n_slots, 'exit': exit_rank, 'total': t, 'top5_excl': ft5, 'top10_excl': ft10, 'turnover': tn})

# 최적: total > +500% + top10 제외 > 0%
robust = [r for r in prod_results if r['top10_excl'] > 0]
robust_sorted = sorted(robust, key=lambda x: -x['total'])[:5]
print('\n=== robust 후보 (Top 10 제외 > 0%) ===')
for r in robust_sorted:
    print(f"  슬롯{r['slots']}/exit{r['exit']}: total={r['total']:+.0f}%, -Top10 {r['top10_excl']:+.0f}%, 회전 {r['turnover']}")

print()
# ===========================================
# Phase 8: 대형주 fork 정밀 grid (5조+, V40Q25G15M20)
# ===========================================
print('=== Phase 8: 대형주 5조+ V40Q25G15M20 슬롯 정밀 grid ===\n')
print(f'{"슬롯":<5} {"Exit":<6} {"Total":>9} {"-Top5":>9} {"-Top10":>9} {"회전":>8}')
print('-' * 55)
large_w = (0.40, 0.25, 0.15, 0.20)
large_results = []
for n_slots in [3, 5, 7, 10]:
    for exit_rank in [n_slots+1, n_slots+3, n_slots+5]:
        t, ft5, ft10, tn = measure(5e12, large_w, n_slots, exit_rank)
        print(f'{n_slots:<5} {exit_rank:<6} {t:>+8.0f}% {ft5:>+8.0f}% {ft10:>+8.0f}% {tn:>7}')
        large_results.append({'slots': n_slots, 'exit': exit_rank, 'total': t, 'top5_excl': ft5, 'top10_excl': ft10})

robust_l = [r for r in large_results if r['top10_excl'] > 0]
robust_l_sorted = sorted(robust_l, key=lambda x: -x['total'])[:5]
print('\n=== 대형주 robust 후보 (Top 10 제외 > 0%) ===')
for r in robust_l_sorted:
    print(f"  슬롯{r['slots']}/exit{r['exit']}: total={r['total']:+.0f}%, -Top10 {r['top10_excl']:+.0f}%")
