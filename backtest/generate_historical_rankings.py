"""과거 날짜별 ranking JSON 일괄 생성 (백테스트용)

create_current_portfolio.py를 날짜별로 호출하여 state/ranking_YYYYMMDD.json 생성.
FnGuide 컨센서스(fwd_per)는 과거 조회 불가 → CONSENSUS_FROM_JSON=1로 스킵.
날짜순 처리로 3일 교집합 가중순위가 자동 누적.

Usage:
    python backtest/generate_historical_rankings.py                    # 전체 가능 기간
    python backtest/generate_historical_rankings.py 20250701 20251231  # 기간 지정
    python backtest/generate_historical_rankings.py --resume           # 중단 지점부터 재개
"""
import sys
import os
import json
import time
import subprocess
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
STATE_DIR = PROJECT_ROOT / 'state'
CACHE_DIR = PROJECT_ROOT / 'data_cache'
PYTHON = sys.executable  # 현재 Python 인터프리터

# MA120(120) + 6M모멘텀(126) → 최소 130거래일 필요
MIN_HISTORY_DAYS = 130


def get_existing_ranking_dates():
    """이미 생성된 ranking 날짜 set"""
    dates = set()
    for f in STATE_DIR.glob('ranking_*.json'):
        d = f.stem.replace('ranking_', '')
        if len(d) == 8 and d.isdigit():
            dates.add(d)
    return dates


def get_target_dates(start_arg=None, end_arg=None):
    """생성 가능한 거래일 목록 (OHLCV 기준)"""
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    if not ohlcv_files:
        print('OHLCV 파일 없음')
        return []

    ohlcv_df = pd.read_parquet(ohlcv_files[-1])
    all_dates = ohlcv_df.index

    # 최소 히스토리 이후부터 생성 가능
    earliest = all_dates[MIN_HISTORY_DAYS]
    latest = all_dates[-1]

    start = pd.Timestamp(start_arg) if start_arg else earliest
    end = pd.Timestamp(end_arg) if end_arg else latest

    target = all_dates[(all_dates >= start) & (all_dates <= end)]
    return [d.strftime('%Y%m%d') for d in target]


def run_pipeline_for_date(date_str):
    """create_current_portfolio.py를 특정 날짜로 실행

    CONSENSUS_FROM_JSON=1: FnGuide 컨센서스 크롤링 스킵
    반환: (success: bool, elapsed_sec: float)
    """
    env = os.environ.copy()
    env['CONSENSUS_FROM_JSON'] = '1'
    env['DISABLE_FWD_BONUS'] = '1'  # 과거 컨센서스 없음 → FWD_PER 보너스 비활성화

    script = str(PROJECT_ROOT / 'create_current_portfolio.py')

    t0 = time.time()
    try:
        result = subprocess.run(
            [PYTHON, script, date_str],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300,  # 5분 타임아웃
        )
        elapsed = time.time() - t0

        # ranking JSON 생성 확인
        ranking_path = STATE_DIR / f'ranking_{date_str}.json'
        if ranking_path.exists():
            # 종목 수 확인
            with open(ranking_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            n_stocks = len(data.get('rankings', []))
            return True, elapsed, n_stocks
        else:
            # 실패 로그
            if result.stderr:
                err_lines = result.stderr.strip().split('\n')
                last_err = err_lines[-1] if err_lines else 'unknown'
                print(f'    에러: {last_err[:100]}')
            return False, elapsed, 0

    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        print(f'    타임아웃 (5분)')
        return False, elapsed, 0
    except Exception as e:
        elapsed = time.time() - t0
        print(f'    예외: {e}')
        return False, elapsed, 0


def main():
    # 인자 파싱
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    start_arg = args[0] if len(args) >= 1 else None
    end_arg = args[1] if len(args) >= 2 else None

    # 대상 날짜
    all_target = get_target_dates(start_arg, end_arg)
    existing = get_existing_ranking_dates()

    # 이미 생성된 날짜 제외
    todo = [d for d in all_target if d not in existing]

    print(f'전체 가능: {len(all_target)}거래일')
    print(f'이미 생성: {len(existing)}일')
    print(f'생성 대상: {len(todo)}일')

    if not todo:
        print('생성할 날짜 없음')
        return

    print(f'기간: {todo[0]} ~ {todo[-1]}')
    print(f'예상 시간: {len(todo) * 1.5 / 60:.0f}~{len(todo) * 3 / 60:.0f}분')
    print()

    # 날짜순 처리 (3일 교집합 누적 위해)
    success_count = 0
    fail_count = 0
    total_elapsed = 0
    start_time = time.time()

    for idx, date_str in enumerate(todo):
        progress = f'[{idx + 1}/{len(todo)}]'

        ok, elapsed, n_stocks = run_pipeline_for_date(date_str)
        total_elapsed += elapsed

        if ok:
            success_count += 1
            avg = total_elapsed / (idx + 1)
            remaining = avg * (len(todo) - idx - 1) / 60
            print(f'{progress} {date_str}: {n_stocks}종목, {elapsed:.0f}초 (남은 ~{remaining:.0f}분)')
        else:
            fail_count += 1
            print(f'{progress} {date_str}: 실패 ({elapsed:.0f}초)')

    # 결과 요약
    wall_time = time.time() - start_time
    print(f'\n{"="*60}')
    print(f'완료: {success_count}성공 / {fail_count}실패 / {len(todo)}전체')
    print(f'소요: {wall_time/60:.1f}분 (평균 {total_elapsed/max(success_count,1):.1f}초/일)')
    print(f'ranking 파일: {len(get_existing_ranking_dates())}일')
    print(f'{"="*60}')


if __name__ == '__main__':
    main()
