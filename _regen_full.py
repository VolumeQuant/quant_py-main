# -*- coding: utf-8 -*-
"""프로덕션 state 전체(7.4년)를 현재 전략으로 재생성 (2월 이전=시뮬, 현재전략 통일).
boost→state/, defense→state/defense/ FG 범위 재생성(병렬) + wr 후처리(production 함수).
corpaction 기본 OFF(현 코드). production _build_mode_env 사용 = 라이브와 동일 env."""
import sys, os, io, glob, subprocess, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
LO, HI = '20190102', '20260616'
def env_for(mode):
    e = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}  # full 모드 (PRODUCTION_MODE 제거: 과거날 mom_10/vol_low 계산 위해)
    e.update(rd._build_mode_env(get_regime_params(mode)))
    return e
assert os.environ.get('CORPACTION_ADJ_ENABLE') != '1', "corp 켜지면 안 됨"
os.makedirs('state/defense', exist_ok=True)
t0 = time.time()
print(f"[{LO}~{HI}] boost→state/ + defense→state/defense/ FG 병렬 재생성 시작", flush=True)
pb = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=state'], env=env_for('boost'),
                      stdout=open('_full_boost.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
pd_ = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=state/defense'], env=env_for('defense'),
                       stdout=open('_full_def.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
rb, rd_ = pb.wait(), pd_.wait()
print(f"FG 완료 (boost rc={rb}, defense rc={rd_}) {time.time()-t0:.0f}s", flush=True)
class _L:
    def write(self, *a): pass
    def flush(self): pass
log = _L()
for state_dir, mode in [('state', 'boost'), ('state/defense', 'defense')]:
    days = sorted(os.path.basename(f)[8:16] for f in glob.glob(f'{state_dir}/ranking_*.json')
                  if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16]) == 8)
    ok = 0
    for d in days:
        if rd._postprocess_ranking(d, state_dir, mode, log): ok += 1
    print(f"  {mode}: {state_dir} wr후처리 {ok}/{len(days)}일", flush=True)
print(f"ALL DONE {time.time()-t0:.0f}s", flush=True)
