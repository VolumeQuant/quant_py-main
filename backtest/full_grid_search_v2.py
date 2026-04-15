"""v72 전략 파라미터 그리드 서치 v2

Growth 정상 데이터 기반 재검증.
기존 ranking z-score 재조합 → bt 재생성 불필요.

단계:
  1단계: 팩터 가중치(V/Q/G/M) + g_rev → Sharpe 기준
  2단계: 진입/퇴출/슬롯 → 1단계 최적값 고정
  3단계: 결과 비교 (전체/최근/국면별)

Usage:
    python backtest/full_grid_search_v2.py
    python backtest/full_grid_search_v2.py --phase 1
    python backtest/full_grid_search_v2.py --phase 2 --v 15 --q 25 --g 40 --m 20 --g_rev 0.7
"""
import sys
import json
import time
import itertools
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

from backtest.production_simulator import ProductionSimulator

CACHE_DIR = PROJECT_ROOT / 'data_cache'
STATE_DIR = PROJECT_ROOT / 'state'


def load_rankings_and_prices(bt_dirs):
    """여러 bt 디렉토리에서 ranking + OHLCV 로드"""
    all_rankings = {}
    for bd in bt_dirs:
        for f in sorted(bd.glob('ranking_*.json')):
            date = f.stem.replace('ranking_', '')
            r = json.load(open(f, encoding='utf-8'))
            all_rankings[date] = r.get('rankings', [])

    dates = sorted(all_rankings.keys())
    print(f'  ranking: {len(dates)}일 ({dates[0]}~{dates[-1]})')

    # OHLCV (가장 긴 파일)
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])
    prices = pd.read_parquet(ohlcv_files[0])
    print(f'  OHLCV: {prices.shape[0]}일 × {prices.shape[1]}종목')

    return all_rankings, dates, prices


def split_by_regime(dates, prices):
    """코스피 수익률 기반 국면 분류

    bull: 6개월 수익률 > 10%
    bear: 6개월 수익률 < -10%
    sideways: 그 사이
    """
    # 코스피 대용: 전종목 평균 수익률 (벤치마크 없을 때)
    # 또는 첫 번째 OHLCV 컬럼 그룹의 평균
    avg_price = prices.mean(axis=1).dropna()

    regimes = {'bull': [], 'bear': [], 'sideways': []}
    lookback = 126  # ~6개월

    for d in dates:
        ts = pd.Timestamp(d)
        if ts not in avg_price.index:
            continue
        idx = avg_price.index.get_loc(ts)
        if idx < lookback:
            regimes['sideways'].append(d)
            continue

        ret_6m = avg_price.iloc[idx] / avg_price.iloc[idx - lookback] - 1
        if ret_6m > 0.10:
            regimes['bull'].append(d)
        elif ret_6m < -0.10:
            regimes['bear'].append(d)
        else:
            regimes['sideways'].append(d)

    for k, v in regimes.items():
        print(f'  {k}: {len(v)}일')
    return regimes


def generate_weight_combos(step=5):
    """V+Q+G+M=100 조합 생성 (합=100 제약)"""
    combos = []
    for v in range(5, 35, step):
        for q in range(5, 35, step):
            for g in range(10, 55, step):
                m = 100 - v - q - g
                if 5 <= m <= 35:
                    combos.append((v / 100, q / 100, g / 100, m / 100))
    return combos


def phase1_weights_grev(sim, weight_combos, g_revs, label=''):
    """1단계: 팩터 가중치 + g_rev 그리드 서치"""
    results = []
    total = len(weight_combos) * len(g_revs)
    t0 = time.time()

    for i, ((v, q, g, m), gr) in enumerate(itertools.product(weight_combos, g_revs)):
        r = sim.run(
            v_w=v, q_w=q, g_w=g, m_w=m, g_rev=gr,
            strategy='rank', entry_param=5, exit_param=10,
            max_slots=5, top_n=20, stop_loss=-0.10,
        )
        r['v_w'] = v
        r['q_w'] = q
        r['g_w'] = g
        r['m_w'] = m
        r['g_rev'] = gr
        results.append(r)

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            remaining = elapsed / (i + 1) * (total - i - 1) / 60
            print(f'  [{i+1}/{total}] ~{remaining:.0f}분 남음')

    df = pd.DataFrame(results)
    df = df.sort_values('sharpe', ascending=False)

    elapsed = time.time() - t0
    print(f'\n=== Phase 1 결과 {label} ({elapsed:.0f}초, {total}조합) ===')
    print(f'Top 10:')
    cols = ['v_w', 'q_w', 'g_w', 'm_w', 'g_rev', 'sharpe', 'cagr', 'mdd', 'calmar', 'alpha', 'avg_holdings']
    print(df.head(10)[cols].to_string(index=False))

    return df


def phase2_entry_exit(sim, best_weights, label=''):
    """2단계: 진입/퇴출/슬롯 그리드 서치 (1단계 최적 가중치 고정)"""
    v, q, g, m, gr = best_weights

    entry_ranks = [3, 5, 7, 10]
    exit_ranks = [5, 7, 10, 12, 15]
    slots_list = [3, 5, 7, 10]
    top_ns = [10, 15, 20, 30]
    stop_losses = [-0.10, -0.15, None]

    results = []
    total = len(entry_ranks) * len(exit_ranks) * len(slots_list) * len(top_ns) * len(stop_losses)
    t0 = time.time()

    for i, (er, xr, sl, tn, stp) in enumerate(
        itertools.product(entry_ranks, exit_ranks, slots_list, top_ns, stop_losses)
    ):
        if er >= xr:  # 진입 rank가 퇴출보다 느슨하면 스킵
            continue

        r = sim.run(
            v_w=v, q_w=q, g_w=g, m_w=m, g_rev=gr,
            strategy='rank', entry_param=er, exit_param=xr,
            max_slots=sl, top_n=tn, stop_loss=stp,
        )
        r['entry_rank'] = er
        r['exit_rank'] = xr
        r['slots'] = sl
        r['top_n'] = tn
        r['stop_loss'] = stp
        results.append(r)

    df = pd.DataFrame(results)
    df = df.sort_values('sharpe', ascending=False)

    elapsed = time.time() - t0
    print(f'\n=== Phase 2 결과 {label} ({elapsed:.0f}초, {len(results)}조합) ===')
    cols = ['entry_rank', 'exit_rank', 'slots', 'top_n', 'stop_loss', 'sharpe', 'cagr', 'mdd', 'calmar', 'alpha', 'avg_holdings']
    print(f'Top 10:')
    print(df.head(10)[cols].to_string(index=False))

    return df


def run_period(all_rankings, prices, dates_subset, label):
    """특정 기간에 대해 Phase 1 + Phase 2 실행"""
    # dates_subset에 해당하는 ranking만 필터
    sub_rankings = {d: all_rankings[d] for d in dates_subset if d in all_rankings}
    sub_dates = sorted(sub_rankings.keys())

    if len(sub_dates) < 60:
        print(f'\n{label}: {len(sub_dates)}일 → 너무 짧아 스킵')
        return None, None

    print(f'\n{"="*60}')
    print(f'{label}: {len(sub_dates)}일 ({sub_dates[0]}~{sub_dates[-1]})')
    print(f'{"="*60}')

    sim = ProductionSimulator(sub_rankings, sub_dates, prices)

    # Phase 1
    weight_combos = generate_weight_combos(step=5)
    g_revs = [0.3, 0.5, 0.7, 0.8, 1.0]
    print(f'\nPhase 1: {len(weight_combos)} × {len(g_revs)} = {len(weight_combos)*len(g_revs)}조합')

    p1 = phase1_weights_grev(sim, weight_combos, g_revs, label)

    # Phase 2: Phase 1 Top 1 가중치 사용
    best = p1.iloc[0]
    best_weights = (best['v_w'], best['q_w'], best['g_w'], best['m_w'], best['g_rev'])
    print(f'\nPhase 2 (고정: V{best["v_w"]:.0%} Q{best["q_w"]:.0%} G{best["g_w"]:.0%} M{best["m_w"]:.0%} g_rev={best["g_rev"]})')

    p2 = phase2_entry_exit(sim, best_weights, label)

    return p1, p2


def main():
    args = sys.argv[1:]
    t0 = time.time()

    print('=== 데이터 로드 ===')
    # 지배주주 보정 완료된 bt만 사용 (2023~2025)
    bt_dirs = [STATE_DIR / f'bt_{yr}' for yr in ['2023', '2024', '2025']]
    bt_dirs = [d for d in bt_dirs if d.exists()]
    all_rankings, dates, prices = load_rankings_and_prices(bt_dirs)

    # 기간별 날짜 분류
    dates_2021_26 = [d for d in dates if '20210104' <= d <= '20260320']
    dates_2024_26 = [d for d in dates if '20240102' <= d <= '20260320']

    # 국면별 분류
    print('\n=== 국면 분류 ===')
    regimes = split_by_regime(dates_2021_26, prices)

    # 실행
    results = {}

    # 전체기간 (2021~2026)
    p1_full, p2_full = run_period(all_rankings, prices, dates_2021_26, '전체 2021~2026')
    results['full'] = (p1_full, p2_full)

    # 최근 (2024~2026)
    p1_recent, p2_recent = run_period(all_rankings, prices, dates_2024_26, '최근 2024~2026')
    results['recent'] = (p1_recent, p2_recent)

    # 국면별
    for regime_name, regime_dates in regimes.items():
        p1_r, p2_r = run_period(all_rankings, prices, regime_dates, f'국면: {regime_name}')
        results[regime_name] = (p1_r, p2_r)

    # 비교 요약
    print(f'\n{"="*60}')
    print('=== 최적 가중치 비교 ===')
    print(f'{"="*60}')
    print(f'{"구간":<20} {"V":>4} {"Q":>4} {"G":>4} {"M":>4} {"g_rev":>5} {"Sharpe":>7} {"CAGR":>7} {"MDD":>7}')
    print('-' * 70)
    for name, (p1, _) in results.items():
        if p1 is not None and not p1.empty:
            b = p1.iloc[0]
            print(f'{name:<20} {b["v_w"]:>4.0%} {b["q_w"]:>4.0%} {b["g_w"]:>4.0%} {b["m_w"]:>4.0%} {b["g_rev"]:>5.1f} {b["sharpe"]:>7.3f} {b["cagr"]:>6.1f}% {b["mdd"]:>6.1f}%')

    # 현재값(v72) 성과
    print(f'\n현재 v72 (V15 Q25 G40 M20 g_rev=0.7):')
    for name, (p1, _) in results.items():
        if p1 is not None and not p1.empty:
            cur = p1[(p1['v_w']==0.15) & (p1['q_w']==0.25) & (p1['g_w']==0.40) & (p1['m_w']==0.20) & (p1['g_rev']==0.7)]
            if not cur.empty:
                c = cur.iloc[0]
                print(f'  {name:<20} Sharpe={c["sharpe"]:.3f} CAGR={c["cagr"]:.1f}% MDD={c["mdd"]:.1f}%')

    elapsed = time.time() - t0
    print(f'\n총 소요: {elapsed/60:.1f}분')

    # 결과 저장
    out_path = PROJECT_ROOT / 'backtest' / 'grid_search_v2_results.json'
    save_data = {}
    for name, (p1, p2) in results.items():
        save_data[name] = {
            'phase1_top10': p1.head(10).to_dict('records') if p1 is not None else [],
            'phase2_top10': p2.head(10).to_dict('records') if p2 is not None else [],
        }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    print(f'결과 저장: {out_path}')


if __name__ == '__main__':
    main()
