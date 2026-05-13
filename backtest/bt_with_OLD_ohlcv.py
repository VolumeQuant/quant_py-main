"""옛 OHLCV (refill 전, 백업)로 BT — baseline 3.97 회복 검증"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from compare_optf_bt import load_rankings, run_v80

PROJECT = Path(__file__).parent.parent

def main():
    print('=== 옛 OHLCV (refill 전, 5/11 백업) BT ===')
    OLD_OHLCV = PROJECT / 'data_cache_ohlcv_backup_20260513' / 'all_ohlcv_20170601_20260511.parquet'
    print(f'  OHLCV: {OLD_OHLCV.name}')
    ohlcv = pd.read_parquet(OLD_OHLCV).replace(0, np.nan)
    print(f'    {len(ohlcv.columns)}종목, {len(ohlcv)}일')

    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    if 'kospi' in kospi_df.columns:
        kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna()
    else:
        kospi = kospi_df.iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()

    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates = sorted(set(boost) & set(defense))
    print(f'  거래일: {len(dates)} ({dates[0]} ~ {dates[-1]})')

    DISP = float(os.environ.get('DISP_MAX', '0')) or None
    if DISP:
        print(f'  이격도20 안전망: {DISP}')

    r = run_v80(boost, defense, dates, ohlcv, kospi, ma170,
                sl=-0.10, ts=-0.15, ts_cd=2, disparity_max=DISP)
    print(f'\n--- 결과 (옛 OHLCV) ---')
    print(f'  Cal       = {r["calmar"]:.3f}')
    print(f'  CAGR      = {r["cagr"]:.1f}%')
    print(f'  MDD       = {r["mdd"]:.1f}%')
    print(f'  Sharpe    = {r["sharpe"]:.3f}')
    print(f'  Sortino   = {r["sortino"]:.3f}')
    print(f'  Total     = {r["total"]:.1f}%')
    print(f'  Avg holds = {r["avg_holdings"]:.1f}')
    print(f'\n  vs 새 OHLCV BT (1.957): Δ {r["calmar"]-1.957:+.3f}')
    print(f'  vs baseline (3.97):    Δ {r["calmar"]-3.97:+.3f}')


if __name__ == '__main__':
    main()
