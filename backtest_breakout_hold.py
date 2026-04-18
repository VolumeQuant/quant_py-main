"""한국 v77에 Breakout Hold 변형 적용 + 검증

미국 v74의 Breakout Hold 인사이트를 한국 환경에 적용:
- 미국 조건: 20일+25%, EPS 90일 동행, 애널 40%, MA60
- 한국 변형: 20일+25%, rev_z > 0, op_margin_z > 0, MA60

방법:
1. TurboSimulator를 fork (hold 로직 추가)
2. 5년 단일 백테스트
3. 다양한 hold 조건 변형 비교
"""
import sys
import os
import json
import time
import numpy as np
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / 'backtest'))

# TurboSimulator 직접 import
from backtest.turbo_simulator import TurboSimulator, _calc_metrics


def load_data():
    """한국 백테스트 데이터 로드"""
    print("[1] 데이터 로드...")

    # OHLCV
    ohlcv_files = sorted(Path('data_cache').glob('all_ohlcv_*.parquet'))
    if not ohlcv_files:
        print("ERROR: OHLCV 파일 없음")
        return None
    ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
    print(f"  OHLCV: {ohlcv.shape}")

    # 벤치마크
    bench_files = list(Path('data_cache').glob('kospi_yf.parquet'))
    bench = pd.read_parquet(bench_files[0]) if bench_files else None
    print(f"  KOSPI: {bench.shape if bench is not None else 'NONE'}")

    # Rankings
    bt = Path('backtest/bt_test_A')
    if not bt.exists():
        print("ERROR: bt_test_A 없음")
        return None
    dates = sorted([f.stem.replace('ranking_', '') for f in bt.glob('ranking_*.json')])
    rk = {}
    for d in dates:
        with open(bt / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
            rk[d] = json.load(f).get('rankings', [])
    print(f"  Rankings: {len(dates)}일 ({dates[0]}~{dates[-1]})")

    return ohlcv, bench, rk, dates


def make_regime(dates, bench):
    """국면 판단 (KOSPI > MA200, 5일 연속)"""
    kospi = bench.iloc[:, 0].dropna()
    km200 = kospi.rolling(200).mean()

    rd = {}
    mode = False
    streak = 0
    ss = False
    for d in dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts, None)
        mv = km200.get(ts, None)
        s = (kv > mv) if kv is not None and mv is not None else mode
        if s == ss:
            streak += 1
        else:
            streak = 1
            ss = s
        if streak >= 5 and mode != s:
            mode = s
        rd[d] = mode
    return rd


def baseline_test(rk, dates, ohlcv, bench, rd):
    """v77 baseline (Breakout Hold 없음)"""
    print("\n[2] Baseline (v77) 백테스트...")

    # v77 파라미터
    op = {'v': 0.05, 'q': 0.0, 'g': 0.65, 'm': 0.30, 'g_rev': 0.5,
          'entry': 7, 'exit': 8, 'slots': 3, 'mom': '12m-1m'}
    dp = {'v': 0.30, 'q': 0.05, 'g': 0.10, 'm': 0.55, 'g_rev': 0.5,
          'entry': 3, 'exit': 6, 'slots': 7, 'mom': '6m-1m'}

    tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
    r = tsim.run_regime(
        dp, op, rd,
        stop_loss=-0.10, trailing_stop=-0.15,
        g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z',
        g_sub1_o='rev_z', g_sub2_o='oca_z'
    )
    print(f"  CAGR={r['cagr']:.1f}%  MDD={r['mdd']:.1f}%  Cal={r['calmar']:.2f}  "
          f"Sh={r['sharpe']:.2f}  So={r['sortino']:.2f}")
    return r


def main():
    t0 = time.time()
    data = load_data()
    if data is None:
        return
    ohlcv, bench, rk, dates = data
    rd = make_regime(dates, bench)

    print(f"\n로드 완료: {time.time()-t0:.1f}s")

    # Step 1: Baseline 확인
    r_base = baseline_test(rk, dates, ohlcv, bench, rd)
    print(f"\n예상값 대비: CAGR=186%, Cal=6.62 (v77 spec)")

    print(f"\n총 소요: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
