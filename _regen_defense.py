# -*- coding: utf-8 -*-
"""defense state(4/28~6/16)를 corp-OFF로 재생성 — boost와 동일 범위/방식.
6/12 corpaction 배포가 defense도 4/28~6/11 소급재생성(d59ad32b9)+sanity재생성(53779e783),
6/12~16은 라이브 corp-ON → defense 32일 전부 corp 오염. boost(c97bfafc2)와 맞추는 작업.
wr 체인(이전2일 cr 의존) 정합 위해 날짜순. production 함수 그대로."""
import sys, os, io, json, glob
sys.path.insert(0, r'C:\dev')
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd

assert os.environ.get('CORPACTION_ADJ_ENABLE') != '1', "corp 켜지면 안 됨"
defense_params = get_regime_params('defense')
env = rd._build_mode_env(defense_params)
SD = 'state/defense'
log = open('_regen_defense.log', 'w', encoding='utf-8')

dates = sorted([os.path.basename(f)[8:16] for f in glob.glob(f'{SD}/ranking_*.json')
                if os.path.basename(f)[8:16].isdigit()
                and '20260428' <= os.path.basename(f)[8:16] <= '20260616'])
print(f"[defense] 재생성 대상 {len(dates)}일: {dates[0]} ~ {dates[-1]}")
print(f"[defense] V/Q/G/M = {defense_params['V_W']}/{defense_params['Q_W']}/{defense_params['G_W']}/{defense_params['M_W']}, corp OFF 확인됨\n")

def top3(path):
    d = json.load(open(path, encoding='utf-8'))['rankings']
    d = sorted(d, key=lambda x: x.get('weighted_rank', x['rank']))[:3]
    return [x['name'] for x in d]

changed = 0
for dt in dates:
    old = top3(f'{SD}/ranking_{dt}.json')
    ok1 = rd._run_fg_single(dt, env, SD, log)
    ok2 = rd._postprocess_ranking(dt, SD, 'defense', log)
    new = top3(f'{SD}/ranking_{dt}.json')
    diff = '' if old == new else f' ★top3변경 {old}->{new}'
    if old != new: changed += 1
    print(f"  {dt} FG={ok1} pp={ok2}{diff}", flush=True)
log.close()
print(f"\n[defense] 완료 {len(dates)}일. top3 변경된 날: {changed}/{len(dates)} (defense=cash라 매매무관, 정합용)")
