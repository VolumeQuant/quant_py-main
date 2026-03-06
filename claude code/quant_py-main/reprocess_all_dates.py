"""
모든 과거 날짜를 현재 전략으로 재계산

- 각 날짜에 대해 create_current_portfolio.py 실행
- CONSENSUS_FROM_JSON=1 → FnGuide 크롤링 대신 기존 ranking JSON에서 Forward PER 사용
- pykrx 과거 데이터 + FnGuide 캐시로 팩터 점수 전부 재계산
"""

import subprocess
import sys
import io
import json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

STATE_DIR = Path(__file__).parent / 'state'
PYTHON = sys.executable
SCRIPT = str(Path(__file__).parent / 'create_current_portfolio.py')


def get_all_dates():
    """기존 ranking JSON 날짜 목록 (오래된 순)"""
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    dates = []
    for f in files:
        date_str = f.stem.replace('ranking_', '')
        if len(date_str) == 8 and date_str.isdigit():
            dates.append(date_str)
    return dates


def main():
    dates = get_all_dates()
    print(f"재계산 대상: {len(dates)}개 날짜")
    for d in dates:
        print(f"  {d}")

    print(f"\n{'='*50}")

    success = 0
    failed = []

    for i, date_str in enumerate(dates):
        print(f"\n[{i+1}/{len(dates)}] {date_str} 재계산 시작...")
        print("-" * 40)

        try:
            import os
            env = os.environ.copy()
            env['CONSENSUS_FROM_JSON'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'
            result = subprocess.run(
                [PYTHON, SCRIPT, date_str],
                cwd=str(Path(__file__).parent),
                env=env,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=600,
            )

            # 마지막 20줄만 출력
            lines = result.stdout.strip().split('\n')
            for line in lines[-20:]:
                print(f"  {line}")

            if result.returncode != 0:
                print(f"  [ERROR] returncode={result.returncode}")
                if result.stderr:
                    for line in result.stderr.strip().split('\n')[-10:]:
                        print(f"  STDERR: {line}")
                failed.append(date_str)
            else:
                success += 1
                # 결과 확인
                ranking_file = STATE_DIR / f'ranking_{date_str}.json'
                if ranking_file.exists():
                    with open(ranking_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    count = len(data.get('rankings', []))
                    print(f"  -> ranking_{date_str}.json: {count}개 종목")

        except subprocess.TimeoutExpired:
            print(f"  [TIMEOUT] 10분 초과")
            failed.append(date_str)
        except Exception as e:
            print(f"  [EXCEPTION] {e}")
            failed.append(date_str)

    print(f"\n{'='*50}")
    print(f"완료: {success}/{len(dates)} 성공")
    if failed:
        print(f"실패: {failed}")

    # 최종 검증: 삼성전자
    print(f"\n[검증] 삼성전자(005930):")
    for d in dates:
        ranking_file = STATE_DIR / f'ranking_{d}.json'
        if ranking_file.exists():
            with open(ranking_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for s in data.get('rankings', []):
                if s.get('ticker') == '005930':
                    print(f"  {d}: comp={s['composite_rank']}, rank={s['rank']}, "
                          f"score={s.get('score', 0):.4f}, G={s.get('growth_s', 0):.3f}, "
                          f"fwd_per={s.get('fwd_per')}")
                    break


if __name__ == '__main__':
    main()
