"""연도별 + 모드별 BT 분석"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from compare_optf_bt import load_rankings, run_v80, calc_regime
from turbo_simulator import _calc_metrics

PROJECT = Path(__file__).parent.parent

def main():
    OHLCV_PATH = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()

    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates_all = sorted(set(boost) & set(defense))
    print(f'전체 거래일: {len(dates_all)} ({dates_all[0]} ~ {dates_all[-1]})')

    # 1. 국면 분포
    reg = calc_regime(dates_all, kospi, ma170)
    boost_days = sum(1 for d in dates_all if reg.get(d, False))
    defense_days = sum(1 for d in dates_all if not reg.get(d, False))
    print(f'\n국면 분포: boost {boost_days}일 ({100*boost_days/len(dates_all):.0f}%), defense {defense_days}일 ({100*defense_days/len(dates_all):.0f}%)')

    # 2. 연도별 단독 BT
    print(f'\n=== 연도별 BT (이격도 1.5) ===')
    print(f'{"연도":<6}{"일수":>5}{"boost일":>8}{"def일":>6}{"Cal":>8}{"CAGR%":>8}{"MDD%":>8}{"Sharpe":>8}')
    for yr in range(2018, 2027):
        yr_str = f'{yr:04d}'
        d_yr = [d for d in dates_all if d.startswith(yr_str)]
        if len(d_yr) < 30: continue
        b_yr = sum(1 for d in d_yr if reg.get(d, False))
        d_yr_def = len(d_yr) - b_yr
        try:
            r = run_v80(boost, defense, d_yr, ohlcv, kospi, ma170,
                        sl=-0.10, ts=-0.15, ts_cd=2, disparity_max=1.5)
            print(f'{yr:<6}{len(d_yr):>5}{b_yr:>8}{d_yr_def:>6}{r["calmar"]:>8.2f}{r["cagr"]:>8.1f}{r["mdd"]:>8.1f}{r["sharpe"]:>8.2f}')
        except Exception as e:
            print(f'{yr:<6}: ERR {e}')

if __name__ == '__main__':
    main()
