"""state ↔ state_new swap (옵션F production 적용).

기존 state/ 는 이미 state_backup_pre_optf_20260512/ 로 백업됨.
이 스크립트는:
1. state/의 모든 ranking_*.json 삭제 (regime_state.json은 보존)
2. state_new/의 모든 ranking_*.json → state/로 이동
3. state_new/defense/* → state/defense/로 이동
4. state_new/ 디렉토리 정리
5. regime_state.json은 그대로 유지 (옵션F 영향 없음)
"""
import sys, shutil
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent
OLD = PROJECT / 'state'
NEW = PROJECT / 'state_new'


def clear_ranking_files(d):
    if not d.exists(): return 0
    count = 0
    for fp in d.glob('ranking_*.json'):
        if len(fp.stem.replace('ranking_', '')) == 8:
            fp.unlink()
            count += 1
    return count


def move_ranking_files(src, dst):
    if not src.exists(): return 0
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for fp in src.glob('ranking_*.json'):
        if len(fp.stem.replace('ranking_', '')) == 8:
            shutil.move(str(fp), str(dst / fp.name))
            count += 1
    return count


def main():
    print('=== state ↔ state_new swap ===')

    # 1. state/ ranking 삭제
    n = clear_ranking_files(OLD)
    print(f'  state/ 기존 ranking 삭제: {n}개')
    n = clear_ranking_files(OLD / 'defense')
    print(f'  state/defense/ 기존 ranking 삭제: {n}개')

    # 2. state_new/ → state/ 이동
    n = move_ranking_files(NEW, OLD)
    print(f'  state_new/ → state/: {n}개 이동')
    n = move_ranking_files(NEW / 'defense', OLD / 'defense')
    print(f'  state_new/defense/ → state/defense/: {n}개 이동')

    # 3. state_new/ 정리
    if NEW.exists():
        # defense 비우기
        if (NEW / 'defense').exists():
            try:
                (NEW / 'defense').rmdir()
            except OSError:
                print(f'  state_new/defense/ 비어있지 않음 — 수동 정리 필요')
        try:
            NEW.rmdir()
            print(f'  state_new/ 디렉토리 제거')
        except OSError:
            print(f'  state_new/ 비어있지 않음 — 수동 정리 필요')

    # 4. 검증
    print(f'\n--- swap 후 확인 ---')
    print(f'  state/ ranking: {len(list(OLD.glob("ranking_*.json")))}')
    print(f'  state/defense/ ranking: {len(list((OLD / "defense").glob("ranking_*.json")))}')
    print(f'  state/regime_state.json: {"있음" if (OLD / "regime_state.json").exists() else "없음"}')


if __name__ == '__main__':
    main()
