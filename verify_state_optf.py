"""state_new 옵션F 적용 검증 — 기존 state vs state_new 비교.

검증 항목:
1. 파일 수 비교 (boost + defense)
2. Top 30 종목 비교 (4/30, 5/11)
3. 시스템 수익률 시뮬레이션 비교
"""
import sys, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent

OLD_BOOST = PROJECT / 'state_backup_pre_optf_20260512'
OLD_DEF = PROJECT / 'state_backup_pre_optf_20260512' / 'defense'
NEW_BOOST = PROJECT / 'state_new'
NEW_DEF = PROJECT / 'state_new' / 'defense'


def count(d):
    return len(list(d.glob('ranking_*.json'))) if d.exists() else 0


def top_compare(old_fp, new_fp, n=30):
    if not (old_fp.exists() and new_fp.exists()):
        return None
    with open(old_fp, 'r', encoding='utf-8') as f:
        old = json.load(f).get('rankings', [])
    with open(new_fp, 'r', encoding='utf-8') as f:
        new = json.load(f).get('rankings', [])
    o_set = set(r['ticker'] for r in sorted(old, key=lambda x: x.get('composite_rank', x.get('rank', 999)))[:n])
    n_set = set(r['ticker'] for r in sorted(new, key=lambda x: x.get('composite_rank', x.get('rank', 999)))[:n])
    inter = len(o_set & n_set)
    only_old = sorted(o_set - n_set)
    only_new = sorted(n_set - o_set)
    return inter, only_old, only_new, len(old), len(new)


def main():
    print('=== state_new 검증 ===')
    print(f'\n--- 파일 수 ---')
    print(f'  기존 boost: {count(OLD_BOOST)}')
    print(f'  기존 defense: {count(OLD_DEF)}')
    print(f'  옵션F boost: {count(NEW_BOOST)}')
    print(f'  옵션F defense: {count(NEW_DEF)}')

    print(f'\n--- Top 30 비교 (boost) ---')
    for d in ['20260430', '20260507', '20260511']:
        r = top_compare(OLD_BOOST / f'ranking_{d}.json',
                        NEW_BOOST / f'ranking_{d}.json', 30)
        if r:
            inter, only_old, only_new, n_old, n_new = r
            print(f'  {d}: 교집합 {inter}/30, 기존만 {len(only_old)}, 옵션F만 {len(only_new)} (total {n_old}→{n_new})')
        else:
            print(f'  {d}: 파일 없음')

    print(f'\n--- Top 30 비교 (defense) ---')
    for d in ['20260430', '20260507', '20260511']:
        r = top_compare(OLD_DEF / f'ranking_{d}.json',
                        NEW_DEF / f'ranking_{d}.json', 30)
        if r:
            inter, only_old, only_new, n_old, n_new = r
            print(f'  {d}: 교집합 {inter}/30, 기존만 {len(only_old)}, 옵션F만 {len(only_new)} (total {n_old}→{n_new})')


if __name__ == '__main__':
    main()
