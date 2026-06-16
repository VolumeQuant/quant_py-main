# -*- coding: utf-8 -*-
"""corpaction 오염 전 구간(4/28~6/16) state를 corp-OFF로 재생성 — production 함수 그대로, 날짜순.
6/12 배포 때 4/28~6/11이 corpaction으로 소급재생성됐고 6/12~16은 라이브 corp-ON이라 32일 전부 오염.
wr 체인(각 날 이전2일 cr 의존) 정합 위해 날짜순 재생성 필수."""
import sys, os, io, json, glob
sys.path.insert(0, r'C:\dev')
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
boost_params = get_regime_params('boost')
env = rd._build_mode_env(boost_params)
assert os.environ.get('CORPACTION_ADJ_ENABLE') != '1', "corp 켜지면 안 됨"
log = open('_regen_range.log', 'w', encoding='utf-8')
dates = sorted([os.path.basename(f)[8:16] for f in glob.glob('state/ranking_*.json')
                if os.path.basename(f)[8:16].isdigit() and '20260428' <= os.path.basename(f)[8:16] <= '20260616'])
print(f"재생성 대상 {len(dates)}일: {dates[0]} ~ {dates[-1]}")
def top3(path):
    d = json.load(open(path, encoding='utf-8'))['rankings']
    d = sorted(d, key=lambda x: x.get('weighted_rank', x['rank']))[:3]
    return [x['name'] for x in d]
changed = 0
for dt in dates:
    old = top3(f'state/ranking_{dt}.json')
    ok1 = rd._run_fg_single(dt, env, 'state', log)
    ok2 = rd._postprocess_ranking(dt, 'state', 'boost', log)
    new = top3(f'state/ranking_{dt}.json')
    diff = '' if old == new else f' ★top3변경 {old}->{new}'
    if old != new: changed += 1
    print(f"  {dt} FG={ok1} pp={ok2}{diff}", flush=True)
log.close()
print(f"\n완료 {len(dates)}일. top3(진입권) 변경된 날: {changed}/{len(dates)}")
print("→ 변경 0이면 corpaction이 진입결정 전혀 안 바꿨음 재확인. 소수면 그날만 표시순위 미세변동(진입은 보통 동일).")
