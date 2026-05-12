"""옛 state (옵션F 시대) BT — 비교 baseline"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from compare_optf_bt import load_rankings, run_v80

PROJECT = Path(__file__).parent.parent

def main():
    print('=== 옛 state (옵션F 시대, 5/12 백업) BT ===')
    ohlcv_files = sorted((PROJECT/'data_cache').glob('all_ohlcv_*.parquet'))
    ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
    print(f'  OHLCV: {ohlcv_files[-1].name}')
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()

    # 옛 state 백업
    boost = load_rankings([PROJECT/'state_backup_pre_optf_20260512'])
    defense = load_rankings([PROJECT/'state_backup_pre_optf_20260512'/'defense'])
    dates = sorted(set(boost) & set(defense))
    dates = [d for d in dates if '20210104' <= d <= '20260330']
    print(f'  거래일: {len(dates)} ({dates[0]} ~ {dates[-1]})')

    r = run_v80(boost, defense, dates, ohlcv, kospi, ma170,
                sl=-0.10, ts=-0.15, ts_cd=2)
    print(f'\n  Cal = {r["calmar"]:.3f}')
    print(f'  CAGR = {r["cagr"]:.1f}%')
    print(f'  MDD = {r["mdd"]:.1f}%')

if __name__ == '__main__':
    main()
