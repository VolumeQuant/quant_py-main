# -*- coding: utf-8 -*-
"""TurboSim 즉시 grid — _OBSOLETE_bt_extended_20260513 (옵션F 제거된 v80.6 ranking)
+ universe(시총) 필터 + 가중치 × 슬롯 grid

주의: v80.6 기준이라 v80.20 신팩터(mom_10/vol_low) + v80.7 계절성 + v80.12 D6 미반영.
v80.6 → v80.22 진화 Cal 1.86 → 3.06 = 1.65배 알파 증폭.
따라서 v80.22 추정 = 결과 × 1.65 (대형주는 신팩터 영향 작아서 보정 작음)
"""
import json, sys, re, glob
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
sys.path.insert(0, str(Path('backtest').resolve()))
from turbo_simulator import TurboSimulator, TurboRunner
sys.stdout.reconfigure(encoding='utf-8')

BT_DIR = Path('backtest/_OBSOLETE_bt_extended_20260513')
mc_files = {p.split('_')[-1].replace('.parquet',''): p
            for p in glob.glob('data_cache/market_cap_ALL_*.parquet')}


def load_rankings(bt_dir):
    files = sorted(Path(bt_dir).glob('ranking_2*.json'))
    print(f'  ranking 파일: {len(files)}')
    all_rankings = {}
    dates = []
    for f in files:
        d = json.loads(f.read_text(encoding='utf-8'))
        date_str = d.get('date','')
        if not date_str:
            m = re.search(r'ranking_(\d{8})', f.name)
            if m: date_str = m.group(1)
        if not date_str: continue
        all_rankings[date_str] = d.get('rankings', [])
        dates.append(date_str)
    return all_rankings, dates


def filter_by_mcap(all_rankings, dates, mcap_cutoff):
    if not mcap_cutoff: return all_rankings
    filtered = {}
    mc_cache = {}
    for d in dates:
        rows = all_rankings.get(d, [])
        mc_key = d
        if mc_key not in mc_files:
            for delta in range(1, 6):
                alt = (datetime.strptime(d,'%Y%m%d') - timedelta(days=delta)).strftime('%Y%m%d')
                if alt in mc_files: mc_key = alt; break
        if mc_key not in mc_files:
            filtered[d] = []; continue
        if mc_key not in mc_cache:
            try: mc_cache[mc_key] = pd.read_parquet(mc_files[mc_key])['시가총액'].to_dict()
            except: mc_cache[mc_key] = {}
        mc_dict = mc_cache[mc_key]
        filtered[d] = [r for r in rows if mc_dict.get(r['ticker'], 0) >= mcap_cutoff]
    return filtered


def main():
    print('=== TurboSim 즉시 grid 시작 ===\n')
    print('1. ranking 로드 (_OBSOLETE = v80.6 옵션F 제거)')
    all_rankings, dates = load_rankings(BT_DIR)

    print('2. 가격 / KOSPI bench 로드')
    prices = pd.read_parquet('data_cache/all_ohlcv_20170601_20260529.parquet')
    prices.index = pd.to_datetime(prices.index)
    bench = pd.read_parquet('data_cache/kospi_yf.parquet')
    bench.index = pd.to_datetime(bench.index)

    print('3. universe 4벌 ranking 필터')
    rankings_by_univ = {
        'raw': all_rankings,
        '1조+': filter_by_mcap(all_rankings, dates, 1e12),
        '3조+': filter_by_mcap(all_rankings, dates, 3e12),
        '5조+': filter_by_mcap(all_rankings, dates, 5e12),
    }
    for label, r in rankings_by_univ.items():
        avg_n = sum(len(v) for v in r.values()) / max(len(r), 1)
        print(f'  {label}: 일평균 {avg_n:.0f} 종목')

    print('4. TurboSimulator 4 인스턴스 생성 (한 번만)')
    sims = {}
    for label, r in rankings_by_univ.items():
        try:
            sims[label] = TurboSimulator(r, dates, prices, bench)
            print(f'  {label} OK')
        except Exception as e:
            print(f'  {label} 실패: {e}')

    weights_list = [
        ('V15Q00G55M30 (raw)',  0.15, 0.00, 0.55, 0.30),
        ('V40Q25G15M20 (V↑)',   0.40, 0.25, 0.15, 0.20),
        ('V35Q35G15M15 (V+Q)',  0.35, 0.35, 0.15, 0.15),
        ('V50Q20G05M25 (가치)', 0.50, 0.20, 0.05, 0.25),
        ('V30Q30G20M20 (균형)', 0.30, 0.30, 0.20, 0.20),
        ('V20Q10G20M50 (M↑)',   0.20, 0.10, 0.20, 0.50),
        ('M100',                 0.00, 0.00, 0.00, 1.00),
    ]
    slot_configs = [(3,4), (3,6), (5,7), (5,10), (7,10), (10,14), (15,20)]
    g_rev = 0.4

    print(f'\n5. grid 실행: {len(sims)} universe × {len(weights_list)} 가중치 × {len(slot_configs)} 슬롯 = {len(sims)*len(weights_list)*len(slot_configs)} 시나리오\n')

    import time
    results = []
    t0 = time.time()
    for univ_label, sim in sims.items():
        for w_label, vw, qw, gw, mw in weights_list:
            try:
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
            except Exception as e:
                print(f'    {univ_label} {w_label}: {e}')
    elapsed = time.time() - t0
    print(f'시뮬 완료: {elapsed:.1f}초 ({len(results)} 시나리오)\n')

    df = pd.DataFrame(results)
    df.to_csv('bt_v80_6_turbosim_results.csv', index=False, encoding='utf-8')

    # KOSPI alpha 양수
    print('=== Top 15 by Calmar (KOSPI 우월 = alpha > 0) ===')
    pos = df[df['alpha']>0].sort_values('calmar', ascending=False).head(15)
    print(pos.to_string(index=False))

    print('\n=== Top 10 by Total ===')
    print(df.sort_values('total', ascending=False).head(10).to_string(index=False))

    print('\n=== Top 10 by Calmar (전체) ===')
    print(df.sort_values('calmar', ascending=False).head(10).to_string(index=False))

    print(f'\n저장: bt_v80_6_turbosim_results.csv ({len(df)} 시나리오)')
    print('\n주의: v80.6 기준. v80.22 추정 = × 1.65 (신팩터/계절성/QoQ 진화 효과). 대형주는 보정 작음.')


if __name__ == '__main__':
    main()
