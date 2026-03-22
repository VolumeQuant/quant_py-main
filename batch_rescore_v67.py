"""
v67 재스코어링 — Growth 팩터(전년동기 G3) 로직 변경분만 재계산
- OHLCV 캐시: 그대로 유지
- FnGuide 캐시: yoy_q 레코드 이미 포함 상태
- Forward PER: 기존 ranking JSON에서 로드 (CONSENSUS_FROM_JSON=1)
"""
import sys, io, os, json, shutil, subprocess, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from pathlib import Path
from datetime import datetime

PYTHON = sys.executable
SCRIPT_DIR = Path(__file__).parent
STATE_DIR = SCRIPT_DIR / 'state'
BACKUP_DIR = STATE_DIR / '_v66_backup'

def main():
    start_time = datetime.now()

    # 1. 재계산 대상 날짜
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    dates = [f.stem.split('_')[1] for f in files]
    print(f"재스코어링 대상: {len(dates)}일 ({dates[0]} ~ {dates[-1]})")

    # 2. 원본 백업
    BACKUP_DIR.mkdir(exist_ok=True)
    backed_up = 0
    for f in files:
        dest = BACKUP_DIR / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
            backed_up += 1
    print(f"v66 원본 백업: {backed_up}개 → {BACKUP_DIR}")

    # 3. 원본 요약 저장
    original = {}
    for d in dates:
        data = json.loads((STATE_DIR / f'ranking_{d}.json').read_text(encoding='utf-8'))
        rankings = sorted(data['rankings'], key=lambda x: x['rank'])
        original[d] = {
            'scored': len(rankings),
            'top5': [(r['name'], r['rank']) for r in rankings[:5]],
        }

    # 4. 날짜별 파이프라인 실행
    print(f"\n{'='*60}")
    results = {}
    failed = []

    for i, d in enumerate(dates):
        print(f"[{i+1}/{len(dates)}] {d} ...", end=' ', flush=True)

        env = os.environ.copy()
        env['CONSENSUS_FROM_JSON'] = '1'

        try:
            result = subprocess.run(
                [PYTHON, 'create_current_portfolio.py', d],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                cwd=str(SCRIPT_DIR), env=env, timeout=600
            )

            ranking_file = STATE_DIR / f'ranking_{d}.json'
            if ranking_file.exists():
                data = json.loads(ranking_file.read_text(encoding='utf-8'))
                rankings = sorted(data['rankings'], key=lambda x: x['rank'])
                scored = len(rankings)
                top3 = [r['name'] for r in rankings[:3]]
                results[d] = {'scored': scored, 'top3': top3}

                orig_scored = original[d]['scored']
                print(f"scored {orig_scored}→{scored}, Top3: {', '.join(top3)}")
            else:
                print("FAIL (no output)")
                failed.append(d)

        except subprocess.TimeoutExpired:
            print("TIMEOUT")
            failed.append(d)
        except Exception as e:
            print(f"ERROR: {e}")
            failed.append(d)

        # 진행률
        elapsed = (datetime.now() - start_time).total_seconds()
        if i > 0:
            avg = elapsed / (i + 1)
            remain = avg * (len(dates) - i - 1)
            print(f"  경과 {elapsed/60:.1f}분, 잔여 ~{remain/60:.1f}분")

    # 5. 비교 결과
    print(f"\n{'='*60}")
    print("v66 → v67 비교")
    print(f"{'='*60}")
    print(f"{'날짜':>10s} {'v66_scored':>10s} {'v67_scored':>10s} {'v66_top3':<40s} {'v67_top3':<40s}")

    for d in dates:
        orig = original[d]
        new = results.get(d)
        if not new:
            print(f"{d:>10s} {'FAIL':>10s}")
            continue

        v66_top3 = ', '.join(n for n, _ in orig['top5'][:3])
        v67_top3 = ', '.join(new['top3'])
        changed = '***' if v66_top3 != v67_top3 else ''
        print(f"{d:>10s} {orig['scored']:>10d} {new['scored']:>10d} {v66_top3:<40s} {v67_top3:<40s} {changed}")

    total = (datetime.now() - start_time).total_seconds()
    print(f"\n총 소요: {total/60:.1f}분")
    print(f"성공: {len(results)}/{len(dates)}, 실패: {len(failed)}")
    if failed:
        print(f"실패 날짜: {failed}")

if __name__ == '__main__':
    main()
