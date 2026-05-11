"""state/ → backtest/bt_optf_boost/ + bt_optf_defense/ 복사.

state가 2018-07~2026-05-11 7.8년 옵션F+섹터필터 통합 데이터를 가지므로
BT 평가용 디렉토리를 state에서 즉시 복사 가능 (35분 재생성 → 1분 cp).

BT 디렉토리는 .gitignored (459MB) — git pull 후 이 스크립트 1회 실행하면 BT 동기화 완료.

사용법:
    python sync_bt_from_state.py
"""
import sys, shutil
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent
STATE_BOOST = PROJECT / 'state'
STATE_DEF = PROJECT / 'state' / 'defense'
BT_BOOST = PROJECT / 'backtest' / 'bt_optf_boost'
BT_DEF = PROJECT / 'backtest' / 'bt_optf_defense'


def sync(src, dst):
    if not src.exists():
        print(f'  ERR: {src} 없음')
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    # 기존 ranking 삭제
    for fp in dst.glob('ranking_*.json'):
        if len(fp.stem.replace('ranking_', '')) == 8:
            fp.unlink()
    # 복사
    count = 0
    for fp in src.glob('ranking_*.json'):
        if len(fp.stem.replace('ranking_', '')) == 8:
            shutil.copy2(fp, dst / fp.name)
            count += 1
    return count


def main():
    print('=== state → bt_optf_* 동기화 ===')
    n = sync(STATE_BOOST, BT_BOOST)
    print(f'  state/ → bt_optf_boost/: {n} 파일')
    n = sync(STATE_DEF, BT_DEF)
    print(f'  state/defense/ → bt_optf_defense/: {n} 파일')
    print('\n완료. BT 평가 도구(compare_optf_bt.py 등)에서 사용 가능.')


if __name__ == '__main__':
    main()
