# -*- coding: utf-8 -*-
"""TurboSim 활용: leave-one-out robust + 융합 시뮬
- 베스트 시나리오 (raw V30Q30G20M20 3/4 등) 종목별 기여도 + Top 5/10 제외 검증
- production raw + KR EPS proxy (5조+ M100) 융합 시뮬
"""
import json, sys, re, glob, time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd
import numpy as np
sys.path.insert(0, str(Path('backtest').resolve()))
from turbo_simulator import TurboSimulator, TurboRunner
sys.stdout.reconfigure(encoding='utf-8')

BT_DIR = Path('backtest/_OBSOLETE_bt_extended_20260513')
mc_files = {p.split('_')[-1].replace('.parquet',''): p
            for p in glob.glob('data_cache/market_cap_ALL_*.parquet')}

# 1. ranking 로드
print('1. ranking 로드')
files = sorted(BT_DIR.glob('ranking_2*.json'))
all_rankings = {}
dates = []
for f in files:
    d = json.loads(f.read_text(encoding='utf-8'))
    date_str = d.get('date','')
    if not date_str:
        m = re.search(r'ranking_(\d{8})', f.name)
        if m: date_str = m.group(1)
    all_rankings[date_str] = d.get('rankings', [])
    dates.append(date_str)
print(f'  {len(dates)} 거래일')

# 2. 가격
prices = pd.read_parquet('data_cache/all_ohlcv_20170601_20260529.parquet')
prices.index = pd.to_datetime(prices.index)
bench = pd.read_parquet('data_cache/kospi_yf.parquet')
bench.index = pd.to_datetime(bench.index)
ohlcv = prices  # alias

# 3. universe별 필터
mc_cache = {}
def get_mc_dict(d):
    mc_key = d
    if mc_key not in mc_files:
        for delta in range(1, 6):
            alt = (datetime.strptime(d,'%Y%m%d') - timedelta(days=delta)).strftime('%Y%m%d')
            if alt in mc_files: mc_key = alt; break
    if mc_key not in mc_files: return {}
    if mc_key not in mc_cache:
        try: mc_cache[mc_key] = pd.read_parquet(mc_files[mc_key])['시가총액'].to_dict()
        except: mc_cache[mc_key] = {}
    return mc_cache[mc_key]

def filter_rankings(mcap_cutoff):
    if not mcap_cutoff: return all_rankings
    return {d: [r for r in all_rankings[d] if get_mc_dict(d).get(r['ticker'], 0) >= mcap_cutoff]
            for d in dates}

# 4. 베스트 시나리오 leave-one-out (raw V30Q30G20M20 3/4)
print('\n2. raw V30Q30G20M20 3/4 leave-one-out 검증')
# TurboSim 직접 사용은 종목별 기여도 추적 X. 직접 시뮬레이션 구현 (vectorized)
def run_simulation_with_per_ticker(rankings, dates, vw, qw, gw, mw, n_slots, exit_rank):
    """TurboSim과 동일 룰, per-ticker 기여 추적"""
    ticker_pnl = defaultdict(float)
    prev_holdings = {}
    slot_w = 1 / n_slots
    for d in dates:
        rows = rankings.get(d, [])
        if not rows: continue
        scored = []
        for r in rows:
            s = (r.get('value_s') or 0)*vw + (r.get('quality_s') or 0)*qw + \
                (r.get('growth_s') or 0)*gw + (r.get('momentum_s') or 0)*mw
            scored.append((r['ticker'], s))
        scored.sort(key=lambda x: -x[1])
        new_picks = [t for t, _ in scored[:n_slots]]
        in_top_exit = set(t for t, _ in scored[:exit_rank])
        dt = pd.Timestamp(d)
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
    return ticker_pnl

# 베스트 시나리오들 leave-one-out
print()
print(f'{"시나리오":<35} {"Total":>9} {"-Top5":>9} {"-Top10":>9}')
print('-' * 70)
scenarios = [
    ('raw V30Q30G20M20 3/4 (BEST)',  all_rankings, 0.30, 0.30, 0.20, 0.20, 3, 4),
    ('raw V40Q25G15M20 7/10',        all_rankings, 0.40, 0.25, 0.15, 0.20, 7, 10),
    ('raw V30Q30G20M20 5/7',         all_rankings, 0.30, 0.30, 0.20, 0.20, 5, 7),
    ('raw V40Q25G15M20 5/10',        all_rankings, 0.40, 0.25, 0.15, 0.20, 5, 10),
    ('raw V15Q00G55M30 (현재) 3/4',  all_rankings, 0.15, 0.00, 0.55, 0.30, 3, 4),
    ('raw V15Q00G55M30 (현재) 7/10', all_rankings, 0.15, 0.00, 0.55, 0.30, 7, 10),
]
for label, r, vw, qw, gw, mw, ns, er in scenarios:
    pnl = run_simulation_with_per_ticker(r, dates, vw, qw, gw, mw, ns, er)
    total = sum(pnl.values()) * 100
    sorted_p = sorted(pnl.values(), reverse=True)
    top5 = sum(sorted_p[:5]) * 100
    top10 = sum(sorted_p[:10]) * 100
    marker = ' ★' if total > 200 and total-top10 > 0 else ''
    print(f'{label:<35} {total:>+8.0f}% {total-top5:>+8.0f}% {total-top10:>+8.0f}%{marker}')

# 5. 융합 시뮬 — TurboSim 활용
print('\n3. 융합 시뮬 (production raw × 5조+ M100 KR EPS proxy)')
sim_raw = TurboSimulator(all_rankings, dates, prices, bench)
sim_5tn = TurboSimulator(filter_rankings(5e12), dates, prices, bench)

# 융합 = 두 시스템 슬롯 결합. TurboSim은 단일 시스템만. 직접 구현으로 융합.
def run_fusion(a_w, b_w, a_slots, a_exit, b_slots, b_exit, a_rankings, b_rankings):
    """a + b 시스템 독립 슬롯, weight 비중 = slot 수 비례"""
    a_vw, a_qw, a_gw, a_mw = a_w
    b_vw, b_qw, b_gw, b_mw = b_w
    ticker_pnl = defaultdict(float)
    prev_a, prev_b = {}, {}
    slot_a = 1 / a_slots if a_slots else 0
    slot_b = 1 / b_slots if b_slots else 0
    total_slots = a_slots + b_slots
    weight_a = a_slots / total_slots
    weight_b = b_slots / total_slots
    for d in dates:
        rows_a = a_rankings.get(d, [])
        rows_b = b_rankings.get(d, [])
        if not rows_a and not rows_b: continue
        dt = pd.Timestamp(d)
        next_dts = ohlcv.index[ohlcv.index > dt]
        if len(next_dts) == 0: continue
        next_dt = next_dts[0]
        # 시스템 A
        if a_slots:
            scored_a = []
            for r in rows_a:
                s = (r.get('value_s') or 0)*a_vw + (r.get('quality_s') or 0)*a_qw + \
                    (r.get('growth_s') or 0)*a_gw + (r.get('momentum_s') or 0)*a_mw
                scored_a.append((r['ticker'], s))
            scored_a.sort(key=lambda x: -x[1])
            picks_a = [t for t,_ in scored_a[:a_slots]]
            top_a = set(t for t,_ in scored_a[:a_exit])
            new_a = {}
            for tk, entry in prev_a.items():
                if tk in top_a: new_a[tk] = entry
                else:
                    try:
                        ec = ohlcv.loc[dt, tk] if tk in ohlcv.columns else None
                        if ec and entry and pd.notna(ec):
                            ticker_pnl[tk] += (ec/entry - 1) * slot_a * weight_a
                    except: pass
            for tk in picks_a:
                if tk in new_a: continue
                if len(new_a) >= a_slots: break
                try:
                    ec = ohlcv.loc[next_dt, tk] if tk in ohlcv.columns else None
                    if ec and pd.notna(ec): new_a[tk] = ec
                except: pass
            prev_a = new_a
        # 시스템 B
        if b_slots:
            scored_b = []
            for r in rows_b:
                s = (r.get('value_s') or 0)*b_vw + (r.get('quality_s') or 0)*b_qw + \
                    (r.get('growth_s') or 0)*b_gw + (r.get('momentum_s') or 0)*b_mw
                scored_b.append((r['ticker'], s))
            scored_b.sort(key=lambda x: -x[1])
            picks_b = [t for t,_ in scored_b[:b_slots]]
            top_b = set(t for t,_ in scored_b[:b_exit])
            new_b = {}
            for tk, entry in prev_b.items():
                if tk in top_b: new_b[tk] = entry
                else:
                    try:
                        ec = ohlcv.loc[dt, tk] if tk in ohlcv.columns else None
                        if ec and entry and pd.notna(ec):
                            ticker_pnl[tk] += (ec/entry - 1) * slot_b * weight_b
                    except: pass
            for tk in picks_b:
                if tk in new_b: continue
                if len(new_b) >= b_slots: break
                try:
                    ec = ohlcv.loc[next_dt, tk] if tk in ohlcv.columns else None
                    if ec and pd.notna(ec): new_b[tk] = ec
                except: pass
            prev_b = new_b
    last_dt = ohlcv.index[-1]
    for tk, entry in prev_a.items():
        try:
            ec = ohlcv.loc[last_dt, tk] if tk in ohlcv.columns else None
            if ec and entry and pd.notna(ec):
                ticker_pnl[tk] += (ec/entry - 1) * slot_a * weight_a
        except: pass
    for tk, entry in prev_b.items():
        try:
            ec = ohlcv.loc[last_dt, tk] if tk in ohlcv.columns else None
            if ec and entry and pd.notna(ec):
                ticker_pnl[tk] += (ec/entry - 1) * slot_b * weight_b
        except: pass
    return ticker_pnl

print()
print(f'{"시나리오":<55} {"Total":>9} {"-Top5":>9} {"-Top10":>9}')
print('-' * 90)
B_PROXY = (0.0, 0.0, 0.0, 1.0)  # 5조+ M100 = KR EPS proxy
filtered_5tn = filter_rankings(5e12)
fusion_scenarios = [
    ('단독 raw V30Q30G20M20 3/4',        (0.30,0.30,0.20,0.20), 3, 4, (0,0,0,0), 0, 0, all_rankings, all_rankings),
    ('단독 raw V15Q00G55M30 3/4 (현재)', (0.15,0.00,0.55,0.30), 3, 4, (0,0,0,0), 0, 0, all_rankings, all_rankings),
    ('단독 5조+ M100 (KR EPS proxy) 3/4',(0,0,0,0), 0, 0,         B_PROXY, 3, 4, all_rankings, filtered_5tn),
    ('융합 1: 균형 3 + KR EPS 2 (5슬롯)', (0.30,0.30,0.20,0.20), 3, 4, B_PROXY, 2, 3, all_rankings, filtered_5tn),
    ('융합 2: 균형 3 + KR EPS 3 (6슬롯)', (0.30,0.30,0.20,0.20), 3, 4, B_PROXY, 3, 4, all_rankings, filtered_5tn),
    ('융합 3: raw 3 + KR EPS 2',         (0.15,0.00,0.55,0.30), 3, 4, B_PROXY, 2, 3, all_rankings, filtered_5tn),
    ('융합 4: raw 5 + KR EPS 2 (7슬롯)', (0.15,0.00,0.55,0.30), 5, 7, B_PROXY, 2, 3, all_rankings, filtered_5tn),
    ('융합 5: V↑ 5 + KR EPS 2',          (0.40,0.25,0.15,0.20), 5, 7, B_PROXY, 2, 3, all_rankings, filtered_5tn),
]
for label, aw, a_slots, a_exit, bw, b_slots, b_exit, ar, br in fusion_scenarios:
    pnl = run_fusion(aw, bw, a_slots, a_exit, b_slots, b_exit, ar, br)
    total = sum(pnl.values()) * 100
    sorted_p = sorted(pnl.values(), reverse=True)
    top5 = sum(sorted_p[:5]) * 100
    top10 = sum(sorted_p[:10]) * 100
    marker = ' ★' if total > 200 and total-top10 > 0 else ''
    print(f'{label:<55} {total:>+8.0f}% {total-top5:>+8.0f}% {total-top10:>+8.0f}%{marker}')

print('\n참고: KOSPI 7년 +273%, v80.22 진짜 추정 = v80.6 × 1.65')
