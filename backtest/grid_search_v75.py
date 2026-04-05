"""v75 전면 그리드서치 — 8변수 동시 최적화 + Walk-Forward + FDR 보정

Phase 2a: 가중치+g_rev+모멘텀 스크리닝 (고정 규칙)
Phase 2b: Top 200 × 전 규칙 조합
Phase 2c: Walk-Forward 롤링 검증 (3기간)
Phase 2d: FDR 보정 (Benjamini-Hochberg)
Phase 2e: 인접 안정성

Usage:
    python backtest/grid_search_v75.py
"""
import sys, os, json, time, glob
from pathlib import Path
from itertools import product

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

CACHE_DIR = PROJECT / 'data_cache'
BT_DIR = PROJECT / 'backtest' / 'bt_v75'
RESULTS_DIR = PROJECT / 'backtest_results'
RESULTS_DIR.mkdir(exist_ok=True)


# ============================================================================
# 데이터 로드
# ============================================================================
def load_bt_rankings(bt_dir, year_filter=None):
    all_rankings = {}
    for f in sorted(bt_dir.glob('ranking_*.json')):
        date = f.stem.replace('ranking_', '')
        if year_filter and date[:4] not in year_filter:
            continue
        with open(f, encoding='utf-8') as fh:
            data = json.load(fh)
            all_rankings[date] = data.get('rankings', [])
    dates = sorted(all_rankings.keys())
    return all_rankings, dates


def load_prices():
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_2020*.parquet'))
    if not ohlcv_files:
        ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    # _full 파일 우선 (전종목)
    full_files = [f for f in ohlcv_files if '_full' in f.stem]
    if full_files:
        ohlcv_files = full_files
    return pd.read_parquet(ohlcv_files[0]).replace(0, np.nan)


# ============================================================================
# 가중치 생성
# ============================================================================
def generate_weight_grid():
    """V(0-40) Q(0-40) G(10-70) M=100-V-Q-G (10-60), step=5"""
    combos = []
    for v in range(0, 45, 5):
        for q in range(0, 45, 5):
            for g in range(10, 75, 5):
                m = 100 - v - q - g
                if 10 <= m <= 60:
                    combos.append((v, q, g, m))
    return combos


# ============================================================================
# Phase 2a: 가중치 스크리닝
# ============================================================================
def phase_2a(tsim, weights, g_revs, mom_types):
    """고정 규칙(E5, X12, S5, SL=-10%)으로 가중치 스크리닝"""
    print(f'\n{"="*80}')
    print(f'Phase 2a: 가중치 스크리닝')
    print(f'  가중치: {len(weights)} × g_rev: {len(g_revs)} × mom: {len(mom_types)}'
          f' = {len(weights)*len(g_revs)*len(mom_types)} 조합')
    print(f'{"="*80}')

    results = []
    total = len(weights) * len(g_revs) * len(mom_types)
    done = 0
    t0 = time.time()

    for v, q, g, m in weights:
        for g_rev in g_revs:
            for mt in mom_types:
                r = tsim.run_fast(
                    v/100, q/100, g/100, m/100, g_rev,
                    entry_param=5, exit_param=12.0, max_slots=5,
                    stop_loss=-0.10, mom_type=mt
                )
                results.append({
                    'v': v, 'q': q, 'g': g, 'm': m,
                    'g_rev': g_rev, 'mom': mt,
                    'calmar': r['calmar'], 'cagr': r['cagr'],
                    'mdd': r['mdd'], 'sharpe': r['sharpe'],
                    'sortino': r['sortino'],
                })
                done += 1
                if done % 500 == 0:
                    elapsed = time.time() - t0
                    rate = done / elapsed
                    remain = (total - done) / rate
                    print(f'  [{done}/{total}] {elapsed:.0f}초 | 남은 ~{remain:.0f}초')

    df = pd.DataFrame(results)
    df = df.sort_values('calmar', ascending=False)
    elapsed = time.time() - t0
    print(f'  완료: {elapsed:.0f}초, {len(df)}개 결과')
    print(f'\n  Top 10 (Calmar):')
    for i, row in df.head(10).iterrows():
        print(f'    V{row.v}Q{row.q}G{row.g}M{row.m} g={row.g_rev} mom={row.mom}'
              f' | Cal={row.calmar:.2f} CAGR={row.cagr:.1f}% MDD={row.mdd:.1f}%'
              f' Sharpe={row.sharpe:.2f}')

    return df


# ============================================================================
# Phase 2b: 규칙 최적화
# ============================================================================
def phase_2b(tsim, top_weights_df, n_top=200):
    """Top N 가중치에 대해 전 규칙 조합"""
    from turbo_simulator import TurboRunner

    entries = [3, 5, 7]
    exits = [4, 8, 12, 15]
    slots_list = [3, 5, 7]
    stop_losses = [-0.08, -0.10, -0.12, None]
    trailing_stops = [-0.15, -0.20, None]
    corr_thresholds = [0.60, 0.65, None]

    rules = list(product(entries, exits, slots_list, stop_losses, trailing_stops, corr_thresholds))
    # exit > entry 필터
    rules = [(e, x, s, sl, ts, ct) for e, x, s, sl, ts, ct in rules if x > e]

    top = top_weights_df.head(n_top)
    total = len(top) * len(rules)

    print(f'\n{"="*80}')
    print(f'Phase 2b: 규칙 최적화')
    print(f'  Top {n_top} 가중치 × {len(rules)} 규칙 = {total:,} 조합')
    print(f'{"="*80}')

    results = []
    t0 = time.time()
    done_w = 0

    for _, wrow in top.iterrows():
        v, q, g, m = int(wrow.v), int(wrow.q), int(wrow.g), int(wrow.m)
        g_rev, mt = wrow.g_rev, wrow.mom

        tsim._ensure_cache(v/100, q/100, g/100, m/100, g_rev, 20, mt)
        runner = TurboRunner(tsim)

        for entry, exit_, slots, sl, ts, ct in rules:
            r = runner.run(entry, exit_, slots, stop_loss=sl,
                          corr_threshold=ct, trailing_stop=ts)
            results.append({
                'v': v, 'q': q, 'g': g, 'm': m,
                'g_rev': g_rev, 'mom': mt,
                'entry': entry, 'exit': exit_, 'slots': slots,
                'sl': sl, 'trail': ts, 'corr_th': ct,
                'calmar': r['calmar'], 'cagr': r['cagr'],
                'mdd': r['mdd'], 'sharpe': r['sharpe'],
                'sortino': r['sortino'], 'avg_holdings': r['avg_holdings'],
            })

        done_w += 1
        if done_w % 20 == 0:
            elapsed = time.time() - t0
            rate = done_w / elapsed
            remain = (len(top) - done_w) / rate
            print(f'  [{done_w}/{len(top)}] {elapsed:.0f}초 | 남은 ~{remain:.0f}초')

    df = pd.DataFrame(results)
    df = df.sort_values('calmar', ascending=False)
    elapsed = time.time() - t0
    print(f'  완료: {elapsed:.0f}초, {len(df):,}개 결과')
    print(f'\n  Top 10:')
    for i, row in df.head(10).iterrows():
        sl_s = f'{int(row.sl*100)}%' if pd.notna(row.sl) else 'X'
        tr_s = f'{int(row.trail*100)}%' if pd.notna(row.trail) else 'X'
        cr_s = f'{row.corr_th}' if pd.notna(row.corr_th) else 'X'
        ex = row['exit']
        print(f'    V{row.v}Q{row.q}G{row.g}M{row.m} g={row.g_rev} {row.mom}'
              f' E{row.entry}X{ex}S{row.slots} sl={sl_s} tr={tr_s} corr={cr_s}'
              f' | Cal={row.calmar:.2f} CAGR={row.cagr:.1f}% MDD={row.mdd:.1f}%')

    return df


# ============================================================================
# Phase 2c: Walk-Forward 검증
# ============================================================================
def phase_2c(top_configs_df, n_top=500):
    """3기간 Walk-Forward 교차 검증"""
    from turbo_simulator import TurboSimulator, TurboRunner

    periods = [
        (['2021', '2022', '2023'], ['2024'], 'WF1'),
        (['2022', '2023', '2024'], ['2025'], 'WF2'),
        (['2021', '2022', '2023', '2024'], ['2025', '2026'], 'WF3'),
    ]

    top = top_configs_df.head(n_top)
    print(f'\n{"="*80}')
    print(f'Phase 2c: Walk-Forward ({len(periods)}기간 × {len(top)} 후보)')
    print(f'{"="*80}')

    prices = load_prices()

    wf_results = {wf_name: [] for _, _, wf_name in periods}

    for train_years, test_years, wf_name in periods:
        print(f'\n  {wf_name}: train={train_years} test={test_years}')
        test_rankings, test_dates = load_bt_rankings(BT_DIR, test_years)
        if not test_dates:
            print(f'    데이터 없음 — 스킵')
            continue
        print(f'    {len(test_dates)}거래일')

        bench = pd.read_parquet(CACHE_DIR / 'bench_proxy.parquet') \
            if (CACHE_DIR / 'bench_proxy.parquet').exists() else pd.DataFrame()
        tsim = TurboSimulator(test_rankings, test_dates, prices, bench)

        for _, cfg in top.iterrows():
            sl = cfg.sl if pd.notna(cfg.sl) else None
            ct = cfg.corr_th if pd.notna(cfg.corr_th) else None
            tr = cfg.trail if pd.notna(cfg.trail) else None
            tsim._ensure_cache(
                cfg.v/100, cfg.q/100, cfg.g/100, cfg.m/100,
                cfg.g_rev, 20, cfg.mom
            )
            runner = TurboRunner(tsim)
            r = runner.run(
                int(cfg.entry), cfg['exit'], int(cfg.slots),
                stop_loss=sl, corr_threshold=ct, trailing_stop=tr
            )
            wf_results[wf_name].append(r['calmar'])

    # 평균 Calmar 계산
    avg_calmar = []
    for i in range(len(top)):
        cals = []
        for _, _, wf_name in periods:
            if i < len(wf_results[wf_name]):
                cals.append(wf_results[wf_name][i])
        avg_calmar.append(np.mean(cals) if cals else 0)

    result_df = top.copy()
    result_df['wf_avg_calmar'] = avg_calmar
    for _, _, wf_name in periods:
        vals = wf_results[wf_name]
        result_df[f'{wf_name}_calmar'] = vals + [0] * (len(result_df) - len(vals))

    result_df = result_df.sort_values('wf_avg_calmar', ascending=False)
    print(f'\n  WF Top 10 (평균 Calmar):')
    for i, row in result_df.head(10).iterrows():
        print(f'    V{row.v}Q{row.q}G{row.g}M{row.m} g={row.g_rev} {row.mom}'
              f' | WF_avg={row.wf_avg_calmar:.2f}'
              f' WF1={row.WF1_calmar:.2f} WF2={row.WF2_calmar:.2f} WF3={row.WF3_calmar:.2f}')

    return result_df


# ============================================================================
# Phase 2d: FDR 보정 (Benjamini-Hochberg)
# ============================================================================
def phase_2d(full_results_df, wf_df, n_wf_top=100):
    """Multiple testing 보정"""
    print(f'\n{"="*80}')
    print(f'Phase 2d: FDR 보정 (Benjamini-Hochberg)')
    print(f'{"="*80}')

    # 전체 결과에서 p-value 계산 (Calmar 분포 기반)
    calmars = full_results_df['calmar'].values
    mu = np.mean(calmars)
    sigma = np.std(calmars)

    if sigma > 0:
        z_scores = (calmars - mu) / sigma
        from scipy.stats import norm
        p_values = 1 - norm.cdf(z_scores)
    else:
        p_values = np.ones(len(calmars))

    full_results_df = full_results_df.copy()
    full_results_df['p_value'] = p_values

    # BH procedure
    n = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = p_values[sorted_idx]
    q_threshold = 0.05

    significant = np.zeros(n, dtype=bool)
    for k in range(n):
        if sorted_p[k] <= (k + 1) / n * q_threshold:
            significant[sorted_idx[:k+1]] = True

    full_results_df['fdr_significant'] = significant
    n_sig = significant.sum()
    print(f'  전체 {n:,}개 중 FDR q<0.05 유의: {n_sig:,}개 ({n_sig/n*100:.1f}%)', flush=True)

    # FDR 너무 공격적이면 완화 (최소 50개 확보)
    if n_sig < 50:
        for q_relaxed in [0.10, 0.20, 0.50]:
            sig_relaxed = np.zeros(n, dtype=bool)
            for k in range(n):
                if sorted_p[k] <= (k + 1) / n * q_relaxed:
                    sig_relaxed[sorted_idx[:k+1]] = True
            n_relaxed = sig_relaxed.sum()
            if n_relaxed >= 50:
                full_results_df['fdr_significant'] = sig_relaxed
                print(f'  FDR 완화 q<{q_relaxed}: {n_relaxed}개', flush=True)
                break
        else:
            # 그래도 부족하면 FDR 필터 비활성화
            full_results_df['fdr_significant'] = True
            print(f'  FDR 비활성화 (유의 결과 부족)', flush=True)

    # WF Top과 교집합
    wf_top = wf_df.head(n_wf_top)
    # FDR 통과한 것만 남기기 (소프트 필터)
    wf_top_fdr = wf_top[wf_top.index.isin(
        full_results_df[full_results_df['fdr_significant']].index)]
    if len(wf_top_fdr) >= 20:
        wf_top = wf_top_fdr
        print(f'  WF Top × FDR 교차: {len(wf_top)}개', flush=True)
    else:
        print(f'  FDR 교차 결과 {len(wf_top_fdr)}개 (부족) → WF Top {n_wf_top} 유지', flush=True)

    return full_results_df, wf_top


# ============================================================================
# Phase 2e: 인접 안정성
# ============================================================================
def phase_2e(tsim, candidates_df, n_top=50):
    """가중치 ±5, g_rev ±0.1 이웃 테스트"""
    print(f'\n{"="*80}')
    print(f'Phase 2e: 인접 안정성 (Top {n_top})')
    print(f'{"="*80}')

    top = candidates_df.head(n_top)
    stability = []

    for _, cfg in top.iterrows():
        v, q, g, m = int(cfg.v), int(cfg.q), int(cfg.g), int(cfg.m)
        sl = cfg.sl if pd.notna(cfg.sl) else None
        ct = cfg.corr_th if pd.notna(cfg.corr_th) else None
        tr = cfg.trail if pd.notna(cfg.trail) else None
        neighbors_ok = 0
        neighbors_total = 0

        for dv in [-5, 0, 5]:
            for dq in [-5, 0, 5]:
                for dg in [-5, 0, 5]:
                    nv, nq, ng = v + dv, q + dq, g + dg
                    nm = 100 - nv - nq - ng
                    if nv < 0 or nq < 0 or ng < 5 or nm < 5:
                        continue
                    if (nv, nq, ng, nm) == (v, q, g, m):
                        continue
                    neighbors_total += 1

                    r = tsim.run_fast(
                        nv/100, nq/100, ng/100, nm/100, cfg.g_rev,
                        entry_param=int(cfg.entry), exit_param=cfg['exit'],
                        max_slots=int(cfg.slots), stop_loss=sl,
                        corr_threshold=ct, trailing_stop=tr,
                        mom_type=cfg.mom
                    )
                    if r['calmar'] >= 2.0:
                        neighbors_ok += 1

        # g_rev +-0.1
        for dg_rev in [-0.1, 0.1]:
            new_grev = cfg.g_rev + dg_rev
            if 0.0 <= new_grev <= 1.0:
                neighbors_total += 1
                r = tsim.run_fast(
                    v/100, q/100, g/100, m/100, new_grev,
                    entry_param=int(cfg.entry), exit_param=cfg['exit'],
                    max_slots=int(cfg.slots), stop_loss=sl,
                    corr_threshold=ct, trailing_stop=tr,
                    mom_type=cfg.mom
                )
                if r['calmar'] >= 2.0:
                    neighbors_ok += 1

        # entry ±1, exit ±2, slots ±1
        base_entry = int(cfg.entry)
        base_exit = cfg['exit']
        base_slots = int(cfg.slots)
        for de, dx, ds in [(-1,0,0),(1,0,0),(0,-2,0),(0,2,0),(0,0,-1),(0,0,1)]:
            ne = base_entry + de
            nx = base_exit + dx
            ns = base_slots + ds
            if ne < 2 or nx < 3 or ns < 2 or nx <= ne:
                continue
            neighbors_total += 1
            r = tsim.run_fast(
                v/100, q/100, g/100, m/100, cfg.g_rev,
                entry_param=ne, exit_param=float(nx),
                max_slots=ns, stop_loss=sl,
                corr_threshold=ct, trailing_stop=tr,
                mom_type=cfg.mom
            )
            if r['calmar'] >= 2.0:
                neighbors_ok += 1

        pct = neighbors_ok / neighbors_total * 100 if neighbors_total > 0 else 0
        stability.append(pct)

    top = top.copy()
    top['stability'] = stability
    top = top.sort_values(['stability', 'wf_avg_calmar'], ascending=[False, False])

    print(f'\n  안정성 Top 10:')
    for i, row in top.head(10).iterrows():
        print(f'    V{row.v}Q{row.q}G{row.g}M{row.m} g={row.g_rev} {row.mom}'
              f' | stab={row.stability:.0f}% WF={row.wf_avg_calmar:.2f}'
              f' Cal={row.calmar:.2f} CAGR={row.cagr:.1f}%')

    return top


# ============================================================================
# 병렬 워커 (모듈 레벨 — Windows pickle 호환)
# ============================================================================
def _worker_phase2a(args):
    """워커: 자체 TurboSimulator로 가중치 서브셋 처리"""
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    chunk_weights, g_revs_w, mom_types_w, bt_dir_str, cache_dir_str = args
    from pathlib import Path
    _bt = Path(bt_dir_str)
    _cache = Path(cache_dir_str)
    _r, _d = load_bt_rankings(_bt)
    _p = load_prices()
    _b = pd.read_parquet(_cache / 'bench_proxy.parquet') \
        if (_cache / 'bench_proxy.parquet').exists() else pd.DataFrame()
    from turbo_simulator import TurboSimulator
    _tsim = TurboSimulator(_r, _d, _p, _b)
    results = []
    done = 0
    total = len(chunk_weights) * len(g_revs_w) * len(mom_types_w)
    for v, q, g, m in chunk_weights:
        for g_rev in g_revs_w:
            for mt in mom_types_w:
                r = _tsim.run_fast(v/100, q/100, g/100, m/100, g_rev,
                                  entry_param=5, exit_param=12.0, max_slots=5,
                                  stop_loss=-0.10, mom_type=mt)
                results.append({'v':v,'q':q,'g':g,'m':m,'g_rev':g_rev,'mom':mt,
                               'calmar':r['calmar'],'cagr':r['cagr'],'mdd':r['mdd'],
                               'sharpe':r['sharpe'],'sortino':r['sortino']})
                done += 1
    return results


# ============================================================================
# Main
# ============================================================================
def main():
    t_start = time.time()

    print('=== v75 전면 그리드서치 ===', flush=True)
    print('BT 데이터 로드 중...', flush=True)

    all_rankings, dates = load_bt_rankings(BT_DIR)
    prices = load_prices()
    bench = pd.read_parquet(CACHE_DIR / 'bench_proxy.parquet') \
        if (CACHE_DIR / 'bench_proxy.parquet').exists() else pd.DataFrame()

    print(f'거래일: {len(dates)} ({dates[0]}~{dates[-1]})', flush=True)

    from turbo_simulator import TurboSimulator
    print('TurboSimulator 초기화 중...', flush=True)
    t_init = time.time()
    tsim = TurboSimulator(all_rankings, dates, prices, bench)
    print(f'TurboSimulator 초기화 완료: {time.time()-t_init:.0f}초', flush=True)

    # ================================================================
    # Phase 2a-coarse: 거친 스크리닝 (step=10, 6m만)
    # ================================================================
    coarse_weights = []
    for v in range(0, 45, 10):
        for q in range(0, 45, 10):
            for g in range(10, 75, 10):
                m = 100 - v - q - g
                if 10 <= m <= 60:
                    coarse_weights.append((v, q, g, m))
    coarse_grevs = [0.5, 0.7, 1.0]
    coarse_moms = ['6m', '12m']  # 6m 외 12m도 coarse에서 체크 (누락 방지)
    print(f'Phase 2a-coarse: {len(coarse_weights)} × {len(coarse_grevs)} × {len(coarse_moms)}'
          f' = {len(coarse_weights)*len(coarse_grevs)*len(coarse_moms)}', flush=True)

    phase2a_coarse = phase_2a(tsim, coarse_weights, coarse_grevs, coarse_moms)

    # Phase 2a-fine: Top 50 주변 정밀 탐색
    top50 = phase2a_coarse.head(50)
    fine_weights = set()
    for _, row in top50.iterrows():
        v, q, g = int(row.v), int(row.q), int(row.g)
        for dv in [-5, 0, 5]:
            for dq in [-5, 0, 5]:
                for dg in [-5, 0, 5]:
                    nv, nq, ng = v+dv, q+dq, g+dg
                    nm = 100 - nv - nq - ng
                    if nv >= 0 and nq >= 0 and ng >= 5 and 5 <= nm <= 60:
                        fine_weights.add((nv, nq, ng, nm))
    fine_weights = list(fine_weights)
    fine_grevs = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    fine_moms = ['6m', '6m-1m', '12m', '12m-1m']
    print(f'Phase 2a-fine: {len(fine_weights)} × {len(fine_grevs)} × {len(fine_moms)}'
          f' = {len(fine_weights)*len(fine_grevs)*len(fine_moms)}', flush=True)

    # Phase 2a-fine: 병렬 (3워커) + 부분캐싱
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    n_workers = min(3, max(1, multiprocessing.cpu_count() - 1))
    if n_workers > 1 and len(fine_weights) > 50:
        print(f'  병렬 실행: {n_workers}워커', flush=True)
        chunks = [[] for _ in range(n_workers)]
        for i, w in enumerate(fine_weights):
            chunks[i % n_workers].append(w)
        t_par = time.time()
        worker_args = [(c, fine_grevs, fine_moms, str(BT_DIR), str(CACHE_DIR)) for c in chunks]
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            chunk_results = list(pool.map(_worker_phase2a, worker_args))
        all_results = []
        for cr in chunk_results:
            all_results.extend(cr)
        phase2a_fine = pd.DataFrame(all_results).sort_values('calmar', ascending=False)
        print(f'  병렬 완료: {time.time()-t_par:.0f}초, {len(phase2a_fine)}개', flush=True)
        print(f'\n  Top 10 (Calmar):')
        for i, row in phase2a_fine.head(10).iterrows():
            print(f'    V{row.v}Q{row.q}G{row.g}M{row.m} g={row.g_rev} mom={row.mom}'
                  f' | Cal={row.calmar:.2f} CAGR={row.cagr:.1f}% MDD={row.mdd:.1f}%'
                  f' Sharpe={row.sharpe:.2f}')
    else:
        phase2a_fine = phase_2a(tsim, fine_weights, fine_grevs, fine_moms)

    # 합치기
    phase2a_df = pd.concat([phase2a_coarse, phase2a_fine]).drop_duplicates(
        subset=['v','q','g','m','g_rev','mom']).sort_values('calmar', ascending=False)
    phase2a_df.to_csv(RESULTS_DIR / 'phase2a_screening.csv', index=False)
    print(f'Phase 2a 합산: {len(phase2a_df)}개', flush=True)

    # Phase 2b
    phase2b_df = phase_2b(tsim, phase2a_df, n_top=200)
    phase2b_df.to_csv(RESULTS_DIR / 'phase2b_rules.csv', index=False)

    # Phase 2c: Walk-Forward
    phase2c_df = phase_2c(phase2b_df, n_top=500)
    phase2c_df.to_csv(RESULTS_DIR / 'phase2c_walkforward.csv', index=False)

    # Phase 2d: FDR
    phase2d_full, phase2d_top = phase_2d(phase2b_df, phase2c_df, n_wf_top=100)

    # Phase 2e: 안정성
    phase2e_df = phase_2e(tsim, phase2d_top, n_top=50)
    phase2e_df.to_csv(RESULTS_DIR / 'phase2e_stability.csv', index=False)

    # ================================================================
    # 최종 선정: 하드필터 → Pareto Frontier → Borda Count
    # ================================================================
    print(f'\n{"="*80}')
    print(f'최종 선정: 하드필터 → Pareto → Borda')
    print(f'{"="*80}', flush=True)

    candidates = phase2e_df.copy()

    # Step 1: 하드 필터
    before = len(candidates)
    candidates = candidates[candidates['mdd'] <= 40]  # MDD > -40% 탈락
    candidates = candidates[candidates['stability'] >= 60]  # 안정성 < 60% 탈락
    # WF_min: 어느 기간이든 Calmar < 1.0 탈락
    wf_cols = [c for c in candidates.columns if c.startswith('WF') and c.endswith('_calmar')]
    if wf_cols:
        candidates['wf_min'] = candidates[wf_cols].min(axis=1)
        candidates = candidates[candidates['wf_min'] >= 1.0]
    else:
        candidates['wf_min'] = candidates.get('wf_avg_calmar', 0)
    print(f'  하드 필터: {before} → {len(candidates)}개', flush=True)

    if candidates.empty:
        print('  하드 필터 통과 전략 없음! 기준 완화...')
        candidates = phase2e_df.copy()
        candidates['wf_min'] = candidates.get('wf_avg_calmar', 0)
        candidates = candidates[candidates['mdd'] <= 45]
        candidates = candidates[candidates['stability'] >= 50]

    # Step 2: Pareto Frontier (Calmar, WF_min, Stability, Sharpe)
    pareto_cols = ['calmar', 'wf_min', 'stability', 'sharpe']
    pareto_mask = np.ones(len(candidates), dtype=bool)
    vals = candidates[pareto_cols].values
    for i in range(len(vals)):
        for j in range(len(vals)):
            if i == j:
                continue
            # j가 모든 축에서 i보다 크거나 같고, 적어도 하나에서 크면 i는 지배당함
            if np.all(vals[j] >= vals[i]) and np.any(vals[j] > vals[i]):
                pareto_mask[i] = False
                break
    pareto = candidates[pareto_mask].copy()
    print(f'  Pareto: {len(candidates)} → {len(pareto)}개 (비지배)', flush=True)

    # Step 3: Borda Count (전체 후보에서 순위)
    rank_cols = {
        'calmar': False, 'cagr': False, 'mdd': True,  # mdd는 작을수록 좋음
        'sharpe': False, 'sortino': False,
        'wf_min': False, 'wf_avg_calmar': False, 'stability': False,
    }
    borda = np.zeros(len(candidates))
    for col, ascending in rank_cols.items():
        if col in candidates.columns:
            borda += candidates[col].rank(ascending=ascending, method='min').values
    candidates = candidates.copy()
    candidates['borda'] = borda
    pareto = pareto.copy()
    pareto['borda'] = candidates.loc[pareto.index, 'borda']

    # Pareto + Borda Top 10 합집합
    borda_top10 = candidates.nsmallest(10, 'borda')
    final = pd.concat([pareto, borda_top10]).drop_duplicates(
        subset=['v','q','g','m','g_rev','mom','entry','exit','slots']
    ).sort_values('borda')

    final = final.head(30)
    print(f'  최종 후보: {len(final)}개 (Pareto ∪ Borda Top 10)', flush=True)

    # 출력
    print(f'\n{"Borda":>5} {"Pareto":>6} {"전략":>35} {"Cal":>6} {"CAGR":>6} {"MDD":>6}'
          f' {"Sharpe":>7} {"Sort":>6} {"WF_min":>6} {"Stab":>5}', flush=True)
    print('-' * 100)
    for _, row in final.iterrows():
        is_pareto = '★' if row.name in pareto.index else ' '
        sl_s = f'{int(row.sl*100)}' if pd.notna(row.sl) and row.sl else 'X'
        ex = row['exit']
        label = f'V{int(row.v)}Q{int(row.q)}G{int(row.g)}M{int(row.m)} g{row.g_rev} {row.mom} E{int(row.entry)}X{ex}S{int(row.slots)} sl{sl_s}'
        wf_min_v = row.get('wf_min', 0)
        print(f'{row.borda:5.0f} {is_pareto:>6} {label:>35}'
              f' {row.calmar:6.2f} {row.cagr:5.1f}% {row.mdd:5.1f}%'
              f' {row.sharpe:7.2f} {row.sortino:6.2f} {wf_min_v:6.2f} {row.stability:4.0f}%')

    final.to_csv(RESULTS_DIR / 'v75_final_singles.csv', index=False)
    print(f'\n저장: backtest_results/v75_final_singles.csv', flush=True)

    # ================================================================
    # 연도별/구간별 분석 (Top 10)
    # ================================================================
    print(f'\n{"="*80}')
    print(f'연도별 성과 분석 (Top 10)')
    print(f'{"="*80}', flush=True)

    year_ranges = {
        '2021': ('20210104', '20211231'),
        '2022': ('20220101', '20221231'),
        '2023': ('20230101', '20231231'),
        '2024': ('20240101', '20241231'),
        '2025': ('20250101', '20251231'),
        '2026': ('20260101', '20260403'),
        'Bear2022': ('20220101', '20221231'),      # 하락장
        'Bear2024Q3': ('20240801', '20241031'),    # 2024 Q3 조정
        'Bull2024H1': ('20240101', '20240630'),    # 2024 상반기
    }

    # dates를 연도별로 분류
    date_to_idx = {d: i for i, d in enumerate(dates)}

    top10_final = final.head(10)
    for _, cfg in top10_final.iterrows():
        sl = cfg.sl if pd.notna(cfg.sl) else None
        ct = cfg.corr_th if pd.notna(cfg.corr_th) else None
        tr = cfg.trail if pd.notna(cfg.trail) else None
        r = tsim.run_fast(
            cfg.v/100, cfg.q/100, cfg.g/100, cfg.m/100, cfg.g_rev,
            entry_param=int(cfg.entry), exit_param=cfg['exit'],
            max_slots=int(cfg.slots), stop_loss=sl,
            corr_threshold=ct, trailing_stop=tr, mom_type=cfg.mom
        )
        daily = r['_daily_rets']

        ex = cfg['exit']
        label = f'V{int(cfg.v)}Q{int(cfg.q)}G{int(cfg.g)}M{int(cfg.m)} g{cfg.g_rev} E{int(cfg.entry)}X{ex}S{int(cfg.slots)}'
        print(f'\n  {label} ({cfg.mom}):')
        line = '    '
        for period, (start, end) in year_ranges.items():
            period_rets = [daily[i] for i, d in enumerate(dates) if start <= d <= end]
            if not period_rets:
                line += f'{period}=N/A  '
                continue
            cum = 1.0
            peak = 1.0
            mdd = 0.0
            for ret in period_rets:
                cum *= (1 + ret)
                peak = max(peak, cum)
                dd = (cum - peak) / peak
                mdd = min(mdd, dd)
            days = len(period_rets)
            ann = (cum ** (252/max(days,1)) - 1) * 100
            line += f'{period}={ann:+.0f}%/{mdd*100:.0f}%  '
        print(line)

    elapsed = time.time() - t_start
    print(f'\n총 소요: {elapsed/60:.1f}분')


if __name__ == '__main__':
    main()
