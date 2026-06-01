# -*- coding: utf-8 -*-
"""v80.22 진짜 BT (재생성된 baseline) 위에서 사용자 의도 grid 시뮬
- 대형주 fork: 1조+ / 3조+ / 5조+ universe
- 가중치 grid: V40Q25G15M20 / V35Q35G15M15 / V50Q20G05M25 / V15Q00G55M30 (raw)
- 슬롯 3/5/7/10/15 × exit rank
- leave-one-out (Top 5/10 제외)
"""
import json, sys, re, glob
from pathlib import Path
from collections import defaultdict
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

ohlcv = pd.read_parquet('data_cache/all_ohlcv_20170601_20260529.parquet')
ohlcv.index = pd.to_datetime(ohlcv.index)
mc_files = {p.split('_')[-1].replace('.parquet',''): p
            for p in glob.glob('data_cache/market_cap_ALL_*.parquet')}

BT_DIR = Path('backtest/state_v80_22_truebt')


def run_bt(mcap_cutoff, weights, n_slots=3, exit_rank=4, return_per_ticker=False):
    vw, qw, gw, mw = weights
    slot_w = 1 / n_slots
    files = sorted(BT_DIR.glob('ranking_2*.json'))
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
    return (sum(ticker_pnl.values()) * 100, ticker_pnl) if return_per_ticker else sum(ticker_pnl.values()) * 100


def measure(mcap, weights, n_slots, exit_rank):
    t, pnl = run_bt(mcap, weights, n_slots, exit_rank, return_per_ticker=True)
    sorted_p = sorted(pnl.values(), reverse=True)
    top5 = sum(sorted_p[:5]) * 100
    top10 = sum(sorted_p[:10]) * 100
    return t, t - top5, t - top10


def grid_label(mcap):
    return {0: 'raw', 1e12: '1조+', 3e12: '3조+', 5e12: '5조+'}[mcap]


if __name__ == '__main__':
    print('=== v80.22 진짜 BT grid (사용자 의도 = 대형주 fork) ===\n')

    # 시나리오: universe × 가중치
    weights_list = [
        ('V15Q00G55M30 (raw)',    (0.15, 0.00, 0.55, 0.30)),
        ('V40Q25G15M20 (V↑)',     (0.40, 0.25, 0.15, 0.20)),
        ('V35Q35G15M15 (V+Q)',    (0.35, 0.35, 0.15, 0.15)),
        ('V50Q20G05M25 (가치)',   (0.50, 0.20, 0.05, 0.25)),
        ('V30Q30G20M20 (균형)',   (0.30, 0.30, 0.20, 0.20)),
    ]
    universes = [0, 1e12, 3e12, 5e12]
    slot_configs = [(3,4), (5,7), (7,10), (10,14), (15,20)]

    for univ in universes:
        print(f'\n### universe: {grid_label(univ)} ###')
        print(f'{"가중치":<22} {"슬롯/exit":<10} {"Total":>9} {"-Top5":>9} {"-Top10":>9}')
        print('-' * 65)
        for label, w in weights_list:
            for ns, er in slot_configs:
                t, ft5, ft10 = measure(univ, w, ns, er)
                marker = ' ★' if t > 300 and ft10 > 0 else ''
                print(f'{label:<22} {ns:>2}/{er:<7} {t:>+8.0f}% {ft5:>+8.0f}% {ft10:>+8.0f}%{marker}')

    print('\n참고: KOSPI 7년 단순 매수 +273%')
