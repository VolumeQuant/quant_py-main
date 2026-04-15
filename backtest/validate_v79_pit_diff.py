"""v79 1차(git commit c34a86390) vs 2차(디스크 현재, FnGuide PIT 반영) 비교
랜덤 날짜 10개에서 Top 10 종목 + 점수 차이 분석
"""
import sys, json, subprocess, random
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

COMMIT_1ST = 'c34a86390'  # v79 1차
random.seed(42)

# 랜덤 10일 추출 (state/)
state_dir = Path('C:/dev/state')
all_dates = sorted([fp.stem.replace('ranking_', '') for fp in state_dir.glob('ranking_*.json')
                    if len(fp.stem.replace('ranking_', '')) == 8])
samples = random.sample(all_dates, 10)
samples.append('20260414')  # 최근 추가
samples.append('20230615')  # 중간 추가
samples = sorted(set(samples))

print(f'검증 대상 {len(samples)}일:')

def load_git_version(path, commit):
    try:
        out = subprocess.check_output(
            ['git', 'show', f'{commit}:{path}'],
            cwd='C:/dev', stderr=subprocess.DEVNULL,
        )
        return json.loads(out.decode('utf-8'))
    except Exception as e:
        return None

def compare_one(date_str):
    rel = f'state/ranking_{date_str}.json'
    v1 = load_git_version(rel, COMMIT_1ST)
    try:
        with open(f'C:/dev/{rel}', 'r', encoding='utf-8') as f:
            v2 = json.load(f)
    except FileNotFoundError:
        return date_str, None, None, 'disk_missing'

    if v1 is None:
        return date_str, None, None, 'git_missing'

    r1 = v1.get('rankings', [])
    r2 = v2.get('rankings', [])
    n1, n2 = len(r1), len(r2)

    # Top 10 종목 비교
    top1 = [(r['composite_rank'], r['ticker'], r['score']) for r in r1[:10]]
    top2 = [(r['composite_rank'], r['ticker'], r['score']) for r in r2[:10]]

    # 티커 기준 set 비교
    tk1 = set(r['ticker'] for r in r1[:10])
    tk2 = set(r['ticker'] for r in r2[:10])
    common = tk1 & tk2
    only1 = tk1 - tk2
    only2 = tk2 - tk1

    return date_str, (n1, n2), (top1, top2, len(common), only1, only2), None


tot_common = 0
tot_days = 0
for d in samples:
    date_str, sizes, cmp, err = compare_one(d)
    if err:
        print(f'  {date_str}: {err}')
        continue
    n1, n2 = sizes
    top1, top2, n_common, o1, o2 = cmp
    tot_common += n_common
    tot_days += 1
    status = '동일' if n_common == 10 else f'Top10 공통 {n_common}/10'
    print(f'\n=== {date_str} (v1:{n1} v2:{n2}, {status}) ===')
    if n_common < 10:
        print(f'  v1만: {list(o1)[:5]}')
        print(f'  v2만: {list(o2)[:5]}')
    # Top 5 점수 비교
    print('  Top 5 비교:')
    for i in range(min(5, len(top1), len(top2))):
        cr1, tk1_, sc1 = top1[i]
        cr2, tk2_, sc2 = top2[i]
        same = '✓' if tk1_ == tk2_ else '✗'
        print(f'    rank {i+1}: v1={tk1_}({sc1:.3f}) v2={tk2_}({sc2:.3f}) {same}')

print(f'\n\n=== 요약 ===')
print(f'{tot_days}일 평균 Top 10 공통: {tot_common/tot_days:.1f}/10')
