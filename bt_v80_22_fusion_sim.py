# -*- coding: utf-8 -*-
"""v80.22 진짜 BT 위에서 융합 시스템 시뮬
- 시스템 A: production raw 중소형주 (V15Q00G55M30) 또는 production fork 대형주 (V40Q25G15M20 5조+)
- 시스템 B: KR EPS proxy = 5조+ universe + momentum_s 단독 = 대형주 모멘텀 top (EPS revision proxy)
- 합성: 슬롯 분할 (N_A + N_B), 비중은 슬롯 수에 비례

진짜 KR EPS는 yfinance forward EPS 7년 historical 없으니 proxy. 60일 누적 후 진짜 BT 가능.
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


def run_dual_bt(sys_a_cfg, sys_b_cfg, return_per_ticker=False):
    """두 시스템 동시 BT — 슬롯 합산, 종목 중복 시 비중 합산
    sys_cfg = (mcap_cutoff, weights, n_slots, exit_rank)
    """
    files = sorted(BT_DIR.glob('ranking_2*.json'))
    ticker_pnl = defaultdict(float)
    # 시스템별 보유 (독립 슬롯)
    prev_a = {}  # {ticker: entry_close} (시스템 A 슬롯)
    prev_b = {}  # 시스템 B
    slot_w_a = 1 / sys_a_cfg[2] if sys_a_cfg[2] else 0
    slot_w_b = 1 / sys_b_cfg[2] if sys_b_cfg[2] else 0
    # 총 비중 = (n_a + n_b)/(n_a + n_b) = 1. 슬롯 분할 비중
    total_slots = sys_a_cfg[2] + sys_b_cfg[2]
    w_a = sys_a_cfg[2] / total_slots if total_slots else 0
    w_b = sys_b_cfg[2] / total_slots if total_slots else 0

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
        next_dts = ohlcv.index[ohlcv.index > dt]
        if len(next_dts) == 0: continue
        next_dt = next_dts[0]

        def _process(prev, cfg, slot_w, sys_w):
            mc_cut, weights, n_slots, exit_rank = cfg
            if n_slots == 0: return prev, {}
            vw, qw, gw, mw = weights
            scored = []
            for r in rows:
                if mc_cut and mc_dict.get(r['ticker'], 0) < mc_cut: continue
                s = (r.get('value_s') or 0)*vw + (r.get('quality_s') or 0)*qw + \
                    (r.get('growth_s') or 0)*gw + (r.get('momentum_s') or 0)*mw
                scored.append((r['ticker'], s))
            if not scored: return prev, {}
            scored.sort(key=lambda x: -x[1])
            new_picks = [t for t, _ in scored[:n_slots]]
            in_top_exit = set(t for t, _ in scored[:exit_rank])
            new_h = {}
            for tk, entry in prev.items():
                if tk in in_top_exit: new_h[tk] = entry
                else:
                    try:
                        exit_c = ohlcv.loc[dt, tk] if tk in ohlcv.columns else None
                        if exit_c and entry and pd.notna(exit_c):
                            ticker_pnl[tk] += (exit_c/entry - 1) * slot_w * sys_w
                    except: pass
            for tk in new_picks:
                if tk in new_h: continue
                if len(new_h) >= n_slots: break
                try:
                    ec = ohlcv.loc[next_dt, tk] if tk in ohlcv.columns else None
                    if ec and pd.notna(ec): new_h[tk] = ec
                except: pass
            return new_h, {}
        prev_a, _ = _process(prev_a, sys_a_cfg, slot_w_a, w_a)
        prev_b, _ = _process(prev_b, sys_b_cfg, slot_w_b, w_b)

    last_dt = ohlcv.index[-1]
    for tk, entry in prev_a.items():
        try:
            ec = ohlcv.loc[last_dt, tk] if tk in ohlcv.columns else None
            if ec and entry and pd.notna(ec):
                ticker_pnl[tk] += (ec/entry - 1) * slot_w_a * w_a
        except: pass
    for tk, entry in prev_b.items():
        try:
            ec = ohlcv.loc[last_dt, tk] if tk in ohlcv.columns else None
            if ec and entry and pd.notna(ec):
                ticker_pnl[tk] += (ec/entry - 1) * slot_w_b * w_b
        except: pass

    total = sum(ticker_pnl.values()) * 100
    return (total, ticker_pnl) if return_per_ticker else total


def measure_dual(sys_a, sys_b):
    t, pnl = run_dual_bt(sys_a, sys_b, return_per_ticker=True)
    sorted_p = sorted(pnl.values(), reverse=True)
    top5 = sum(sorted_p[:5]) * 100
    top10 = sum(sorted_p[:10]) * 100
    return t, t - top5, t - top10


if __name__ == '__main__':
    print('=== 융합 시뮬 — production fork × KR EPS proxy ===\n')
    print('시스템 A 후보: production raw / production large-fork')
    print('시스템 B 후보: 5조+ momentum 단독 (KR EPS proxy = 대형주 EPS revision 효과)')
    print()

    # 시나리오: (시스템 A, 시스템 B)
    # 형식: (mcap_cutoff, weights(v,q,g,m), n_slots, exit_rank)
    A_RAW = (0, (0.15, 0.0, 0.55, 0.30), 3, 4)
    A_LARGE = (5e12, (0.40, 0.25, 0.15, 0.20), 3, 4)
    B_EPS_PROXY = (5e12, (0.0, 0.0, 0.0, 1.0), 2, 3)  # 대형주 momentum 단독 = KR EPS proxy

    scenarios = [
        # (제목, A, B)
        ('단독: production raw 3슬롯', A_RAW, (0, (0,0,0,0), 0, 0)),
        ('단독: 대형주 fork V40Q25 3슬롯', A_LARGE, (0, (0,0,0,0), 0, 0)),
        ('단독: KR EPS proxy 2슬롯', (0, (0,0,0,0), 0, 0), B_EPS_PROXY),
        ('융합 A: raw 3 + KR EPS proxy 2 (5슬롯)', A_RAW, B_EPS_PROXY),
        ('융합 B: 대형주 3 + KR EPS proxy 2', A_LARGE, B_EPS_PROXY),
        ('융합 C: raw 5 + KR EPS proxy 2 (7슬롯)', (0, A_RAW[1], 5, 7), B_EPS_PROXY),
        ('융합 D: raw 5 + KR EPS proxy 3', (0, A_RAW[1], 5, 7), (5e12, B_EPS_PROXY[1], 3, 5)),
        ('융합 E: 대형주 5 + KR EPS proxy 3', (5e12, A_LARGE[1], 5, 7), (5e12, B_EPS_PROXY[1], 3, 5)),
        ('융합 F: raw 7 + KR EPS proxy 3', (0, A_RAW[1], 7, 10), (5e12, B_EPS_PROXY[1], 3, 5)),
    ]
    print(f'{"시나리오":<45} {"Total":>9} {"-Top5":>9} {"-Top10":>9}')
    print('-' * 75)
    for label, a, b in scenarios:
        t, ft5, ft10 = measure_dual(a, b)
        marker = ' ★' if t > 300 and ft10 > 0 else ''
        print(f'{label:<45} {t:>+8.0f}% {ft5:>+8.0f}% {ft10:>+8.0f}%{marker}')

    print('\n참고: KOSPI 7년 단순 매수 +273%')
    print('\n주의: KR EPS proxy = 대형주 momentum 단독. 진짜 KR EPS (yfinance NTM revision)와 차이 가능.')
    print('       진짜 KR EPS 60일 누적 (~8월) 후 진짜 융합 BT 가능.')
