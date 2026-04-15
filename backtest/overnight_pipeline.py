"""야간 자동 파이프라인 — 자정 후 DART 수집 → bt 재생성 → 그리드 서치 → 프로덕션 적용

자정(00:00 KST)에 DART API 한도 리셋을 기다린 후:
1. DART 2020~2026 재수집 (지배주주당기순이익/자본 포함)
2. bt_2020~2025 재생성
3. 그리드 서치 (전체/최근/국면별)
4. 최적 전략 프로덕션 적용
5. 결과 개인봇 전송
6. 06:00 스케줄러 전에 완료

Usage:
    python backtest/overnight_pipeline.py
"""
import sys
import os
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

KST = ZoneInfo('Asia/Seoul')
PYTHON = sys.executable
LOG_FILE = PROJECT_ROOT / 'backtest' / 'overnight_log.txt'


def log(msg):
    ts = datetime.now(KST).strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def wait_until_midnight():
    """자정(00:05 KST)까지 대기 — 5분 여유"""
    now = datetime.now(KST)
    if now.hour >= 0 and now.hour < 6:
        log('이미 자정 이후, 바로 시작')
        return

    tomorrow = now.replace(hour=0, minute=5, second=0, microsecond=0) + timedelta(days=1)
    wait_sec = (tomorrow - now).total_seconds()
    log(f'자정까지 {wait_sec/3600:.1f}시간 대기...')

    while datetime.now(KST) < tomorrow:
        time.sleep(60)


def test_api_available():
    """API 한도 리셋 확인"""
    log('API 한도 확인...')
    from dart_collector import DartCollector
    dc = DartCollector()
    try:
        df = dc.fetch_single('005930', 2025, 2025)
        if not df.empty:
            has_parent = '지배주주당기순이익' in df['계정'].values
            log(f'API 정상, 지배주주필드: {has_parent}')
            return True
        else:
            log('API 응답 비어있음')
            return False
    except Exception as e:
        log(f'API 에러: {e}')
        return False


def phase2_dart_collection():
    """Phase 2: DART 수집 — 2024~2025 먼저(프로덕션용) → 2020~2023(백테스트용)"""
    log('=== Phase 2: DART 수집 시작 ===')

    import pandas as pd
    from dart_collector import DartCollector

    cache_dir = PROJECT_ROOT / 'data_cache'
    dart_files = sorted(cache_dir.glob('fs_dart_*.parquet'))

    # 지배주주 필드 없는 종목 파악
    all_tickers = []
    for f in dart_files:
        ticker = f.stem.replace('fs_dart_', '')
        df = pd.read_parquet(f)
        if df.empty:
            continue
        has_parent_ni = '지배주주당기순이익' in df['계정'].values
        if not has_parent_ni:
            all_tickers.append(ticker)

    log(f'지배주주 필드 없는 종목: {len(all_tickers)}개')

    dc = DartCollector()
    success = fail = 0
    t0 = time.time()

    # 1차: 2024~2025 (프로덕션 + 최근 bt 우선)
    log(f'--- 1차: 2024~2025 수집 ---')
    for i, ticker in enumerate(all_tickers):
        try:
            df = dc.fetch_single(ticker, 2024, 2025)
            if not df.empty:
                dc.save_cache(ticker, df)
                success += 1
            else:
                fail += 1
        except RuntimeError as e:
            if '한도' in str(e):
                log(f'1차 한도 도달! API {dc._call_count}건')
                break
            fail += 1
        except Exception:
            fail += 1
        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            rem = elapsed / (i + 1) * (len(all_tickers) - i - 1) / 60
            log(f'  [{i+1}/{len(all_tickers)}] {success}ok {fail}fail | API {dc._call_count} | ~{rem:.0f}min')

    log(f'1차 완료: {success}ok {fail}fail | API {dc._call_count} | {(time.time()-t0)/60:.1f}min')

    # 표본 검증
    for ticker in ['005930', '124500', '000660']:
        f = cache_dir / f'fs_dart_{ticker}.parquet'
        if f.exists():
            df = pd.read_parquet(f)
            has = '지배주주당기순이익' in df['계정'].values
            log(f'  검증 {ticker}: 지배주주당기순이익={has}')

    # 2차: 2020~2023 (나머지 bt용)
    log(f'--- 2차: 2020~2023 수집 ---')
    success2 = fail2 = 0
    t1 = time.time()
    for i, ticker in enumerate(all_tickers):
        try:
            df = dc.fetch_single(ticker, 2020, 2023)
            if not df.empty:
                dc.save_cache(ticker, df)
                success2 += 1
            else:
                fail2 += 1
        except RuntimeError as e:
            if '한도' in str(e):
                log(f'2차 한도 도달! API {dc._call_count}건')
                log(f'2020~2023 부분 수집: {success2}ok — 내일 재실행 필요')
                break
            fail2 += 1
        except Exception:
            fail2 += 1
        if (i + 1) % 200 == 0:
            elapsed = time.time() - t1
            rem = elapsed / (i + 1) * (len(all_tickers) - i - 1) / 60
            log(f'  [{i+1}/{len(all_tickers)}] {success2}ok {fail2}fail | API {dc._call_count} | ~{rem:.0f}min')

    log(f'2차 완료: {success2}ok {fail2}fail | API {dc._call_count} | {(time.time()-t1)/60:.1f}min')


def phase3_bt_regeneration():
    """Phase 3: bt_2020~2025 재생성 — 3병렬로 최대 속도"""
    log('=== Phase 3: bt 재생성 시작 (3병렬) ===')

    # 1배치: bt_2024 + bt_2025 + bt_2023 (3병렬, 최근 우선)
    # 2배치: bt_2020 + bt_2021 + bt_2022 (3병렬)
    batches = [
        [('20240102', '20241230', 'state/bt_2024'),
         ('20250102', '20260320', 'state/bt_2025'),
         ('20230102', '20231228', 'state/bt_2023')],
        [('20200102', '20201230', 'state/bt_2020'),
         ('20210104', '20211230', 'state/bt_2021'),
         ('20220103', '20221229', 'state/bt_2022')],
    ]

    for batch_idx, batch in enumerate(batches):
        procs = []
        for start, end, state_dir in batch:
            log(f'  시작: {state_dir} ({start}~{end})')
            p = subprocess.Popen(
                [PYTHON, 'backtest/fast_generate_rankings.py', start, end, f'--state-dir={state_dir}'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=str(PROJECT_ROOT), encoding='utf-8'
            )
            procs.append((state_dir, p))

        for state_dir, p in procs:
            stdout, stderr = p.communicate()
            lines = stdout.strip().split('\n')
            result_line = [l for l in lines if '완료:' in l or '성공' in l]
            log(f'  완료: {state_dir} — {result_line[-1] if result_line else "OK"}')

    log('bt 재생성 완료')

    # 검증
    for yr in ['2020', '2021', '2022', '2023', '2024', '2025']:
        bt_dir = PROJECT_ROOT / 'state' / f'bt_{yr}'
        files = list(bt_dir.glob('ranking_*.json'))
        g0 = 0
        for f in files:
            r = json.load(open(f, encoding='utf-8'))
            rankings = r.get('rankings', [])
            if rankings and all(s.get('growth_s', 0) == 0 for s in rankings):
                g0 += 1
        log(f'  bt_{yr}: {len(files)}일, Growth=0: {g0}일')


def phase4_grid_search():
    """Phase 4: 그리드 서치"""
    log('=== Phase 4: 그리드 서치 시작 ===')

    result = subprocess.run(
        [PYTHON, 'backtest/full_grid_search_v2.py'],
        capture_output=True, text=True, encoding='utf-8',
        cwd=str(PROJECT_ROOT)
    )

    # 결과 파싱
    lines = result.stdout.strip().split('\n')
    # 최적 가중치 비교 부분 추출
    summary_start = None
    for i, l in enumerate(lines):
        if '최적 가중치 비교' in l:
            summary_start = i
            break

    if summary_start:
        summary = '\n'.join(lines[summary_start:])
        log(summary)
    else:
        log('그리드 서치 결과 파싱 실패')
        log('\n'.join(lines[-30:]))

    return result.stdout


def phase5_apply_and_notify(grid_result):
    """Phase 5: 최적 전략 적용 + 개인봇 전송"""
    log('=== Phase 5: 적용 + 전송 ===')

    # 그리드 서치 결과 로드
    results_file = PROJECT_ROOT / 'backtest' / 'grid_search_v2_results.json'
    if not results_file.exists():
        log('그리드 서치 결과 파일 없음!')
        return

    results = json.load(open(results_file, encoding='utf-8'))
    full_top = results.get('full', {}).get('phase1_top10', [])
    if not full_top:
        log('전체기간 Top 결과 없음!')
        return

    best = full_top[0]
    v_w = best['v_w']
    q_w = best['q_w']
    g_w = best['g_w']
    m_w = best['m_w']
    g_rev = best['g_rev']

    log(f'최적: V{v_w:.0%} Q{q_w:.0%} G{g_w:.0%} M{m_w:.0%} g_rev={g_rev}')
    log(f'  Sharpe={best["sharpe"]:.3f} CAGR={best["cagr"]:.1f}% MDD={best["mdd"]:.1f}%')

    # v72 성과도 확인
    v72 = None
    for r in results.get('full', {}).get('phase1_top10', []):
        pass  # top10에 v72가 없을 수 있음

    # strategy_b 가중치 변경
    strat_file = PROJECT_ROOT / 'strategy_b_multifactor.py'
    content = strat_file.read_text(encoding='utf-8')
    import re
    content = re.sub(
        r'V_W, Q_W, G_W, M_W = [\d.]+, [\d.]+, [\d.]+, [\d.]+',
        f'V_W, Q_W, G_W, M_W = {v_w}, {q_w}, {g_w}, {m_w}',
        content
    )
    content = re.sub(
        r"G_REVENUE_WEIGHT', '[\d.]+'",
        f"G_REVENUE_WEIGHT', '{g_rev}'",
        content
    )
    strat_file.write_text(content, encoding='utf-8')
    log(f'strategy_b 가중치 변경 완료')

    # 프로덕션 ranking reweight
    import numpy as np
    state_dir = PROJECT_ROOT / 'state'
    prod_files = sorted([f for f in state_dir.glob('ranking_*.json') if 'bt_' not in str(f)])

    for f in prod_files:
        r = json.load(open(f, encoding='utf-8'))
        rankings = r.get('rankings', [])
        if not rankings:
            continue

        g_raws = []
        for s in rankings:
            rev = s.get('rev_z', 0) or 0
            oca = s.get('oca_z', 0) or 0
            g_raws.append(g_rev * rev + (1 - g_rev) * oca)

        g_arr = np.array(g_raws)
        g_mean, g_std = g_arr.mean(), g_arr.std()
        g_std_arr = (g_arr - g_mean) / g_std if g_std > 0 else g_arr * 0

        for i, s in enumerate(rankings):
            v = s.get('value_s', 0) or 0
            q = s.get('quality_s', 0) or 0
            m = s.get('momentum_s', 0) or 0
            s['growth_s'] = round(float(g_std_arr[i]), 4)
            s['score'] = round(float(v_w * v + q_w * q + g_w * g_std_arr[i] + m_w * m), 4)

        rankings.sort(key=lambda x: -x['score'])
        for i, s in enumerate(rankings):
            s['rank'] = i + 1
            s['composite_rank'] = i + 1

        meta = r.get('metadata', {})
        meta['v_weight'] = v_w
        meta['q_weight'] = q_w
        meta['g_weight'] = g_w
        meta['m_weight'] = m_w
        meta['g_rev'] = g_rev

        with open(f, 'w', encoding='utf-8') as fp:
            json.dump(r, fp, ensure_ascii=False, indent=2)

    log(f'프로덕션 ranking {len(prod_files)}개 reweight 완료')

    # 개인봇 메시지 전송
    send_personal_bot_message(best, results)


def send_personal_bot_message(best, results):
    """개인봇에만 결과 요약 전송"""
    try:
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        TELEGRAM_BOT_TOKEN_PERSONAL = TELEGRAM_BOT_TOKEN
        TELEGRAM_CHAT_ID_PERSONAL = TELEGRAM_PRIVATE_ID
    except ImportError:
        log('텔레그램 설정 없음, 전송 스킵')
        return

    import requests

    msg = f"🔬 야간 파이프라인 완료\n\n"
    msg += f"최적 전략: V{best['v_w']:.0%} Q{best['q_w']:.0%} G{best['g_w']:.0%} M{best['m_w']:.0%}\n"
    msg += f"g_rev={best['g_rev']}\n\n"
    msg += f"전체 Sharpe={best['sharpe']:.3f}\n"
    msg += f"CAGR={best['cagr']:.1f}%\n"
    msg += f"MDD={best['mdd']:.1f}%\n\n"

    # 국면별 최적
    for period in ['full', 'recent', 'bull', 'bear', 'sideways']:
        data = results.get(period, {})
        top = data.get('phase1_top10', [])
        if top:
            t = top[0]
            msg += f"{period}: Sharpe {t['sharpe']:.3f} CAGR {t['cagr']:.1f}%\n"

    msg += f"\n프로덕션 적용 완료 ✅"
    msg += f"\n06:00 스케줄러 대기 중"

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN_PERSONAL}/sendMessage"
        resp = requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID_PERSONAL,
            'text': msg,
        }, timeout=30)
        log(f'개인봇 전송: {resp.status_code}')
    except Exception as e:
        log(f'개인봇 전송 실패: {e}')


def main():
    log('=' * 60)
    log('야간 파이프라인 시작')
    log('=' * 60)

    # 자정 대기
    wait_until_midnight()

    # API 확인
    for attempt in range(5):
        if test_api_available():
            break
        log(f'API 아직 안됨, 5분 대기 (시도 {attempt+1}/5)')
        time.sleep(300)
    else:
        log('API 사용 불가, 중단')
        return

    # Phase 2: DART 수집
    phase2_dart_collection()

    # Phase 3: bt 재생성
    phase3_bt_regeneration()

    # Phase 4: 그리드 서치
    grid_result = phase4_grid_search()

    # Phase 5: 적용 + 전송
    phase5_apply_and_notify(grid_result)

    log('=' * 60)
    log('야간 파이프라인 완료')
    log(f'현재 시간: {datetime.now(KST).strftime("%H:%M")}')
    log('=' * 60)

    # 07:30 스케줄러 실행 완료 대기 후 06:00 복원
    log('07:40까지 대기 (스케줄러 실행 완료 후 복원)')
    target = datetime.now(KST).replace(hour=7, minute=40, second=0, microsecond=0)
    if datetime.now(KST) >= target:
        # 이미 지남 → 즉시 복원
        pass
    else:
        while datetime.now(KST) < target:
            time.sleep(60)

    try:
        subprocess.run(['schtasks', '/change', '/tn', 'QuanT_DailyPipeline', '/st', '06:00'],
                       capture_output=True)
        log('스케줄러 06:00 복원 완료 ✅')
    except Exception as e:
        log(f'스케줄러 복원 실패: {e} — 수동 복원 필요')


if __name__ == '__main__':
    main()
