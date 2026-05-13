"""현재 state + bt_extended 단독 BT (2018-07~2026-03/30, 215 재수집 + 옵션F 폐기 후).

v80.2 (v80 rollback 후, SL=-10% TS=-15% TS_cd=2)
"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, _calc_metrics
from compare_optf_bt import load_rankings, calc_regime, run_v80

PROJECT = Path(__file__).parent.parent

def main():
    print('=== 현재 state 단독 BT (215 재수집 + 옵션F 폐기 후) ===')
    ohlcv_files = sorted((PROJECT/'data_cache').glob('all_ohlcv_*.parquet'))
    ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
    print(f'  OHLCV: {ohlcv_files[-1].name} ({len(ohlcv.columns)}종목, {len(ohlcv)}일)')
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()

    # 7.8년 (OHLCV 2019-06 시작이라 2019-12부터 가능)
    boost_full = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
    defense_full = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
    dates_full = sorted(set(boost_full) & set(defense_full))
    dates_full = [d for d in dates_full if '20180702' <= d <= '20260330']
    print(f'  거래일 (확장): {len(dates_full)} ({dates_full[0]} ~ {dates_full[-1]})')

    r = run_v80(boost_full, defense_full, dates_full, ohlcv, kospi, ma170,
                sl=-0.10, ts=-0.15, ts_cd=2)
    print(f'\n--- 확장 BT (~6.3년) ---')
    print(f'  Cal = {r["calmar"]:.3f}')
    print(f'  CAGR = {r["cagr"]:.1f}%')
    print(f'  MDD = {r["mdd"]:.1f}%')
    print(f'  Sharpe = {r["sharpe"]:.3f}')
    print(f'  Sortino = {r["sortino"]:.3f}')
    print(f'  Avg holdings = {r["avg_holdings"]:.1f}')
    print(f'  Total = {r["total"]:.1f}%')

    # 매뉴얼 baseline 7.8y Cal 3.97 비교
    print(f'\n  매뉴얼 baseline (옵션F 이전): 7.8y Cal 3.97')
    print(f'  현재 (옵션F 폐기 + 215 재수집): Cal {r["calmar"]:.3f}')
    delta = r["calmar"] - 3.97
    print(f'  Δ {delta:+.3f}')

    # 5.25년 BT (사용자 메모리 baseline 4.71)
    print(f'\n--- 5.25년 BT (state 단독, 2021-01~2026-03/30) ---')
    boost_525 = {k: v for k, v in boost_full.items() if '20210104' <= k <= '20260330'}
    defense_525 = {k: v for k, v in defense_full.items() if '20210104' <= k <= '20260330'}
    dates_525 = sorted(set(boost_525) & set(defense_525))
    print(f'  거래일: {len(dates_525)}')
    r525 = run_v80(boost_525, defense_525, dates_525, ohlcv, kospi, ma170,
                   sl=-0.10, ts=-0.15, ts_cd=2)
    print(f'  Cal = {r525["calmar"]:.3f}')
    print(f'  CAGR = {r525["cagr"]:.1f}%')
    print(f'  MDD = {r525["mdd"]:.1f}%')
    print(f'  매뉴얼 baseline 5.25y Cal 4.71 (옵션F 이전)')
    print(f'  Δ {r525["calmar"]-4.71:+.3f}')

    # 판정
    print(f'\n=== 종합 판정 ===')
    if r525["calmar"] >= 4.0:
        print(f'  ✅ Pass (5.25y Cal {r525["calmar"]:.3f} ≥ 4.0)')
    elif r525["calmar"] >= 3.0:
        print(f'  ⚠️ 재검토 (3.0 ≤ 5.25y Cal {r525["calmar"]:.3f} < 4.0) — 정상 가짜알파제거 효과 가능')
    else:
        print(f'  ❌ Roll back (5.25y Cal {r525["calmar"]:.3f} < 3.0) — ROLLBACK_PLAN §2')

if __name__ == '__main__':
    main()
