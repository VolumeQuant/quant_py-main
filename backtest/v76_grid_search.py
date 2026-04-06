"""v76 전체 최적화 파이프라인
Phase 2a: 공격/방어 단일 전략 가중치 탐색
Phase 2b: Top15 × 규칙(E/X/S) 탐색
국면서치: 공격Top5 × 방어Top5 × 20규칙
안정성 + Walk-Forward
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator

MODE = sys.argv[1] if len(sys.argv) > 1 else 'all'  # 'attack', 'defense', 'all'

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'

# 데이터 로드
print('데이터 로드...', flush=True)
t0 = time.time()
ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*full*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    rk[d] = json.load(open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8')).get('rankings', [])
print(f'  {len(dates)}일 로드 ({time.time()-t0:.1f}초)', flush=True)

# TurboSim 초기화
print('TurboSim 초기화...', flush=True)
t1 = time.time()
tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
print(f'  완료 ({time.time()-t1:.1f}초)', flush=True)


def run_single(v, q, g, m, g_rev, mom, entry, exit_r, slots, sl, trail, sub1, sub2):
    """단일 전략 run (전체 기간 동일 모드)"""
    rd_all = {d: True for d in dates}
    params = {'v': v/100, 'q': q/100, 'g': g/100, 'm': m/100,
              'g_rev': g_rev, 'entry': entry, 'exit': exit_r, 'slots': slots, 'mom': mom}
    return tsim.run_regime(
        params, params, rd_all,
        stop_loss=sl, trailing_stop=trail,
        g_sub1_d=sub1, g_sub2_d=sub2, g_sub1_o=sub1, g_sub2_o=sub2
    )


if MODE in ('attack', 'all'):
    print(f'\n{"="*50}', flush=True)
    print('Phase 2a: 공격 모드 가중치 탐색', flush=True)
    print(f'{"="*50}', flush=True)

    atk_results = []
    count = 0
    for v in range(0, 35, 5):
        for q in range(0, 20, 5):
            for g in range(40, 80, 5):
                m = 100 - v - q - g
                if m < 10 or m > 40:
                    continue
                for gr in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
                    for mom in ['12m', '12m-1m']:
                        r = run_single(v, q, g, m, gr, mom, 5, 8, 3, -0.10, -0.15, 'oca_z', 'op_margin_z')
                        atk_results.append({
                            'v': v, 'q': q, 'g': g, 'm': m, 'gr': gr, 'mom': mom,
                            'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                            'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                        })
                        count += 1
                if count % 100 == 0:
                    print(f'  공격 {count}개 완료...', flush=True)

    adf = pd.DataFrame(atk_results).sort_values('cal', ascending=False)
    adf.to_csv(RESULT_DIR / 'v76_phase2a_attack.csv', index=False)
    print(f'\n공격 {len(atk_results)}개 완료 ({time.time()-t0:.0f}초)', flush=True)
    print(adf.head(15).to_string(index=False), flush=True)


if MODE in ('defense', 'all'):
    print(f'\n{"="*50}', flush=True)
    print('Phase 2a: 방어 모드 가중치 탐색', flush=True)
    print(f'{"="*50}', flush=True)

    def_results = []
    count = 0
    for v in range(10, 35, 5):
        for q in range(0, 25, 5):
            for g in range(10, 45, 5):
                m = 100 - v - q - g
                if m < 30 or m > 60:
                    continue
                for gr in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
                    for mom in ['6m', '6m-1m']:
                        r = run_single(v, q, g, m, gr, mom, 5, 8, 7, -0.10, -0.15, 'rev_z', 'op_margin_z')
                        def_results.append({
                            'v': v, 'q': q, 'g': g, 'm': m, 'gr': gr, 'mom': mom,
                            'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                            'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                        })
                        count += 1
                if count % 100 == 0:
                    print(f'  방어 {count}개 완료...', flush=True)

    ddf = pd.DataFrame(def_results).sort_values('cal', ascending=False)
    ddf.to_csv(RESULT_DIR / 'v76_phase2a_defense.csv', index=False)
    print(f'\n방어 {len(def_results)}개 완료 ({time.time()-t0:.0f}초)', flush=True)
    print(ddf.head(15).to_string(index=False), flush=True)

print(f'\n총 소요: {time.time()-t0:.0f}초', flush=True)
