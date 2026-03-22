"""G팩터 가중치 비교 백테스트 — 매출TTM vs op_change_asset 비율 최적화

3가지 가중 시나리오 × 3구간(2022 하락/2023 완만상승/2024)으로
MDD, CAGR, IR 밸런스를 데이터로 검증.

시나리오:
  - 50:50 (현행 v71 기본값)
  - 70:30 (매출 중심)
  - 30:70 (이익변화량 중심)

Phase 1: ranking 생성 (G_REVENUE_WEIGHT + RANKING_STATE_DIR 환경변수)
Phase 2: 각 ranking으로 백테스트 실행
Phase 3: 3구간 × 3시나리오 비교 테이블

Usage:
    python backtest/backtest_growth_ratio.py generate   # Phase 1: ranking 생성
    python backtest/backtest_growth_ratio.py compare     # Phase 2+3: 백테스트 + 비교
    python backtest/backtest_growth_ratio.py all         # 전체 (generate → compare)
"""
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

PYTHON = sys.executable
CACHE_DIR = PROJECT_ROOT / 'data_cache'

# G 가중치 시나리오
SCENARIOS = {
    'g50_50': 0.5,   # 매출 50% + 이익변화량 50% (현행)
    'g70_30': 0.7,   # 매출 70% + 이익변화량 30%
    'g30_70': 0.3,   # 매출 30% + 이익변화량 70%
}

# 백테스트 구간
PERIODS = {
    '2022_bear':  ('20220103', '20221229'),  # 하락장
    '2023_mild':  ('20230102', '20231228'),  # 완만한 상승
    '2024_mixed': ('20240102', '20241230'),  # 2024
}


def get_state_dir(scenario):
    """시나리오별 ranking 저장 디렉토리"""
    d = PROJECT_ROOT / 'state' / f'bt_{scenario}'
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_target_dates(start_str, end_str):
    """OHLCV 기반 거래일 목록"""
    import pandas as pd
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    if not ohlcv_files:
        print('OHLCV 파일 없음')
        return []
    ohlcv_df = pd.read_parquet(ohlcv_files[-1])
    all_dates = ohlcv_df.index

    # MA120(120) + 6M모멘텀(126) → 130거래일 히스토리 필요
    MIN_HISTORY = 130
    earliest = all_dates[MIN_HISTORY]
    start = pd.Timestamp(start_str)
    end = pd.Timestamp(end_str)
    start = max(start, earliest)
    target = all_dates[(all_dates >= start) & (all_dates <= end)]
    return [d.strftime('%Y%m%d') for d in target]


def generate_rankings(scenario, g_weight, start_str, end_str):
    """특정 시나리오의 ranking JSON 생성"""
    state_dir = get_state_dir(scenario)
    target_dates = get_target_dates(start_str, end_str)

    # 이미 생성된 날짜 스킵
    existing = set()
    for f in state_dir.glob('ranking_*.json'):
        d = f.stem.replace('ranking_', '')
        if len(d) == 8 and d.isdigit():
            existing.add(d)

    todo = [d for d in target_dates if d not in existing]
    print(f'\n[{scenario}] G_REVENUE_WEIGHT={g_weight}')
    print(f'  전체: {len(target_dates)}일, 기존: {len(existing)}일, 남은: {len(todo)}일')

    if not todo:
        print(f'  → 이미 완료')
        return len(existing)

    script = str(PROJECT_ROOT / 'create_current_portfolio.py')
    success = 0
    fail = 0
    t_start = time.time()

    for idx, date_str in enumerate(todo):
        env = os.environ.copy()
        env['CONSENSUS_FROM_JSON'] = '1'
        env['DISABLE_FWD_BONUS'] = '1'
        env['G_REVENUE_WEIGHT'] = str(g_weight)
        env['RANKING_STATE_DIR'] = str(state_dir)

        try:
            result = subprocess.run(
                [PYTHON, script, date_str],
                cwd=str(PROJECT_ROOT),
                env=env,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=300,
            )
            ranking_path = state_dir / f'ranking_{date_str}.json'
            if ranking_path.exists():
                success += 1
                if (idx + 1) % 50 == 0:
                    elapsed = time.time() - t_start
                    avg = elapsed / (idx + 1)
                    remaining = avg * (len(todo) - idx - 1) / 60
                    print(f'  [{idx+1}/{len(todo)}] {date_str} OK (~{remaining:.0f}분 남음)')
            else:
                fail += 1
                if result.stderr:
                    lines = result.stderr.strip().split('\n')
                    print(f'  [{idx+1}/{len(todo)}] {date_str} FAIL: {lines[-1][:80]}')
        except subprocess.TimeoutExpired:
            fail += 1
            print(f'  [{idx+1}/{len(todo)}] {date_str} TIMEOUT')
        except Exception as e:
            fail += 1

    elapsed = time.time() - t_start
    print(f'  완료: {success}성공 / {fail}실패 / {elapsed/60:.1f}분')
    return success + len(existing)


def run_comparison():
    """Phase 2+3: 각 시나리오별 백테스트 실행 + 비교"""
    from backtest_compare import load_data, run_backtest
    from bt_metrics import total_return, cagr, max_drawdown, information_ratio, sharpe_ratio, trade_stats

    # 기본 전략 설정 (v71 현행)
    base_config = {
        'label': '',
        'top_n': 20,
        'exit_rank': 20,
        'entry_score': 72,
        'exit_score': 68,
        'max_positions': 20,
        'require_3day': True,
        'fixed_stop': None,
        'trailing_stop': None,
        'sizing': 'equal',
        'vol_lookback': 5,
    }

    results = {}  # {(scenario, period): metrics_dict}

    for scenario, g_weight in SCENARIOS.items():
        state_dir = get_state_dir(scenario)
        n_files = len(list(state_dir.glob('ranking_*.json')))
        if n_files < 10:
            print(f'\n[{scenario}] ranking 부족 ({n_files}일) — 스킵')
            continue

        print(f'\n{"="*70}')
        print(f'  {scenario} (매출 {g_weight*100:.0f}% / 이익변화량 {(1-g_weight)*100:.0f}%) — {n_files}일')
        print(f'{"="*70}')

        try:
            db = load_data(state_dir=str(state_dir))
        except Exception as e:
            print(f'  데이터 로드 실패: {e}')
            continue

        ranking_dates = db['ranking_dates']

        for period_name, (start, end) in PERIODS.items():
            # 구간 필터
            period_dates = [d for d in ranking_dates if start <= d <= end]
            if len(period_dates) < 10:
                print(f'\n  [{period_name}] 데이터 부족 ({len(period_dates)}일) — 스킵')
                continue

            # 구간 한정 db 생성
            period_db = {
                'ranking_dates': period_dates,
                'rankings': {d: db['rankings'][d] for d in period_dates},
                'rank_maps': {d: db['rank_maps'][d] for d in period_dates},
                'score_maps': {d: db['score_maps'][d] for d in period_dates},
                'item_maps': {d: db['item_maps'][d] for d in period_dates},
                'all_prices': {d: db['all_prices'].get(d, {}) for d in period_dates},
                'ohlcv_prices': db['ohlcv_prices'],
                'ohlcv_trading_days': db['ohlcv_trading_days'],
                'benchmark_rets': db.get('benchmark_rets', {}),
                'kospi_rets': db.get('kospi_rets', {}),
                'kosdaq_rets': db.get('kosdaq_rets', {}),
            }

            cfg = base_config.copy()
            cfg['label'] = f'{scenario}_{period_name}'

            daily_rets, trades, port, bench, kospi, kosdaq = run_backtest(period_db, cfg)

            if not daily_rets:
                continue

            # 지표 계산
            tr = total_return(daily_rets)
            ca = cagr(daily_rets)
            mdd = max_drawdown(daily_rets)
            sr = sharpe_ratio(daily_rets)

            # IR: 벤치마크 대비
            bench_sub = [bench[i] if i < len(bench) else 0 for i in range(len(daily_rets))]
            ir = information_ratio(daily_rets, bench_sub)

            ts = trade_stats(trades) if trades else {}

            metrics = {
                'total_return': tr,
                'cagr': ca,
                'mdd': mdd,
                'sharpe': sr,
                'ir': ir,
                'n_trades': ts.get('total_trades', 0),
                'win_rate': ts.get('win_rate', 0),
                'n_days': len(daily_rets),
            }
            results[(scenario, period_name)] = metrics
            print(f'  [{period_name}] CAGR={ca:+.1f}% MDD={mdd:.1f}% IR={ir:.2f} Sharpe={sr:.2f}')

    # ── 비교 테이블 ──
    if not results:
        print('\n결과 없음')
        return

    print(f'\n{"="*90}')
    print(f'  G팩터 가중치 비교 — 3시나리오 × 구간')
    print(f'{"="*90}')

    # 구간별 비교
    for period_name in PERIODS:
        print(f'\n── {period_name} ──')
        header = f'{"시나리오":15s} {"CAGR":>8s} {"MDD":>8s} {"Sharpe":>8s} {"IR":>8s} {"승률":>6s} {"거래":>5s}'
        print(header)
        print('-' * len(header))

        for scenario in SCENARIOS:
            key = (scenario, period_name)
            if key not in results:
                print(f'{scenario:15s}  --- 데이터 없음 ---')
                continue
            m = results[key]
            print(f'{scenario:15s} {m["cagr"]:+7.1f}% {m["mdd"]:+7.1f}% '
                  f'{m["sharpe"]:7.2f} {m["ir"]:7.2f} {m["win_rate"]:5.1f}% {m["n_trades"]:4d}건')

    # 전구간 종합
    print(f'\n── 종합 (구간 평균) ──')
    header = f'{"시나리오":15s} {"avg CAGR":>10s} {"avg MDD":>10s} {"avg Sharpe":>12s} {"avg IR":>8s}'
    print(header)
    print('-' * len(header))

    for scenario in SCENARIOS:
        period_metrics = [results[(scenario, p)] for p in PERIODS if (scenario, p) in results]
        if not period_metrics:
            continue
        avg_cagr = sum(m['cagr'] for m in period_metrics) / len(period_metrics)
        avg_mdd = sum(m['mdd'] for m in period_metrics) / len(period_metrics)
        avg_sharpe = sum(m['sharpe'] for m in period_metrics) / len(period_metrics)
        avg_ir = sum(m['ir'] for m in period_metrics) / len(period_metrics)
        g_w = SCENARIOS[scenario]
        tag = f'매출{g_w*100:.0f}/이익{(1-g_w)*100:.0f}'
        print(f'{scenario:15s} {avg_cagr:+9.1f}% {avg_mdd:+9.1f}% '
              f'{avg_sharpe:11.2f} {avg_ir:7.2f}  ({tag})')

    print(f'\n{"="*90}')
    print('판정 기준: CAGR-MDD 밸런스 + IR 높은 쪽이 최적')
    print('50:50 대비 ±10% 이내 차이면 기본값(50:50) 유지 권장 (과적합 방지)')
    print(f'{"="*90}')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else None

    if cmd is None:
        print('사용법:')
        print('  python backtest/backtest_growth_ratio.py generate   # ranking 생성')
        print('  python backtest/backtest_growth_ratio.py compare    # 백테스트 비교')
        print('  python backtest/backtest_growth_ratio.py all        # 전체')
        return

    if cmd in ('generate', 'all'):
        print('=' * 70)
        print('Phase 1: G 가중치별 ranking 생성')
        print('=' * 70)

        # 전체 기간 (2022-2024) 한번에 생성
        all_start = min(s for s, e in PERIODS.values())
        all_end = max(e for s, e in PERIODS.values())

        for scenario, g_weight in SCENARIOS.items():
            generate_rankings(scenario, g_weight, all_start, all_end)

    if cmd in ('compare', 'all'):
        print('\n' + '=' * 70)
        print('Phase 2+3: 백테스트 실행 + 비교')
        print('=' * 70)
        run_comparison()


if __name__ == '__main__':
    main()
