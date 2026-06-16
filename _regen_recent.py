# -*- coding: utf-8 -*-
"""최근 corpaction-era state 3일(6/12·15·16)을 corp-OFF로 재생성 — production 함수 그대로 사용.
순서대로(wr이 이전날 의존). 재생성 후 .bak_corp(old, corp-ON) 대비 top6 변화 검증."""
import sys, os, io, json
sys.path.insert(0, r'C:\dev')
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
boost_params = get_regime_params('boost')
env = rd._build_mode_env(boost_params)
assert 'CORPACTION_ADJ_ENABLE' not in env and os.environ.get('CORPACTION_ADJ_ENABLE') != '1', "corp이 켜지면 안 됨"
log = open('_regen4.log', 'w', encoding='utf-8')
DATES = ['20260612', '20260615', '20260616']
def top6(path):
    d = json.load(open(path, encoding='utf-8'))['rankings']
    d = sorted(d, key=lambda x: x.get('weighted_rank', x['rank']))[:6]
    return [(x['rank'], x['name'], x.get('weighted_rank')) for x in d]
print(f"boost env keys: {sorted(env.keys())}")
print(f"corpaction: 기본 OFF (ENABLE 미설정) 확인됨\n")
for dt in DATES:
    ok1 = rd._run_fg_single(dt, env, 'state', log)
    ok2 = rd._postprocess_ranking(dt, 'state', 'boost', log)
    print(f"=== {dt}  FG={ok1} postproc={ok2} ===")
    old = top6(f'state/ranking_{dt}.json.bak_corp')
    new = top6(f'state/ranking_{dt}.json')
    print(f"  {'순위':>2} {'corp-ON(old)':<28} {'corp-OFF(new)':<28}")
    for i in range(6):
        o = f"{old[i][1]}(wr{old[i][2]})" if i < len(old) else "-"
        n = f"{new[i][1]}(wr{new[i][2]})" if i < len(new) else "-"
        mark = "" if (i < len(old) and i < len(new) and old[i][1] == new[i][1]) else " ★바뀜"
        print(f"  {i+1:>2} {o:<28} {n:<28}{mark}")
    on_set = set(x[1] for x in old[:3]); nn_set = set(x[1] for x in new[:3])
    print(f"  → 진입권(top3) {'동일' if on_set==nn_set else '변경: '+str(on_set^nn_set)}")
log.close()
print("\n재생성 완료. 진입권 동일하면 '0 decision change' 재확인 + corp 제거 정합.")
