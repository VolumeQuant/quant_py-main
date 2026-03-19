"""
증분 방식 전체 재계산 스크립트
- 날짜별 유니버스로 OHLCV 증분 수집
- Forward PER은 기존 ranking JSON에서 로드 (CONSENSUS_FROM_JSON=1)
- forward-looking bias 없는 올바른 재계산
"""
import sys, io, os, json, shutil, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
from datetime import datetime

PYTHON = sys.executable
SCRIPT_DIR = Path(__file__).parent
STATE_DIR = SCRIPT_DIR / 'state'
CACHE_DIR = SCRIPT_DIR / 'data_cache'
OHLCV_BACKUP_DIR = CACHE_DIR / '_ohlcv_backup'

# 재계산 대상 날짜 (state/ 디렉토리에서 자동 탐지)
def get_ranking_dates():
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    return [f.stem.split('_')[1] for f in files]

def backup_ohlcv_cache():
    """기존 OHLCV 캐시 백업"""
    ohlcv_files = list(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    if not ohlcv_files:
        print("OHLCV 캐시 없음 - 백업 스킵")
        return

    OHLCV_BACKUP_DIR.mkdir(exist_ok=True)
    for f in ohlcv_files:
        dest = OHLCV_BACKUP_DIR / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
    print(f"OHLCV 캐시 백업: {len(ohlcv_files)}개 → {OHLCV_BACKUP_DIR}")

def clear_ohlcv_cache():
    """OHLCV 캐시 삭제 (빈 상태에서 증분 시작)"""
    ohlcv_files = list(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    # 개별 종목 캐시도 삭제 (get_ohlcv가 만든 파일)
    individual_files = list(CACHE_DIR.glob('ohlcv_*_*.parquet'))

    for f in ohlcv_files + individual_files:
        f.unlink()
    print(f"OHLCV 캐시 삭제: all_ohlcv {len(ohlcv_files)}개 + 개별 {len(individual_files)}개")

def restore_rankings_from_git():
    """git에서 원본 ranking 복원 (Forward PER fallback용)"""
    result = subprocess.run(
        ['git', 'checkout', 'HEAD', '--', 'claude code/quant_py-main/state/'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(SCRIPT_DIR.parent.parent)  # repo root
    )
    if result.returncode == 0:
        print("원본 ranking 복원 완료 (git checkout)")
    else:
        print(f"ranking 복원 실패: {result.stderr}")
        # 실패해도 계속 진행

def save_original_summary():
    """원본 ranking 요약 저장 (비교용)"""
    dates = get_ranking_dates()
    summary = {}
    for d in dates:
        f = STATE_DIR / f'ranking_{d}.json'
        data = json.loads(f.read_text(encoding='utf-8'))
        summary[d] = {
            'universe': data.get('metadata', {}).get('total_universe', 0),
            'scored': len(data['rankings']),
            'top5': [r['name'] for r in data['rankings'][:5]],
            'top5_tickers': [r['ticker'] for r in data['rankings'][:5]],
        }

    backup_file = CACHE_DIR / '_original_rankings_summary.json'
    backup_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"원본 요약 저장: {backup_file} ({len(summary)}일)")
    return summary

def run_pipeline_for_date(date_str, attempt=1):
    """특정 날짜에 대해 파이프라인 실행"""
    env = os.environ.copy()
    env['CONSENSUS_FROM_JSON'] = '1'

    result = subprocess.run(
        [PYTHON, 'create_current_portfolio.py', date_str],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(SCRIPT_DIR),
        env=env,
        timeout=600  # 10분 타임아웃
    )

    return result.returncode, result.stdout, result.stderr

def clean_intermediate_ohlcv():
    """중간 OHLCV 캐시 파일 정리 (최신 것만 유지)"""
    files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    if len(files) > 1:
        for f in files[:-1]:
            f.unlink()
        print(f"중간 OHLCV 캐시 정리: {len(files)-1}개 삭제, 최신 1개 유지")

def main():
    start_time = datetime.now()
    print("=" * 70)
    print("증분 방식 전체 재계산")
    print(f"시작: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 1. 원본 ranking 복원 (Forward PER 소스)
    print("\n[Step 1] 원본 ranking 복원")
    restore_rankings_from_git()

    # 2. 원본 요약 저장
    print("\n[Step 2] 원본 요약 저장")
    original_summary = save_original_summary()
    dates = sorted(original_summary.keys())
    print(f"재계산 대상: {len(dates)}일 ({dates[0]} ~ {dates[-1]})")

    # 3. OHLCV 캐시 백업 및 삭제
    print("\n[Step 3] OHLCV 캐시 백업 및 삭제")
    backup_ohlcv_cache()
    clear_ohlcv_cache()

    # 4. 날짜별 파이프라인 실행
    print("\n[Step 4] 날짜별 파이프라인 실행")
    results = {}
    failed_dates = []

    for i, date_str in enumerate(dates):
        print(f"\n{'='*50}")
        print(f"[{i+1}/{len(dates)}] {date_str} 처리 중...")
        print(f"{'='*50}")

        max_retries = 3
        success = False

        for attempt in range(1, max_retries + 1):
            try:
                returncode, stdout, stderr = run_pipeline_for_date(date_str, attempt)

                # 결과 확인
                ranking_file = STATE_DIR / f'ranking_{date_str}.json'
                if ranking_file.exists():
                    data = json.loads(ranking_file.read_text(encoding='utf-8'))
                    scored = len(data['rankings'])
                    universe = data.get('metadata', {}).get('total_universe', 0)
                    top3 = [r['name'] for r in data['rankings'][:3]]

                    results[date_str] = {
                        'universe': universe,
                        'scored': scored,
                        'top5': [r['name'] for r in data['rankings'][:5]],
                        'returncode': returncode,
                    }

                    orig = original_summary.get(date_str, {})
                    print(f"  완료: uni {orig.get('universe','?')}→{universe}, "
                          f"scored {orig.get('scored','?')}→{scored}, "
                          f"Top3: {', '.join(top3)}")
                    success = True
                    break
                else:
                    print(f"  경고: ranking 파일 미생성 (attempt {attempt})")
                    if stderr:
                        # 핵심 에러만 출력
                        err_lines = [l for l in stderr.split('\n') if 'Error' in l or 'error' in l]
                        for l in err_lines[:3]:
                            print(f"    {l.strip()}")

            except subprocess.TimeoutExpired:
                print(f"  타임아웃 (attempt {attempt})")
            except Exception as e:
                print(f"  에러: {e} (attempt {attempt})")

            if attempt < max_retries:
                wait = attempt * 10
                print(f"  {wait}초 후 재시도...")
                time.sleep(wait)

        if not success:
            print(f"  ❌ {date_str} 실패 (3회 재시도 후)")
            failed_dates.append(date_str)

        # 진행률
        elapsed = (datetime.now() - start_time).total_seconds()
        if i > 0:
            avg_per_date = elapsed / (i + 1)
            remaining = avg_per_date * (len(dates) - i - 1)
            print(f"  경과: {elapsed/60:.1f}분, 예상 잔여: {remaining/60:.1f}분")

    # 5. 중간 OHLCV 캐시 정리
    print("\n[Step 5] 중간 캐시 정리")
    clean_intermediate_ohlcv()

    # 6. 결과 비교
    print("\n" + "=" * 70)
    print("재계산 결과 비교")
    print("=" * 70)

    print(f"\n{'날짜':>10} | {'원본uni':>7} {'→':>1} {'신규uni':>7} | "
          f"{'원본scr':>7} {'→':>1} {'신규scr':>7} | {'Top5 변경':>8}")
    print("-" * 75)

    changed_count = 0
    for d in dates:
        orig = original_summary.get(d, {})
        new = results.get(d, {})

        if not new:
            print(f"{d:>10} | {'실패':>17} |")
            continue

        top5_changed = orig.get('top5', []) != new.get('top5', [])
        if top5_changed:
            changed_count += 1
        mark = 'CHANGED' if top5_changed else 'same'

        print(f"{d:>10} | {orig.get('universe','?'):>7} → {new['universe']:>7} | "
              f"{orig.get('scored','?'):>7} → {new['scored']:>7} | {mark:>8}")

    # 7. 요약
    total_time = (datetime.now() - start_time).total_seconds()
    print(f"\n총 소요: {total_time/60:.1f}분")
    print(f"성공: {len(results)}/{len(dates)}")
    print(f"실패: {len(failed_dates)} ({', '.join(failed_dates) if failed_dates else '없음'})")
    print(f"Top 5 변경: {changed_count}/{len(dates)}")

    # 결과 저장
    comparison_file = CACHE_DIR / '_recalc_comparison.json'
    comparison = {
        'timestamp': datetime.now().isoformat(),
        'total_time_sec': total_time,
        'original': original_summary,
        'recalculated': results,
        'failed': failed_dates,
    }
    comparison_file.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n비교 결과 저장: {comparison_file}")

    return len(failed_dates) == 0

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
