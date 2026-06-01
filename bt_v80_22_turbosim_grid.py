# -*- coding: utf-8 -*-
"""TurboSim 활용 v80.22 진짜 BT grid
- ranking 한 번 로드 → numpy 사전 추출
- 가중치/슬롯/exit grid 시뮬 = 4ms/run × 1000 = 4초
- universe 필터: ranking 사전 필터 (시총 cutoff별 4 인스턴스)
"""
import json, sys, re, glob
from pathlib import Path
import pandas as pd
import numpy as np
sys.path.insert(0, str(Path('backtest').resolve()))
from turbo_simulator import TurboSimulator, TurboRunner
sys.stdout.reconfigure(encoding='utf-8')

BT_DIR = Path('backtest/state_v80_22_truebt')
mc_files = {p.split('_')[-1].replace('.parquet',''): p
            for p in glob.glob('data_cache/market_cap_ALL_*.parquet')}


def load_rankings(bt_dir):
    """ranking JSON 모두 로드 → {date: [rows]}"""
    files = sorted(Path(bt_dir).glob('ranking_2*.json'))
    all_rankings = {}
    dates = []
    for f in files:
        d = json.loads(f.read_text(encoding='utf-8'))
        date_str = d.get('date','')
        if not date_str:
            m = re.search(r'ranking_(\d{8})', f.name)
            if m: date_str = m.group(1)
        if not date_str: continue
        rows = d.get('rankings', [])
        all_rankings[date_str] = rows
        dates.append(date_str)
    return all_rankings, dates


def filter_by_mcap(all_rankings, dates, mcap_cutoff):
    """universe 필터: 시총 cutoff 이상 종목만"""
    if not mcap_cutoff: return all_rankings
    filtered = {}
    for d in dates:
        rows = all_rankings.get(d, [])
        mc_key = d
        if mc_key not in mc_files:
            for delta in range(1, 6):
                from datetime import datetime, timedelta
                alt = (datetime.strptime(d, '%Y%m%d') - timedelta(days=delta)).strftime('%Y%m%d')
                if alt in mc_files: mc_key = alt; break
        if mc_key not in mc_files:
            filtered[d] = []
            continue
        try:
            mc_dict = pd.read_parquet(mc_files[mc_key])['시가총액'].to_dict()
        except:
            filtered[d] = []
            continue
        filtered[d] = [r for r in rows if mc_dict.get(r['ticker'], 0) >= mcap_cutoff]
    return filtered


def main():
    print('=== TurboSim grid 시작 ===')
    print('1. ranking 로드')
    all_rankings, dates = load_rankings(BT_DIR)
    print(f'  {len(dates)} 거래일')

    print('2. 가격 데이터 (OHLCV) 준비')
    prices = pd.read_parquet('data_cache/all_ohlcv_20170601_20260529.parquet')
    prices.index = pd.to_datetime(prices.index)

    print('3. KOSPI bench')
    bench = pd.read_parquet('data_cache/kospi_yf.parquet')
    bench.index = pd.to_datetime(bench.index)

    # universe별 ranking 필터
    print('4. universe별 ranking 필터 (4 인스턴스)')
    rankings_by_univ = {
        'raw': all_rankings,
        '1조+': filter_by_mcap(all_rankings, dates, 1e12),
        '3조+': filter_by_mcap(all_rankings, dates, 3e12),
        '5조+': filter_by_mcap(all_rankings, dates, 5e12),
    }
    sims = {label: TurboSimulator(r, dates, prices, bench)
            for label, r in rankings_by_univ.items()}

    # 가중치 × 슬롯 grid
    weights_list = [
        ('V15Q00G55M30 (raw)',  0.15, 0.00, 0.55, 0.30),
        ('V40Q25G15M20 (V↑)',   0.40, 0.25, 0.15, 0.20),
        ('V35Q35G15M15 (V+Q)',  0.35, 0.35, 0.15, 0.15),
        ('V50Q20G05M25 (가치)', 0.50, 0.20, 0.05, 0.25),
        ('V30Q30G20M20 (균형)', 0.30, 0.30, 0.20, 0.20),
    ]
    slot_configs = [(3,4), (5,7), (7,10), (10,14), (15,20)]
    g_rev = 0.4  # rev_z 비중 (v80.6.1 3f의 rev_z 비중)

    results = []
    for univ_label, sim in sims.items():
        for w_label, vw, qw, gw, mw in weights_list:
            sim._ensure_cache(vw, qw, gw, mw, g_rev)
            runner = TurboRunner(sim)
            for ns, er in slot_configs:
                r = runner.run(entry_param=ns, exit_param=float(er), max_slots=ns)
                results.append({
                    'univ': univ_label, 'weights': w_label,
                    'slots': ns, 'exit': er,
                    'cagr': r['cagr'], 'mdd': r['mdd'], 'calmar': r['calmar'],
                    'total': r['total'], 'sharpe': r['sharpe'], 'alpha': r['alpha'],
                })
    df = pd.DataFrame(results)

    # KOSPI 압승
    print('\n=== Top 10 by Calmar (KOSPI 우월) ===')
    print(df[df['alpha']>0].sort_values('calmar', ascending=False).head(10).to_string(index=False))

    print('\n=== Top 10 by Total ===')
    print(df.sort_values('total', ascending=False).head(10).to_string(index=False))

    df.to_csv('bt_v80_22_turbosim_results.csv', index=False, encoding='utf-8')
    print(f'\n전체 저장: bt_v80_22_turbosim_results.csv ({len(df)} 시나리오)')


if __name__ == '__main__':
    main()
