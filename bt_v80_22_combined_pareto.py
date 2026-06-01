# -*- coding: utf-8 -*-
"""v80.22 BT 위에서 Pareto frontier 탐색
- 가로축: 총 알파 (Total)
- 세로축: robustness (Top 10 제외 알파)
- 운영 부담: 슬롯 수
- universe × 가중치 × 슬롯 grid 결과를 Pareto plot용 데이터로 출력
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


def run_bt(mcap_cutoff, weights, n_slots, exit_rank, return_per_ticker=False):
    vw, qw, gw, mw = weights
    slot_w = 1 / n_slots
    files = sorted(BT_DIR.glob('ranking_2*.json'))
    ticker_pnl = defaultdict(float)
    prev_holdings = {}
    turnover = 0
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
                        turnover += 1
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
            ec = ohlcv.loc[last_dt, tk] if tk in ohlcv.columns else None
            if ec and entry and pd.notna(ec):
                ticker_pnl[tk] += (ec/entry - 1) * slot_w
        except: pass
    total = sum(ticker_pnl.values()) * 100
    return (total, ticker_pnl, turnover) if return_per_ticker else total


def measure(mcap, weights, n_slots, exit_rank):
    t, pnl, tn = run_bt(mcap, weights, n_slots, exit_rank, return_per_ticker=True)
    sorted_p = sorted(pnl.values(), reverse=True)
    top5 = sum(sorted_p[:5]) * 100
    top10 = sum(sorted_p[:10]) * 100
    return t, t - top5, t - top10, tn


if __name__ == '__main__':
    print('=== Pareto frontier (Total × Top10제외 × 슬롯수/회전) ===\n')

    UNIV_LABEL = {0:'raw', 1e12:'1조+', 3e12:'3조+', 5e12:'5조+'}
    W_LABEL = {
        (0.15,0.0,0.55,0.30): 'V15Q00G55M30',
        (0.40,0.25,0.15,0.20): 'V40Q25G15M20',
        (0.35,0.35,0.15,0.15): 'V35Q35G15M15',
        (0.50,0.20,0.05,0.25): 'V50Q20G05M25',
        (0.30,0.30,0.20,0.20): 'V30Q30G20M20',
        (0.20,0.10,0.20,0.50): 'V20Q10G20M50',
        (0.00,0.00,0.00,1.00): 'M100',
    }

    results = []
    for univ in [0, 1e12, 3e12, 5e12]:
        for w in W_LABEL.keys():
            for ns, er in [(3,4), (5,7), (7,10), (10,14), (15,20)]:
                t, ft5, ft10, tn = measure(univ, w, ns, er)
                results.append({
                    'univ': UNIV_LABEL[univ], 'weights': W_LABEL[w],
                    'slots': ns, 'exit': er,
                    'total': t, 'top5_excl': ft5, 'top10_excl': ft10,
                    'turnover': tn,
                })

    # Pareto: total ↑ + top10_excl ↑ (둘 다 클수록 좋음)
    # 운영 부담: slots 적을수록 좋음
    df = pd.DataFrame(results)

    # 알파 > KOSPI +273% 만 필터
    above_kospi = df[df['total'] > 273].sort_values('top10_excl', ascending=False)
    print(f'\n=== KOSPI 압승 (Total > +273%) — Top 15 robust ===')
    print(above_kospi.head(15).to_string(index=False))

    # 운영 부담 5슬롯 이하만
    light = df[(df['total'] > 200) & (df['slots'] <= 5)].sort_values('total', ascending=False)
    print(f'\n=== 운영 부담 ≤ 5슬롯 + Total > +200% — Top 10 ===')
    print(light.head(10).to_string(index=False))

    # 최고 robust (Top 10 제외 > 0%)
    robust = df[df['top10_excl'] > 0].sort_values('total', ascending=False)
    print(f'\n=== 진짜 robust (Top 10 제외 > 0%) — Top 15 ===')
    print(robust.head(15).to_string(index=False))

    # CSV 저장
    df.to_csv('bt_v80_22_pareto_results.csv', index=False, encoding='utf-8')
    print(f'\n전체 결과: bt_v80_22_pareto_results.csv 저장')
