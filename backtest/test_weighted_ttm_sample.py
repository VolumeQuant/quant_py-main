"""Phase A Step A-0: 가중 TTM 표본 테스트
3가지 TTM 설정 × 2구간(60일) 비교

설정:
  ① baseline: 균등 TTM (25/25/25/25)
  ② weighted: 가중 TTM (40/30/20/10)
  ③ half:     반기 TTM (50/50)

구간:
  A: 2025-01-02 ~ 2025-03-31 (공격 모드, 상승장)
  B: 2022-06-01 ~ 2022-08-31 (방어 모드, 하락장)
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import subprocess
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
FG_SCRIPT = str(SCRIPT_DIR / 'fast_generate_rankings_v2.py')
PYTHON = sys.executable

# 표본 구간
PERIODS = {
    'A_boost_2025': ('20250102', '20250331'),
    'B_defense_2022': ('20220601', '20220831'),
}

# TTM 설정
CONFIGS = {
    'baseline': '',                    # 균등 (기본값)
    'weighted': '0.4,0.3,0.2,0.1',    # 가중
    'half': '0.5,0.5',                 # 반기
}

# v79 boost 파라미터
BOOST_ENV = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.05',
    'FACTOR_G_W': '0.50', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_SUB3': 'gp_growth_z',
    'G_W1': '0.5', 'G_W2': '0.3', 'G_W3': '0.2',
    'G_REVENUE_WEIGHT': '0.0',
    'MOM_PERIOD': '12m',
    'PRODUCTION_MODE': '1',
}

# v79 defense 파라미터
DEFENSE_ENV = {
    'FACTOR_V_W': '0.30', 'FACTOR_Q_W': '0.15',
    'FACTOR_G_W': '0.15', 'FACTOR_M_W': '0.40',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z',
    'G_REVENUE_WEIGHT': '0.7',
    'MOM_PERIOD': '6m-1m',
    'PRODUCTION_MODE': '1',
}

def run_fg(start_date, end_date, state_dir, env_vars, ttm_weights):
    """FG 실행 → ranking JSON 생성"""
    os.makedirs(state_dir, exist_ok=True)
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    env.update(env_vars)
    if ttm_weights:
        env['TTM_WEIGHTS'] = ttm_weights
    elif 'TTM_WEIGHTS' in env:
        del env['TTM_WEIGHTS']

    cmd = [PYTHON, '-u', FG_SCRIPT, start_date, end_date, f'--state-dir={state_dir}']
    result = subprocess.run(
        cmd, cwd=str(PROJECT_DIR), capture_output=True,
        text=True, timeout=600, encoding='utf-8', errors='replace', env=env,
    )
    if result.returncode != 0:
        print(f'  ERROR: {result.stderr[:500]}')
        return False
    return True


def load_rankings(state_dir):
    """state_dir에서 ranking JSON 전부 로드 → {date: [{ticker, rank, score, rev_z, ...}]}"""
    rankings = {}
    for fp in sorted(Path(state_dir).glob('ranking_*.json')):
        date = fp.stem.replace('ranking_', '')
        with open(fp, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rankings[date] = data.get('rankings', [])
    return rankings


def compare_configs(results_by_config, mode_label):
    """3가지 설정 비교 분석"""
    configs = list(results_by_config.keys())
    dates = sorted(set().union(*(results_by_config[c].keys() for c in configs)))

    if not dates:
        print(f'  [{mode_label}] 생성된 날짜 없음!')
        return {}

    print(f'\n{"="*60}')
    print(f'[{mode_label}] {len(dates)}일 비교')
    print(f'{"="*60}')

    stats = {}
    for cfg in configs:
        rankings = results_by_config[cfg]
        # Top 20 종목 추출 (각 날짜)
        top20_sets = {}
        top7_sets = {}
        rev_z_means = []
        oca_z_means = []

        for date in dates:
            if date not in rankings:
                continue
            items = rankings[date][:20]
            top20_sets[date] = set(r['ticker'] for r in items)
            top7_sets[date] = set(r['ticker'] for r in items[:7])

            rev_zs = [r.get('rev_z', 0) for r in items if r.get('rev_z') is not None]
            oca_zs = [r.get('oca_z', 0) for r in items if r.get('oca_z') is not None]
            if rev_zs:
                rev_z_means.append(sum(rev_zs) / len(rev_zs))
            if oca_zs:
                oca_z_means.append(sum(oca_zs) / len(oca_zs))

        stats[cfg] = {
            'top20_sets': top20_sets,
            'top7_sets': top7_sets,
            'rev_z_mean': sum(rev_z_means) / len(rev_z_means) if rev_z_means else 0,
            'oca_z_mean': sum(oca_z_means) / len(oca_z_means) if oca_z_means else 0,
            'n_dates': len([d for d in dates if d in rankings]),
        }

    # Top 20 겹침률 (baseline vs weighted, baseline vs half)
    baseline_dates = stats['baseline']['top20_sets']
    for cfg in ['weighted', 'half']:
        cfg_dates = stats[cfg]['top20_sets']
        overlaps = []
        for date in dates:
            if date in baseline_dates and date in cfg_dates:
                inter = baseline_dates[date] & cfg_dates[date]
                union = baseline_dates[date] | cfg_dates[date]
                if union:
                    overlaps.append(len(inter) / len(union))
        avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0
        print(f'\n  baseline vs {cfg} Top 20 Jaccard 겹침률: {avg_overlap:.1%} ({len(overlaps)}일)')

    # Top 7 겹침률
    baseline_t7 = stats['baseline']['top7_sets']
    for cfg in ['weighted', 'half']:
        cfg_t7 = stats[cfg]['top7_sets']
        overlaps = []
        for date in dates:
            if date in baseline_t7 and date in cfg_t7:
                inter = baseline_t7[date] & cfg_t7[date]
                union = baseline_t7[date] | cfg_t7[date]
                if union:
                    overlaps.append(len(inter) / len(union))
        avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0
        print(f'  baseline vs {cfg} Top 7  Jaccard 겹침률: {avg_overlap:.1%}')

    # 평균 z-score 비교
    print(f'\n  {"설정":>12} | {"rev_z 평균":>10} | {"oca_z 평균":>10} | {"날짜수":>6}')
    print(f'  {"-"*48}')
    for cfg in configs:
        s = stats[cfg]
        print(f'  {cfg:>12} | {s["rev_z_mean"]:>10.3f} | {s["oca_z_mean"]:>10.3f} | {s["n_dates"]:>6}')

    # 가중 TTM에서만 Top 20에 있는 종목 (baseline에 없는)
    unique_tickers = defaultdict(int)
    for cfg in ['weighted', 'half']:
        cfg_dates = stats[cfg]['top20_sets']
        for date in dates:
            if date in baseline_dates and date in cfg_dates:
                diff = cfg_dates[date] - baseline_dates[date]
                for t in diff:
                    unique_tickers[(cfg, t)] += 1

    if unique_tickers:
        print(f'\n  가중/반기에서만 Top 20인 종목 (baseline에 없는):')
        for (cfg, ticker), count in sorted(unique_tickers.items(), key=lambda x: -x[1])[:10]:
            print(f'    [{cfg}] {ticker}: {count}일')

    # 섹터별 분포 비교
    sector_counts = {cfg: defaultdict(int) for cfg in configs}
    for cfg in configs:
        for date in dates:
            if date not in results_by_config[cfg]:
                continue
            for r in results_by_config[cfg][date][:20]:
                sector_counts[cfg][r.get('sector', '?')] += 1

    print(f'\n  Top 20 섹터 분포:')
    all_sectors = sorted(set().union(*(sc.keys() for sc in sector_counts.values())))
    print(f'  {"섹터":>12} | {"baseline":>10} | {"weighted":>10} | {"half":>10}')
    print(f'  {"-"*52}')
    for sec in all_sectors:
        b = sector_counts['baseline'].get(sec, 0)
        w = sector_counts['weighted'].get(sec, 0)
        h = sector_counts['half'].get(sec, 0)
        if max(b, w, h) >= 10:  # 빈도 10 이상만
            flag = ' ←차이' if abs(w - b) > b * 0.2 or abs(h - b) > b * 0.2 else ''
            print(f'  {sec:>12} | {b:>10} | {w:>10} | {h:>10}{flag}')

    return stats


def main():
    t0 = time.time()
    all_stats = {}

    for period_name, (start, end) in PERIODS.items():
        mode = 'boost' if 'boost' in period_name else 'defense'
        mode_env = BOOST_ENV if mode == 'boost' else DEFENSE_ENV

        results = {}
        for cfg_name, ttm_w in CONFIGS.items():
            state_dir = str(PROJECT_DIR / 'backtest' / f'sample_ttm_{period_name}_{cfg_name}')
            print(f'\n>>> [{period_name}] {cfg_name} (TTM={ttm_w or "균등"}) → {state_dir}')

            ok = run_fg(start, end, state_dir, mode_env, ttm_w)
            if ok:
                results[cfg_name] = load_rankings(state_dir)
                print(f'  생성: {len(results[cfg_name])}일')
            else:
                print(f'  실패!')
                results[cfg_name] = {}

        all_stats[period_name] = compare_configs(results, period_name)

    elapsed = time.time() - t0
    print(f'\n총 소요: {elapsed:.0f}초')

    # 결과 JSON 저장
    summary_path = PROJECT_DIR / 'backtest' / 'ttm_sample_summary.json'
    summary = {}
    for period_name, stats in all_stats.items():
        summary[period_name] = {
            cfg: {
                'rev_z_mean': s['rev_z_mean'],
                'oca_z_mean': s['oca_z_mean'],
                'n_dates': s['n_dates'],
            } for cfg, s in stats.items()
        }
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'요약 저장: {summary_path}')


if __name__ == '__main__':
    main()
