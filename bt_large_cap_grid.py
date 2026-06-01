# -*- coding: utf-8 -*-
"""대형주 production fork — V/Q/G/M weight × 슬롯 수 × exit rank grid search
+ fragility 측정 (top 5 제외 알파)"""
import json, sys, re, glob, argparse
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


def run_bt(mcap_cutoff, weights, n_slots=3, exit_rank=4, return_per_ticker=False):
    """ranking JSON 활용 BT. weights=(vw,qw,gw,mw). slot_w = 1/n_slots."""
    vw, qw, gw, mw = weights
    slot_w = 1 / n_slots
    ticker_pnl = defaultdict(float)
    prev_holdings = {}
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
            if mc_dict.get(r['ticker'], 0) < mcap_cutoff: continue
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
    return (total, ticker_pnl) if return_per_ticker else total


def measure_fragility(mcap, weights, n_slots, exit_rank):
    total, pnl = run_bt(mcap, weights, n_slots, exit_rank, return_per_ticker=True)
    top5 = sorted(pnl.values(), reverse=True)[:5]
    top5_sum = sum(top5) * 100
    top10 = sorted(pnl.values(), reverse=True)[:10]
    top10_sum = sum(top10) * 100
    return total, total - top5_sum, total - top10_sum


if __name__ == '__main__':
    # Phase 7: 슬롯 확대 효과 (V40Q25G15M20 5조+ 기준)
    print('=== Phase 7: 슬롯 확대 grid (5조+ V40Q25G15M20) ===\n')
    print(f'{"슬롯":<5} {"Exit":<6} {"Total":>8} {"-Top5":>8} {"-Top10":>8}')
    print('-' * 45)
    rows = []
    for n_slots, exit_rank in [(3,4), (5,7), (5,10), (7,10), (7,14), (10,14), (10,20)]:
        t, ft5, ft10 = measure_fragility(5e12, (0.40, 0.25, 0.15, 0.20), n_slots, exit_rank)
        print(f'{n_slots:<5} {exit_rank:<6} {t:>+7.0f}% {ft5:>+7.0f}% {ft10:>+7.0f}%')
        rows.append((n_slots, exit_rank, t, ft5, ft10))

    print('\n=== production raw 비교 (V15Q00G55M30 중소형 포함) ===')
    print(f'{"슬롯":<5} {"Exit":<6} {"Total":>8} {"-Top5":>8} {"-Top10":>8}')
    print('-' * 45)
    for n_slots, exit_rank in [(3,4), (5,7), (5,10), (7,10), (10,14)]:
        t, ft5, ft10 = measure_fragility(0, (0.15, 0.0, 0.55, 0.30), n_slots, exit_rank)
        print(f'{n_slots:<5} {exit_rank:<6} {t:>+7.0f}% {ft5:>+7.0f}% {ft10:>+7.0f}%')
