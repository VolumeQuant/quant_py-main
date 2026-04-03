"""Grid Search Final — 단일 스레드 + 선택적 병렬

Round 1: 기존 bt 파일 그대로, Calmar 최적화, 안정성 필터, 연도별 분해

Usage:
    python backtest/grid_search_final.py
    python backtest/grid_search_final.py --workers 3
    python backtest/grid_search_final.py --test  (소규모 테스트)
"""
import sys
import os
import json
import glob
import time
import argparse
import requests
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

CACHE_DIR = PROJECT / 'data_cache'
RESULTS_DIR = PROJECT / 'backtest_results'
RESULTS_DIR.mkdir(exist_ok=True)

# 텔레그램
try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
except ImportError:
    TELEGRAM_BOT_TOKEN = TELEGRAM_PRIVATE_ID = None


def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg, 'parse_mode': 'HTML'},
            timeout=30,
        )
    except Exception:
        pass


def load_rankings(years, prefix='bt'):
    all_rankings = {}

    # 단일 디렉토리 (bt_2a 등) 또는 연도별 디렉토리 (bt_2021 등)
    single_dir = PROJECT / f'state/{prefix}'
    if single_dir.is_dir():
        # 단일 디렉토리: 연도 필터링
        for f in sorted(glob.glob(str(single_dir / 'ranking_*.json'))):
            date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            if date[:4] in years:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    all_rankings[date] = data.get('rankings', data) if isinstance(data, dict) else data
    else:
        # 연도별 디렉토리: bt_2021, bt_2022, ...
        for year in years:
            pattern = str(PROJECT / f'state/{prefix}_{year}/ranking_*.json')
            for f in sorted(glob.glob(pattern)):
                date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    all_rankings[date] = data.get('rankings', data) if isinstance(data, dict) else data

    dates = sorted(all_rankings.keys())
    return all_rankings, dates


def generate_weight_grid():
    """V(0~40) Q(0~40) G(10~70) M(10~60), step=5"""
    combos = []
    for v in range(0, 45, 5):
        for q in range(0, 45, 5):
            for g in range(10, 75, 5):
                m = 100 - v - q - g
                if 10 <= m <= 60:
                    combos.append((v, q, g, m))
    return combos


def generate_rules():
    """entry/exit/slots/corr_threshold 조합"""
    entry_list = [3, 5, 7]
    exit_list = [5, 7, 10, 15]
    slots_list = [3, 5, 7]
    corr_list = [None, 0.4, 0.5]
    return [(e, x, s, ct) for e in entry_list for x in exit_list
            for s in slots_list for ct in corr_list if x > e]


# === 병렬 워커 (모듈 레벨) ===
_worker_sim = None
_worker_rules = None


def _init_worker(train_years, prefix):
    """워커 프로세스 시작 시 1회 데이터 로드"""
    global _worker_sim, _worker_rules
    from turbo_simulator import TurboSimulator

    all_rankings, dates = load_rankings(train_years, prefix)
    prices = pd.read_parquet(
        sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'), key=lambda f: f.stem.split('_')[2])[0]
    ).replace(0, np.nan)

    _worker_sim = TurboSimulator(all_rankings, dates, prices)
    _worker_rules = generate_rules()


def _run_weight_batch(weight_combo):
    """워커: 1개 가중치 × 전체 규칙 (데이터는 _init_worker에서 로드됨)"""
    global _worker_sim, _worker_rules
    from turbo_simulator import TurboRunner

    v, q, g, m, g_rev = weight_combo
    _worker_sim._ensure_cache(v/100, q/100, g/100, m/100, g_rev, 20)
    runner = TurboRunner(_worker_sim)

    results = []
    for entry_p, exit_p, slots, corr_th in _worker_rules:
        r = runner.run(entry_p, exit_p, slots, corr_threshold=corr_th)
        results.append({
            'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev,
            'entry': entry_p, 'exit': exit_p, 'slots': slots,
            'corr_th': corr_th,
            **r,
        })
    return results


def stability_check(result, top100_weight_keys):
    """이웃 ±5% 중 3개 이상이 top100에 있으면 stable"""
    v, q, g, m, g_rev = result['v'], result['q'], result['g'], result['m'], result['g_rev']
    count = 0
    for dv in [-5, 0, 5]:
        for dq in [-5, 0, 5]:
            for dg in [-5, 0, 5]:
                nv, nq, ng = v + dv, q + dq, g + dg
                nm = 100 - nv - nq - ng
                if (nv, nq, ng, nm) == (v, q, g, m):
                    continue
                if (nv, nq, ng, nm, g_rev) in top100_weight_keys:
                    count += 1
    return count >= 3


def evaluate_on_period(years, best_configs, prefix='bt'):
    """특정 기간에 대해 best configs 평가"""
    from turbo_simulator import TurboSimulator, TurboRunner

    all_rankings, dates = load_rankings(years, prefix)
    if not dates:
        return []

    prices = pd.read_parquet(
        sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'), key=lambda f: f.stem.split('_')[2])[0]
    ).replace(0, np.nan)

    tsim = TurboSimulator(all_rankings, dates, prices)
    results = []
    for cfg in best_configs:
        tsim._ensure_cache(cfg['v']/100, cfg['q']/100, cfg['g']/100, cfg['m']/100, cfg['g_rev'], 20)
        runner = TurboRunner(tsim)
        r = runner.run(cfg['entry'], cfg['exit'], cfg['slots'],
                       corr_threshold=cfg.get('corr_th'))
        results.append({**cfg, **r, 'period': f"{years[0]}~{years[-1]}"})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=0, help='병렬 워커 수 (0=단일 스레드)')
    parser.add_argument('--test', action='store_true', help='소규모 테스트 (20 가중치)')
    parser.add_argument('--prefix', default='bt', help='bt 디렉토리 prefix')
    args = parser.parse_args()

    t_start = time.time()
    train_years = ['2021', '2022', '2023', '2024']
    test_years = ['2025']

    # ================================================================
    # 데이터 로드 (메인 프로세스 — 단일 스레드용)
    # ================================================================
    print('=== 데이터 로드 ===')
    from turbo_simulator import TurboSimulator, TurboRunner

    train_rankings, train_dates = load_rankings(train_years, args.prefix)
    prices = pd.read_parquet(
        sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'), key=lambda f: f.stem.split('_')[2])[0]
    ).replace(0, np.nan)
    bench = pd.read_parquet(CACHE_DIR / 'index_benchmarks.parquet') \
        if (CACHE_DIR / 'index_benchmarks.parquet').exists() else pd.DataFrame()

    print(f'Train: {len(train_dates)}거래일 ({train_dates[0]}~{train_dates[-1]})')

    # ================================================================
    # Grid Search
    # ================================================================
    weights = generate_weight_grid()
    g_ratios = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    rules = generate_rules()

    if args.test:
        weights = weights[:20]
        print('⚠ 테스트 모드: 20 가중치만')

    weight_g_combos = [(v, q, g, m, gr) for (v, q, g, m) in weights for gr in g_ratios]
    n_total = len(weight_g_combos)
    n_rules = len(rules)

    print(f'\n=== Grid Search ===')
    print(f'가중치: {len(weights)} × G비율: {len(g_ratios)} = {n_total}')
    print(f'매매규칙: {n_rules}개')
    print(f'총 조합: {n_total * n_rules:,}')

    all_results = []

    if args.workers > 0:
        # ===== 병렬 실행 (워커당 1회 데이터 로드) =====
        print(f'병렬: {args.workers}워커 (워커당 1회 데이터 로드)')
        done = 0

        with ProcessPoolExecutor(max_workers=args.workers,
                                 initializer=_init_worker,
                                 initargs=(train_years, args.prefix)) as executor:
            futures = {executor.submit(_run_weight_batch, wg): wg for wg in weight_g_combos}
            for future in futures:
                try:
                    batch = future.result(timeout=300)
                    all_results.extend(batch)
                except Exception as e:
                    wg = futures[future]
                    print(f'  ⚠ V{wg[0]}Q{wg[1]}G{wg[2]}M{wg[3]} g={wg[4]} 실패: {e}')

                done += 1
                if done % 200 == 0 or done == n_total:
                    elapsed = time.time() - t_start
                    rate = done / elapsed if elapsed > 0 else 1
                    remain = (n_total - done) / rate / 60 if rate > 0 else 0
                    print(f'  [{done}/{n_total}] {elapsed/60:.0f}분 | 남은 ~{remain:.0f}분', flush=True)
    else:
        # ===== 단일 스레드 =====
        print('단일 스레드')
        tsim = TurboSimulator(train_rankings, train_dates, prices)
        done = 0

        for v, q, g, m, g_rev in weight_g_combos:
            tsim._ensure_cache(v/100, q/100, g/100, m/100, g_rev, 20)
            runner = TurboRunner(tsim)

            for entry_p, exit_p, slots, corr_th in rules:
                r = runner.run(entry_p, exit_p, slots, corr_threshold=corr_th)
                all_results.append({
                    'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev,
                    'entry': entry_p, 'exit': exit_p, 'slots': slots,
                    'corr_th': corr_th,
                    **r,
                })

            done += 1
            if done % 200 == 0 or done == n_total:
                elapsed = time.time() - t_start
                rate = done / elapsed if elapsed > 0 else 1
                remain = (n_total - done) / rate / 60 if rate > 0 else 0
                print(f'  [{done}/{n_total}] {elapsed/60:.0f}분 | 남은 ~{remain:.0f}분', flush=True)

                # 중간 저장
                tmp = RESULTS_DIR / 'grid_checkpoint.json'
                with open(tmp, 'w') as f:
                    json.dump({'done': done, 'total': n_total, 'n_results': len(all_results)}, f)

    search_elapsed = time.time() - t_start

    # ================================================================
    # 결과 정렬 + 필터
    # ================================================================
    print(f'\n=== 결과 처리 ({len(all_results):,}개) ===')

    # Calmar 기준 정렬 (NaN/inf 처리)
    for r in all_results:
        c = r.get('calmar', 0)
        if c is None or (isinstance(c, float) and (np.isnan(c) or np.isinf(c))):
            r['calmar'] = 0

    all_results.sort(key=lambda x: -x['calmar'])

    # Top 100 weight keys (안정성 필터용)
    top100_weight_keys = set()
    for r in all_results[:100]:
        top100_weight_keys.add((r['v'], r['q'], r['g'], r['m'], r['g_rev']))

    # 안정성 필터
    stable_results = [r for r in all_results[:50] if stability_check(r, top100_weight_keys)]
    if len(stable_results) < 5:
        print(f'⚠ 안정성 필터 통과 {len(stable_results)}개 (최소 기준 미달) — 필터 없이 Top 20 사용')
        top_results = all_results[:20]
        stability_applied = False
    else:
        top_results = stable_results[:20]
        stability_applied = True

    # Top 20 출력
    print(f'\n{"#":>3} {"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Grev":>4} {"E":>2}{"X":>3}{"S":>3} {"Corr":>5} | '
          f'{"Calmar":>6} {"CAGR":>6} {"Shrp":>5} {"MDD":>5} {"Alpha":>6} {"H":>3} {"Stab":>4}')
    print('-' * 78)
    for i, r in enumerate(top_results[:20]):
        is_stable = '✓' if stability_check(r, top100_weight_keys) else '✗'
        ct = f'{r.get("corr_th","")}' if r.get('corr_th') else 'none'
        print(f'{i+1:3d} {r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["g_rev"]:4.1f} '
              f'{r["entry"]:2d}{r["exit"]:3d}{r["slots"]:3d} {ct:>5} | '
              f'{r["calmar"]:6.3f} {r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["mdd"]:4.1f}% '
              f'{r.get("alpha",0):+5.1f}% {r["avg_holdings"]:3.1f} {is_stable:>4}')

    # ================================================================
    # 연도별 성과 분해 (Top 5)
    # ================================================================
    print(f'\n=== 연도별 성과 (Top 5) ===')
    year_labels = ['2021', '2022', '2023', '2024', '2025(OOS)']
    year_groups = [['2021'], ['2022'], ['2023'], ['2024'], ['2025']]

    top5 = top_results[:5]
    header = f'{"Config":<30} | ' + ' | '.join(f'{y:>12}' for y in year_labels)
    print(header)
    print('-' * len(header))

    year_details = []
    for cfg in top5:
        label = f'V{cfg["v"]}Q{cfg["q"]}G{cfg["g"]}M{cfg["m"]} g={cfg["g_rev"]}'
        row = f'{label:<30} | '
        cfg_years = {}
        for yl, yg in zip(year_labels, year_groups):
            yr_results = evaluate_on_period(yg, [cfg], args.prefix)
            if yr_results:
                yr = yr_results[0]
                row += f'C={yr["calmar"]:+.2f} R={yr["cagr"]:+.0f}% | '
                cfg_years[yl] = yr
            else:
                row += f'{"N/A":>12} | '
        print(row)
        year_details.append({'config': label, 'years': cfg_years})

    # 2022 stress test
    print(f'\n=== 2022 Stress Test ===')
    for cfg in top5:
        stress = evaluate_on_period(['2022'], [cfg], args.prefix)
        if stress:
            s = stress[0]
            print(f'V{cfg["v"]}Q{cfg["q"]}G{cfg["g"]}M{cfg["m"]}: '
                  f'CAGR={s["cagr"]:+.1f}% MDD={s["mdd"]:.1f}% Calmar={s["calmar"]:.3f} '
                  f'Alpha={s.get("alpha",0):+.1f}%')

    # ================================================================
    # 결과 저장
    # ================================================================
    final = {
        'search_params': {
            'train_years': train_years,
            'test_years': test_years,
            'n_weights': len(weights),
            'n_g_ratios': len(g_ratios),
            'n_rules': n_rules,
            'total_combos': len(all_results),
            'elapsed_minutes': round(search_elapsed / 60, 1),
            'stability_applied': stability_applied,
            'metric': 'calmar',
        },
        'top200': top_results[:200],
        'year_details': year_details,
    }

    # prefix에 따라 파일명 분리
    suffix = f'_{args.prefix}' if args.prefix != 'bt' else ''
    out_file = RESULTS_DIR / f'grid_search_round1{suffix}.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    print(f'\n결과 저장: {out_file}')

    total_elapsed = time.time() - t_start
    print(f'전체 소요: {total_elapsed/60:.1f}분')

    # ================================================================
    # 텔레그램 보고
    # ================================================================
    if not top_results:
        send_telegram('❌ Grid Search 결과 0개 — 전체 실패')
        print('❌ 결과 없음')
        return

    best = top_results[0]
    msg = (
        f"<b>Grid Search Round 1 완료</b>\n"
        f"소요: {search_elapsed/60:.0f}분 | {len(all_results):,}조합\n"
        f"학습: {train_years[0]}~{train_years[-1]} | 검증: {test_years[0]}\n\n"
        f"<b>Top 3 (Calmar):</b>\n"
    )
    for i, r in enumerate(top_results[:3]):
        ct = f"corr={r.get('corr_th')}" if r.get('corr_th') else "no filter"
        msg += (f"{i+1}. V{r['v']}Q{r['q']}G{r['g']}M{r['m']} g={r['g_rev']}\n"
                f"   E{r['entry']}/X{r['exit']}/S{r['slots']} {ct}\n"
                f"   Calmar={r['calmar']:.3f} CAGR={r['cagr']:.1f}% MDD={r['mdd']:.1f}%\n")

    # 2022 stress
    stress = evaluate_on_period(['2022'], [top_results[0]], args.prefix)
    if stress:
        s = stress[0]
        msg += f"\n<b>2022 Stress:</b> CAGR={s['cagr']:+.1f}% MDD={s['mdd']:.1f}%\n"

    # OOS
    oos = evaluate_on_period(test_years, [top_results[0]], args.prefix)
    if oos:
        o = oos[0]
        msg += f"<b>2025 OOS:</b> CAGR={o['cagr']:+.1f}% Calmar={o['calmar']:.3f}\n"

    msg += f"\n안정성 필터: {'적용' if stability_applied else '미적용'}"
    send_telegram(msg)

    print('\n✅ Round 1 완료')


if __name__ == '__main__':
    main()
