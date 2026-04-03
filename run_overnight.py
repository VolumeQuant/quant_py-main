"""야간 자동 파이프라인 — bt 완료 대기 → Grid Search → 프로덕션 적용

12시간 내 전체 완료 목표:
1. bt_2021 + bt_2025 재생성 완료 대기 (검증)
2. Grid Search (Phase 1 + 1b + 2)
3. 프로덕션 ranking 전체 재생성 (create_current_portfolio.py)
4. 텔레그램 최종 보고
"""
import sys
import os
import json
import glob
import time
import subprocess
import re
import requests
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent
sys.path.insert(0, str(PROJECT))

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

PYTHON = r'C:\Users\user\miniconda3\envs\volumequant\python.exe'


def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            'chat_id': TELEGRAM_PRIVATE_ID,
            'text': msg,
            'parse_mode': 'HTML',
        }, timeout=30)
        print(f'[TG] 전송 완료')
    except Exception as e:
        print(f'[TG] 전송 실패: {e}')


def check_bt_complete():
    cutoff = datetime(2026, 4, 2, 14, 0).timestamp()
    issues = []
    for bt in ['bt_2021', 'bt_2022', 'bt_2023', 'bt_2024', 'bt_2025']:
        files = sorted(glob.glob(str(PROJECT / f'state/{bt}/ranking_*.json')))
        total = len(files)
        new = len([f for f in files if os.path.getmtime(f) >= cutoff])
        if new < total:
            issues.append(f'{bt}: {new}/{total} ({total - new}개 미완)')
    return issues


def validate_bt_samples():
    issues = []
    for bt in ['bt_2021', 'bt_2022', 'bt_2023', 'bt_2024', 'bt_2025']:
        files = sorted(glob.glob(str(PROJECT / f'state/{bt}/ranking_*.json')))
        if not files:
            issues.append(f'{bt}: 파일 없음')
            continue
        samples = [files[0], files[len(files)//2], files[-1]]
        for f in samples:
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            rankings = data.get('rankings', data) if isinstance(data, dict) else data
            if not rankings:
                issues.append(f'{os.path.basename(f)}: 빈 파일')
                continue
            total = len(rankings)
            g_zero = sum(1 for r in rankings if r.get('growth_s', 0) == 0.0)
            if total < 50:
                issues.append(f'{os.path.basename(f)}: 종목수 {total}')
            if g_zero > total * 0.8:
                issues.append(f'{os.path.basename(f)}: Growth=0 {g_zero}/{total}')
    return issues


def wait_for_bt():
    print('=== Phase 0: bt 재생성 완료 대기 ===')
    max_wait = 180
    waited = 0
    while waited < max_wait:
        issues = check_bt_complete()
        if not issues:
            print('bt 재생성 완료!')
            break
        print(f'  대기 중... {", ".join(issues)}')
        time.sleep(60)
        waited += 1
    else:
        send_telegram(f'⚠️ bt 재생성 3시간 초과! {issues}')
        return False

    val_issues = validate_bt_samples()
    if val_issues:
        msg = '⚠️ bt 검증 실패:\n' + '\n'.join(val_issues)
        print(msg)
        send_telegram(msg)
        return False

    print('bt 검증 통과')
    send_telegram('✅ bt_2021~2025 재생성 + 검증 완료. Grid Search 시작.')
    return True


def run_grid_search():
    print('\n=== Grid Search 실행 ===')
    t0 = time.time()
    result = subprocess.run(
        [PYTHON, 'backtest/full_grid_search.py'],
        cwd=str(PROJECT),
        timeout=36000,
    )
    elapsed = time.time() - t0
    if result.returncode != 0:
        send_telegram(f'❌ Grid Search 실패 (exit={result.returncode}, {elapsed/60:.0f}분)')
        return False
    print(f'Grid Search 완료: {elapsed/60:.0f}분')
    return True


def apply_production():
    print('\n=== Phase 3: 프로덕션 적용 ===')

    result_file = PROJECT / 'backtest_results' / 'full_final_result.json'
    if not result_file.exists():
        send_telegram('❌ Grid Search 결과 파일 없음')
        return False

    with open(result_file, 'r', encoding='utf-8') as f:
        result = json.load(f)

    best = result['best_strategy']
    adj_sharpe = result.get('adjusted_sharpe', 0)

    if adj_sharpe < 0.3:
        msg = (f'⚠️ 조정 Sharpe={adj_sharpe:.3f} (< 0.3). '
               f'과적합 가능성. 프로덕션 적용 보류.\n'
               f'V{best["v"]}Q{best["q"]}G{best["g"]}M{best["m"]}')
        send_telegram(msg)
        return False

    # strategy_b 가중치 업데이트
    strat_file = PROJECT / 'strategy_b_multifactor.py'
    content = strat_file.read_text(encoding='utf-8')

    content = re.sub(
        r'V_W, Q_W, G_W, M_W = [\d.]+, [\d.]+, [\d.]+, [\d.]+',
        f'V_W, Q_W, G_W, M_W = {best["v"]/100}, {best["q"]/100}, {best["g"]/100}, {best["m"]/100}',
        content
    )
    content = re.sub(
        r"G_REVENUE_WEIGHT', '[0-9.]+'",
        f"G_REVENUE_WEIGHT', '{best['g_rev']}'",
        content
    )
    strat_file.write_text(content, encoding='utf-8')
    print(f'strategy_b 업데이트: V{best["v"]}Q{best["q"]}G{best["g"]}M{best["m"]} Grev={best["g_rev"]}')

    # 프로덕션 ranking 전체 재생성
    prod_files = sorted(glob.glob(str(PROJECT / 'state/ranking_*.json')))
    if prod_files:
        print(f'프로덕션 ranking {len(prod_files)}일 재생성...')
        for i, f in enumerate(prod_files):
            date_str = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            r = subprocess.run(
                [PYTHON, 'create_current_portfolio.py', '--date', date_str],
                cwd=str(PROJECT), capture_output=True, timeout=120, encoding='utf-8',
            )
            if r.returncode != 0:
                print(f'  {date_str} 실패: {(r.stderr or "")[:100]}')
            if (i + 1) % 10 == 0:
                print(f'  [{i+1}/{len(prod_files)}]')
        print(f'프로덕션 재생성 완료')

    # 최종 보고
    wf_summary = '\n'.join(
        f"  {w['window']}: CAGR={w['cagr']:.1f}% Sharpe={w['sharpe']:.3f}"
        for w in result.get('walk_forward', [])
    )
    send_telegram(
        f"<b>🎯 전체 완료</b>\n\n"
        f"<b>최적 전략:</b>\n"
        f"V{best['v']} Q{best['q']} G{best['g']} M{best['m']}\n"
        f"G비율: {best['g_rev']}\n"
        f"진입: rank ≤ {best['entry']} | 이탈: rank > {best['exit']} | 슬롯: {best['slots']}\n\n"
        f"<b>성과:</b>\n"
        f"CAGR: {best['cagr']:.1f}% | Sharpe: {best['sharpe']:.3f} (조정: {adj_sharpe:.3f})\n"
        f"MDD: {best['mdd']:.1f}% | Alpha: {best['alpha']:+.1f}%\n\n"
        f"<b>Walk-Forward:</b>\n{wf_summary}\n\n"
        f"✅ 프로덕션 적용 완료"
    )
    return True


def main():
    t_start = time.time()
    print(f'=== 야간 파이프라인 시작: {datetime.now().strftime("%H:%M:%S")} ===')
    send_telegram('🌙 야간 파이프라인 시작')

    if not wait_for_bt():
        return
    if not run_grid_search():
        return
    apply_production()

    total = time.time() - t_start
    print(f'\n=== 전체 완료: {total/60:.0f}분 ({total/3600:.1f}시간) ===')


if __name__ == '__main__':
    main()
