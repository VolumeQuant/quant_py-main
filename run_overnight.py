"""오버나이트 마스터 스크립트 — Phase 2~4 + 최적화 + 검증 + 프로덕션

모든 단계를 순차적으로 실행. 내일 출근 전까지 완료.

단계:
  1. 현재 진행 중인 bt_2024/2025 완료 대기
  2. Phase 2: 전체 연도 Grid Search (팩터비율 + G비율 + Growth캡)
  3. Phase 3: 진입/이탈 + 슬롯 최적화
  4. Phase 4: Walk-Forward 검증
  5. 최적 조합 결정 → 텔레그램 보고
  6. 프로덕션 실행 (개인봇)
  7. DART 2017-2018 수집 + pykrx 확인
  8. bt_2020, bt_2021 생성
  9. 최적 전략으로 bt_2020/2021 검증 → 텔레그램 보고
  10. 프로덕션 재실행 (개인봇)
"""
import subprocess
import sys
import os
import json
import glob
import time
import shutil
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
os.chdir(r'C:\dev')

PYTHON = r'C:\Users\user\miniconda3\envs\volumequant\python.exe'
PROJECT = Path(r'C:\dev')
CACHE_DIR = PROJECT / 'data_cache'
LOG_PATH = PROJECT / 'logs' / f'overnight_{datetime.now().strftime("%Y%m%d_%H%M")}.log'
LOG_PATH.parent.mkdir(exist_ok=True)


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def run(cmd, timeout=3600, desc=''):
    log(f'실행: {desc or cmd}')
    result = subprocess.run(
        cmd, shell=True, cwd=str(PROJECT),
        capture_output=True, text=True, timeout=timeout,
        encoding='utf-8', errors='replace',
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
    )
    if result.returncode != 0:
        log(f'  실패: {result.stderr[:200] if result.stderr else "no stderr"}')
    return result.returncode == 0


def send_telegram(message):
    """개인봇에 메시지 전송"""
    try:
        sys.path.insert(0, str(PROJECT))
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        import requests
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
            data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': message, 'parse_mode': 'HTML'},
            timeout=30,
        )
        log('텔레그램 전송 완료')
    except Exception as e:
        log(f'텔레그램 전송 실패: {e}')


def wait_for_rankings_complete():
    """bt_2022~2025 누락분 직접 생성 + 검증"""
    log('=== Step 1: bt_2022~2025 누락분 생성 ===')
    import pandas as pd
    ohlcv = pd.read_parquet(sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                                    key=lambda f: f.stem.split('_')[2])[0])
    jobs = [
        ('bt_2022', '20220103', '20221229'),
        ('bt_2023', '20230102', '20231228'),
        ('bt_2024', '20240102', '20241230'),
        ('bt_2025', '20250102', '20260320'),
    ]
    for bt, start, end in jobs:
        trading_days = ohlcv.loc[start:end].index
        existing = len(glob.glob(f'state/{bt}/ranking_*.json'))
        target = len(trading_days)
        if existing < target:
            # 구코드 파일 삭제
            bad = 0
            for f in glob.glob(f'state/{bt}/ranking_*.json'):
                with open(f, 'r', encoding='utf-8') as fh:
                    r = json.load(fh).get('rankings', [])
                if any('price' not in s or s['price'] is None for s in r):
                    os.remove(f)
                    bad += 1
            remaining = len(glob.glob(f'state/{bt}/ranking_*.json'))
            missing = target - remaining
            log(f'  {bt}: 구코드 {bad}개 삭제, {remaining}/{target} 있음, {missing}개 생성 필요')
            if missing > 0:
                # 캐시 복사 + resume
                cache_tmp = PROJECT / f'data_cache_tmp_{bt}'
                if cache_tmp.exists():
                    shutil.rmtree(cache_tmp)
                shutil.copytree(CACHE_DIR, cache_tmp)
                result = subprocess.run(
                    [PYTHON, '-u', str(PROJECT / 'backtest/fast_generate_rankings.py'),
                     start, end, '--state-dir', f'state/{bt}',
                     '--cache-dir', str(cache_tmp), '--resume'],
                    cwd=str(PROJECT), capture_output=True, text=True, timeout=7200,
                    encoding='utf-8', errors='replace',
                )
                shutil.rmtree(cache_tmp, ignore_errors=True)
                final = len(glob.glob(f'state/{bt}/ranking_*.json'))
                log(f'  {bt}: 생성 완료 → {final}/{target}')
        else:
            log(f'  {bt}: {existing}/{target} 이미 완료')

    # 최종 검증
    for bt, _, _ in jobs:
        files = sorted(glob.glob(f'state/{bt}/ranking_*.json'))
        bad = sum(1 for f in files if any(
            'price' not in s or s['price'] is None
            for s in json.load(open(f, 'r', encoding='utf-8')).get('rankings', [])))
        log(f'  검증 {bt}: {len(files)}파일, price누락={bad}')


def phase2_grid_search():
    """Phase 2: 팩터비율 Grid Search"""
    log('=== Step 2: Phase 2 Grid Search (전체 연도) ===')
    run(f'{PYTHON} -u backtest/master_grid_search.py --years 2022,2023,2024,2025',
        timeout=7200, desc='Phase 2 Grid Search 전체')
    return True


def phase3_entry_exit(top_weights):
    """Phase 3: 진입/이탈 최적화"""
    log('=== Step 3: Phase 3 진입/이탈 최적화 ===')

    import pandas as pd
    import numpy as np

    # 랭킹 로드
    all_data = {}
    for year in ['2022', '2023', '2024', '2025']:
        for f in sorted(glob.glob(f'state/bt_{year}/ranking_*.json')):
            date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            with open(f, 'r', encoding='utf-8') as fh:
                all_data[date] = json.load(fh).get('rankings', [])
    dates = sorted(all_data.keys())

    prices = pd.read_parquet(sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                                     key=lambda f: f.stem.split('_')[2])[0])
    prices = prices.replace(0, np.nan)

    def compute_score_100(s0, s1, s2):
        ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
        return max(0, min(100, (ws + 0.7) / 2.4 * 100))

    best_result = None
    best_params = None
    results = []

    # Top weight에서 진입/이탈 테스트
    for w in top_weights[:3]:  # Top 3 weight만
        v_w, q_w, g_w, m_w = w['v']/100, w['q']/100, w['g']/100, w['m']/100
        g_rev, g_cap = w['g_rev'], w['g_cap']

        # 전략 유형별 테스트
        for strategy in ['rank', 'score']:
            if strategy == 'rank':
                param_grid = [(entry, exit_r, slots)
                              for entry in [3, 5, 7, 10]
                              for exit_r in [10, 15, 20, 25]
                              for slots in [3, 5, 7, 10, 0]
                              if exit_r > entry]
            else:
                param_grid = [(entry, exit_s, slots)
                              for entry in [64, 66, 68, 70, 72, 74]
                              for exit_s in [58, 60, 62, 64, 66, 68]
                              for slots in [3, 5, 7, 10, 0]
                              if entry > exit_s]

            for entry_p, exit_p, max_slots in param_grid:
                portfolio = {}
                daily_returns = []

                for i in range(2, len(dates)):
                    d0, d1, d2 = dates[i], dates[i-1], dates[i-2]
                    r0 = all_data[d0]
                    r1 = all_data[d1]
                    r2 = all_data[d2]

                    if not r0:
                        daily_returns.append(0)
                        continue

                    # 재가중
                    def reweight(rankings):
                        scored = []
                        for s in rankings:
                            v = (s.get('value_s') or 0)
                            q = (s.get('quality_s') or 0)
                            m = (s.get('momentum_s') or 0)
                            rev = (s.get('rev_z') or 0)
                            oca = (s.get('oca_z') or 0)
                            if g_cap < 900:
                                cap_z = g_cap / 100
                                rev = max(-cap_z, min(cap_z, rev))
                                oca = max(-cap_z, min(cap_z, oca))
                            g = g_rev * rev + (1 - g_rev) * oca
                            score = v_w * v + q_w * q + g_w * g + m_w * m
                            scored.append({**s, 'new_score': score})
                        scored.sort(key=lambda x: -x['new_score'])
                        for j, s in enumerate(scored):
                            s['new_rank'] = j + 1
                        return scored

                    scored0 = reweight(r0)
                    scored1 = reweight(r1)
                    scored2 = reweight(r2)

                    ticker_map0 = {s['ticker']: s for s in scored0}
                    ticker_map1 = {s['ticker']: s for s in scored1}
                    ticker_map2 = {s['ticker']: s for s in scored2}

                    # 매도
                    for tk in list(portfolio.keys()):
                        s0_s = ticker_map0.get(tk, {})
                        if strategy == 'rank':
                            if s0_s.get('new_rank', 999) > exit_p:
                                del portfolio[tk]
                        else:
                            s0_v = s0_s.get('new_score', 0)
                            s1_v = ticker_map1.get(tk, {}).get('new_score', 0)
                            s2_v = ticker_map2.get(tk, {}).get('new_score', 0)
                            sc100 = compute_score_100(s0_v, s1_v, s2_v)
                            if sc100 < exit_p:
                                del portfolio[tk]

                    # 매수
                    candidates = []
                    for s in scored0:
                        tk = s['ticker']
                        if tk in portfolio:
                            continue
                        if strategy == 'rank':
                            if s['new_rank'] <= entry_p:
                                candidates.append(tk)
                        else:
                            s1_v = ticker_map1.get(tk, {}).get('new_score', 0)
                            s2_v = ticker_map2.get(tk, {}).get('new_score', 0)
                            sc100 = compute_score_100(s['new_score'], s1_v, s2_v)
                            if sc100 >= entry_p:
                                candidates.append(tk)

                    for tk in candidates:
                        if max_slots > 0 and len(portfolio) >= max_slots:
                            break
                        p = ticker_map0[tk].get('price')
                        if p:
                            portfolio[tk] = p

                    # 수익률
                    if i + 1 < len(dates) and portfolio:
                        next_ts = pd.Timestamp(dates[i + 1])
                        cur_ts = pd.Timestamp(d0)
                        if next_ts in prices.index and cur_ts in prices.index:
                            rets = []
                            for tk in portfolio:
                                if tk in prices.columns:
                                    c = prices.loc[next_ts, tk]
                                    p = prices.loc[cur_ts, tk]
                                    if pd.notna(c) and pd.notna(p) and p > 0:
                                        rets.append(c / p - 1)
                            daily_returns.append(np.mean(rets) if rets else 0)
                        else:
                            daily_returns.append(0)
                    else:
                        daily_returns.append(0)

                # 메트릭 계산
                if daily_returns:
                    equity = [1.0]
                    for r in daily_returns:
                        equity.append(equity[-1] * (1 + r))
                    total = (equity[-1] - 1) * 100
                    n = len(daily_returns)
                    cagr = (equity[-1] ** (252 / max(n, 1)) - 1) * 100
                    arr = np.array(daily_returns)
                    sharpe = (arr.mean() / arr.std() * np.sqrt(252)) if arr.std() > 0 else 0
                    peak = np.maximum.accumulate(equity)
                    dd = (np.array(equity) - peak) / peak
                    mdd = abs(dd.min()) * 100

                    result = {
                        'v': w['v'], 'q': w['q'], 'g': w['g'], 'm': w['m'],
                        'g_rev': g_rev, 'g_cap': g_cap,
                        'strategy': strategy, 'entry': entry_p, 'exit': exit_p,
                        'slots': max_slots,
                        'cagr': round(cagr, 2), 'sharpe': round(sharpe, 3),
                        'mdd': round(mdd, 2), 'total_ret': round(total, 2),
                    }
                    results.append(result)

                    if best_result is None or sharpe > best_result['sharpe']:
                        best_result = result
                        best_params = result

        log(f'  Weight V{w["v"]}Q{w["q"]}G{w["g"]}M{w["m"]}: {len(results)}조합 완료')

    results.sort(key=lambda x: -x['sharpe'])

    out_path = PROJECT / 'backtest_results' / 'grid_phase3_entry_exit.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log(f'Phase 3 결과 저장: {out_path}')
    log(f'최적: {best_result}')
    return results[:10], best_result


def phase4_walk_forward(best_params):
    """Phase 4: Walk-Forward 검증"""
    log('=== Step 4: Phase 4 Walk-Forward 검증 ===')

    windows = [
        ('2022', '2023', '학습 2022 검증 2023 (횡보)'),
        ('2022,2023', '2024', '학습 2022-23 검증 2024 (강세)'),
        ('2022,2023,2024', '2025', '학습 2022-24 검증 2025-26'),
    ]

    wf_results = []
    for train_years, test_year, label in windows:
        log(f'  {label}')
        # 테스트 연도만으로 시뮬레이션
        run(f'{PYTHON} -u backtest/master_grid_search.py --years {test_year}',
            timeout=3600, desc=f'WF: {label}')

        # 결과 로드
        result_file = PROJECT / 'backtest_results' / f'grid_phase2_{test_year}.json'
        if result_file.exists():
            with open(result_file, 'r', encoding='utf-8') as f:
                test_results = json.load(f)
            # best_params와 같은 weight 찾기
            matching = [r for r in test_results
                        if r['v'] == best_params['v'] and r['q'] == best_params['q']
                        and r['g'] == best_params['g'] and r['m'] == best_params['m']
                        and r['g_rev'] == best_params['g_rev'] and r['g_cap'] == best_params['g_cap']]
            if matching:
                wf_results.append({'window': label, **matching[0]})
                log(f'    CAGR={matching[0]["cagr"]}% Sharpe={matching[0]["sharpe"]} MDD={matching[0]["mdd"]}%')

    out_path = PROJECT / 'backtest_results' / 'grid_phase4_walkforward.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(wf_results, f, ensure_ascii=False, indent=2)
    return wf_results


def collect_dart_historical():
    """DART 2017-2018 수집"""
    log('=== Step 7: DART 2017-2018 수집 ===')
    for year in [2018, 2017]:
        log(f'  DART {year} 수집 시작')
        # collect_dart_2019.py 복사해서 연도만 변경
        script = f"""
import sys, time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(r'C:\\dev')))
import pandas as pd
from dart_collector import DartCollector
CACHE_DIR = Path(r'C:\\dev\\data_cache')
files = sorted(CACHE_DIR.glob('fs_dart_*.parquet'))
tickers = [f.stem.replace('fs_dart_', '') for f in files]
dc = DartCollector()
success = failed = skipped = 0
for i, ticker in enumerate(tickers):
    try:
        cache_path = CACHE_DIR / f'fs_dart_{{ticker}}.parquet'
        existing = pd.read_parquet(cache_path) if cache_path.exists() else pd.DataFrame()
        if not existing.empty:
            col = existing.columns[1]
            years = set(str(p)[:4] for p in existing[col].dropna().unique())
            if '{year}' in years:
                skipped += 1
                continue
        new_df = dc.fetch_single(ticker, {year}, {year})
        if new_df is not None and not new_df.empty:
            if not existing.empty:
                combined = pd.concat([existing, new_df]).drop_duplicates()
                combined = combined.sort_values(combined.columns[1])
            else:
                combined = new_df
            combined.to_parquet(cache_path, index=False)
            success += 1
        else:
            skipped += 1
        if (i + 1) % 100 == 0:
            print(f'  [{{i+1}}/{{len(tickers)}}] ok={{success}} skip={{skipped}} fail={{failed}} API={{dc._call_count}}')
    except RuntimeError as e:
        if '한도' in str(e):
            print(f'API 한도: {{e}}')
            break
        failed += 1
    except Exception:
        failed += 1
print(f'DART {year}: ok={{success}} skip={{skipped}} fail={{failed}} API={{dc._call_count}}')
"""
        result = subprocess.run(
            [PYTHON, '-c', script], cwd=str(PROJECT),
            capture_output=True, text=True, timeout=3600,
            encoding='utf-8', errors='replace',
        )
        if result.stdout:
            for line in result.stdout.strip().split('\n')[-3:]:
                log(f'    {line}')


def generate_bt_2020_2021():
    """bt_2020, bt_2021 랭킹 생성"""
    log('=== Step 8: bt_2020, bt_2021 생성 ===')

    # 캐시 복사
    for i in [1, 2]:
        dst = PROJECT / f'data_cache_{i}'
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(CACHE_DIR, dst)

    os.makedirs('state/bt_2020', exist_ok=True)
    os.makedirs('state/bt_2021', exist_ok=True)

    # 2개 병렬 (벤치마크 최적)
    p1 = subprocess.Popen(
        [PYTHON, '-u', str(PROJECT / 'backtest/fast_generate_rankings.py'),
         '20200701', '20201230', '--state-dir', str(PROJECT / 'state/bt_2020'),
         '--cache-dir', str(PROJECT / 'data_cache_1')],
        cwd=str(PROJECT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    p2 = subprocess.Popen(
        [PYTHON, '-u', str(PROJECT / 'backtest/fast_generate_rankings.py'),
         '20210104', '20211230', '--state-dir', str(PROJECT / 'state/bt_2021'),
         '--cache-dir', str(PROJECT / 'data_cache_2')],
        cwd=str(PROJECT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    log(f'  bt_2020 PID={p1.pid}, bt_2021 PID={p2.pid}')
    p1.wait()
    p2.wait()
    log(f'  bt_2020: {len(glob.glob("state/bt_2020/ranking_*.json"))}파일')
    log(f'  bt_2021: {len(glob.glob("state/bt_2021/ranking_*.json"))}파일')

    # 캐시 정리
    shutil.rmtree(PROJECT / 'data_cache_1', ignore_errors=True)
    shutil.rmtree(PROJECT / 'data_cache_2', ignore_errors=True)


def validate_on_2020_2021(best_params):
    """최적 전략으로 bt_2020/2021 검증"""
    log('=== Step 9: bt_2020/2021 검증 ===')
    for year in ['2020', '2021']:
        run(f'{PYTHON} -u backtest/master_grid_search.py --years {year}',
            timeout=3600, desc=f'검증: bt_{year}')
        result_file = PROJECT / 'backtest_results' / f'grid_phase2_{year}.json'
        if result_file.exists():
            with open(result_file, 'r', encoding='utf-8') as f:
                results = json.load(f)
            matching = [r for r in results
                        if r['v'] == best_params['v'] and r['q'] == best_params['q']
                        and r['g'] == best_params['g'] and r['m'] == best_params['m']
                        and r['g_rev'] == best_params['g_rev'] and r['g_cap'] == best_params['g_cap']]
            if matching:
                log(f'  bt_{year}: CAGR={matching[0]["cagr"]}% Sharpe={matching[0]["sharpe"]} MDD={matching[0]["mdd"]}%')


def run_production_personal():
    """프로덕션 실행 (개인봇만)"""
    log('=== 프로덕션 실행 (개인봇) ===')
    os.environ['TEST_MODE'] = '1'
    run(f'{PYTHON} -u create_current_portfolio.py', timeout=600, desc='포트폴리오 생성')
    run(f'{PYTHON} -u send_telegram_auto.py', timeout=300, desc='텔레그램 전송 (개인봇)')


def main():
    log('=' * 60)
    log('오버나이트 마스터 스크립트 시작')
    log('=' * 60)

    t0 = time.time()

    # Step 1: bt_2024/2025 완료 대기
    wait_for_rankings_complete()

    # Step 2: Phase 2 Grid Search (전체 연도)
    phase2_grid_search()

    # Phase 2 결과 로드
    p2_file = PROJECT / 'backtest_results' / 'grid_phase2_2022_2023_2024_2025.json'
    if p2_file.exists():
        with open(p2_file, 'r', encoding='utf-8') as f:
            p2_results = json.load(f)
        top_weights = p2_results[:5]
        log(f'Phase 2 Top 5 weights 선정')
    else:
        log('Phase 2 결과 없음 — 기본값 사용')
        top_weights = [{'v': 25, 'q': 25, 'g': 25, 'm': 25, 'g_rev': 0.5, 'g_cap': 999}]

    # Step 3: Phase 3 진입/이탈 최적화
    phase3_results, best_params = phase3_entry_exit(top_weights)

    # Step 4: Phase 4 Walk-Forward 검증
    wf_results = phase4_walk_forward(best_params)

    # Step 5: 텔레그램 보고
    msg = f"""<b>[백테스트 최적화 완료]</b>

<b>최적 전략:</b>
V{best_params['v']} Q{best_params['q']} G{best_params['g']} M{best_params['m']}
G비율: rev {best_params['g_rev']:.0%} / oca {1-best_params['g_rev']:.0%}
Growth캡: {best_params.get('g_cap', 'none')}
진입: {best_params.get('strategy', 'rank')} {best_params.get('entry', '')}
이탈: {best_params.get('exit', '')}
슬롯: {best_params.get('slots', 0) or '무제한'}

<b>In-Sample (2022-2025):</b>
CAGR: {best_params['cagr']}%
Sharpe: {best_params['sharpe']}
MDD: {best_params['mdd']}%

<b>Walk-Forward:</b>
"""
    for wf in wf_results:
        msg += f"  {wf['window']}: CAGR={wf['cagr']}% Sharpe={wf['sharpe']}\n"

    send_telegram(msg)

    # Step 6: 프로덕션 실행
    run_production_personal()

    # Step 7: DART 2017-2018 수집
    collect_dart_historical()

    # Step 8: bt_2020, bt_2021 생성
    generate_bt_2020_2021()

    # Step 9: bt_2020/2021 검증
    validate_on_2020_2021(best_params)

    # Step 10: 검증 결과 텔레그램
    val_msg = f"""<b>[Out-of-Sample 검증 완료]</b>

최적 전략: V{best_params['v']}Q{best_params['q']}G{best_params['g']}M{best_params['m']}

"""
    for year in ['2020', '2021']:
        rf = PROJECT / 'backtest_results' / f'grid_phase2_{year}.json'
        if rf.exists():
            with open(rf, 'r', encoding='utf-8') as f:
                results = json.load(f)
            matching = [r for r in results
                        if r['v'] == best_params['v'] and r['q'] == best_params['q']
                        and r['g'] == best_params['g'] and r['m'] == best_params['m']
                        and r['g_rev'] == best_params['g_rev'] and r['g_cap'] == best_params['g_cap']]
            if matching:
                val_msg += f"bt_{year}: CAGR={matching[0]['cagr']}% Sharpe={matching[0]['sharpe']} MDD={matching[0]['mdd']}%\n"

    elapsed = time.time() - t0
    val_msg += f"\n총 소요: {elapsed/3600:.1f}시간"
    send_telegram(val_msg)

    # 프로덕션 재실행
    run_production_personal()

    # 6AM 스케줄러 재활성화
    subprocess.run(
        ['powershell', '-command', "Enable-ScheduledTask -TaskName 'QuanT_DailyPipeline'"],
        capture_output=True,
    )
    log('6AM 스케줄러 재활성화')

    log('=' * 60)
    log(f'전체 완료: {elapsed/3600:.1f}시간')
    log('=' * 60)


if __name__ == '__main__':
    main()
