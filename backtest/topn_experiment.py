"""Top N 균등배분 실험 — 현재 v80 (E3X6S3) vs Top N 단순 진입/이탈 전략

User 가설: 1Q 2026 동안 Top 3가 거의 안 변함 → Top N 균등 + 단순 회전이
나을 수도? 여러 N과 기간으로 비교.
"""
import sys, glob, json, os
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT = Path(r'C:\dev')
CACHE_DIR = PROJECT / 'data_cache'
sys.path.insert(0, str(PROJECT / 'backtest'))
from turbo_simulator import TurboSimulator, TurboRunner


def load_rankings_for_years(years):
    """state/bt_YYYY/ranking_*.json + state/ranking_2026*.json"""
    all_rankings = {}
    for year in years:
        if year == '2026':
            pat = str(PROJECT / 'state/ranking_2026*.json')
        else:
            pat = str(PROJECT / f'state/bt_{year}/ranking_*.json')
        for f in sorted(glob.glob(pat)):
            d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            with open(f, encoding='utf-8') as fp:
                data = json.load(fp)
            all_rankings[d] = data.get('rankings', data) if isinstance(data, dict) else data
    return all_rankings


def run_experiment(years, configs, period_label):
    print(f'\n{"="*78}')
    print(f'[기간 {period_label}] 데이터 로드 중...')
    rankings = load_rankings_for_years(years)
    if not rankings:
        print(f'  데이터 없음 → 스킵')
        return []
    dates = sorted(rankings.keys())
    print(f'  {len(dates)}일, {dates[0]} ~ {dates[-1]}')

    prices_file = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                         key=lambda f: f.stem.split('_')[2])[-1]
    prices = pd.read_parquet(prices_file).replace(0, np.nan)

    tsim = TurboSimulator(rankings, dates, prices)
    # 보스트 모드 가중치 (v80): V15 Q0 G55 M30, G_REV=0.6, MOM=12m
    tsim._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.6, 20, mom_type='12m')
    runner = TurboRunner(tsim)

    rows = []
    for cfg in configs:
        r = runner.run(
            cfg['entry'], cfg['exit'], cfg['slots'],
            stop_loss=-0.10,
            trailing_stop=cfg.get('trailing', -0.15),
        )
        rows.append({
            '전략': cfg['name'],
            'E': cfg['entry'], 'X': cfg['exit'], 'S': cfg['slots'],
            'CAGR(%)': r['cagr'],
            'MDD(%)': r['mdd'],
            'Calmar': r['calmar'],
            'Sharpe': r['sharpe'],
            '누적(%)': r['total'],
            '보유수': r['avg_holdings'],
            '벤치CAGR(%)': r['b_cagr'],
            '알파(%)': r['alpha'],
        })
    return rows


def main():
    configs = [
        # 현재 v80 baseline
        {'name': 'v80 baseline', 'entry': 3, 'exit': 6, 'slots': 3},
        # Top N 순수 균등 (entry=exit=N=slots, 트레일링 유지)
        {'name': 'Top 3 균등',  'entry': 3,  'exit': 3,  'slots': 3},
        {'name': 'Top 5 균등',  'entry': 5,  'exit': 5,  'slots': 5},
        {'name': 'Top 10 균등', 'entry': 10, 'exit': 10, 'slots': 10},
        {'name': 'Top 15 균등', 'entry': 15, 'exit': 15, 'slots': 15},
        {'name': 'Top 20 균등', 'entry': 20, 'exit': 20, 'slots': 20},
        # exit 여유두기 (회전 완화)
        {'name': 'Top 5 (X10)',  'entry': 5,  'exit': 10, 'slots': 5},
        {'name': 'Top 10 (X15)', 'entry': 10, 'exit': 15, 'slots': 10},
        {'name': 'Top 20 (X25)', 'entry': 20, 'exit': 25, 'slots': 20},
        # 트레일링 끄기 비교 (Top 5)
        {'name': 'Top 5 균등 (TS off)', 'entry': 5, 'exit': 5, 'slots': 5, 'trailing': None},
    ]

    periods = [
        (['2026'], '2026 YTD (1~5월)'),
        (['2024', '2025', '2026'], '2024~2026 (2.3년)'),
        (['2021', '2022', '2023', '2024', '2025', '2026'], '2021~2026 (5.3년)'),
    ]

    all_results = {}
    for years, label in periods:
        rows = run_experiment(years, configs, label)
        all_results[label] = rows
        if rows:
            df = pd.DataFrame(rows)
            print(f'\n[{label}]')
            print(df.to_string(index=False))

    # CSV 저장
    out_path = Path(r'C:\dev\backtest\topn_experiment_result.csv')
    flat = []
    for label, rows in all_results.items():
        for r in rows:
            flat.append({'기간': label, **r})
    pd.DataFrame(flat).to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f'\n결과 저장: {out_path}')


if __name__ == '__main__':
    main()
