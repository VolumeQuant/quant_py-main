# -*- coding: utf-8 -*-
"""자작 corpaction OFF로 7.4년 재생성 (2026-06-24, 의도 vs 실제 결판용).
현재 production state는 자작보정 ON(코드 기본). 이걸 OFF(CORPACTION_ADJ_DISABLE=1)로 별도폴더에
재생성 → TurboSim Calmar 비교. ★production state 안 건드림(_corpoff_boost/_corpoff_def)."""
import sys, os, io, glob, subprocess, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
LO, HI = '20190102', '20260619'
def env_for(mode):
    e = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'CORPACTION_ADJ_DISABLE': '1'}  # ★자작보정 OFF
    e.update(rd._build_mode_env(get_regime_params(mode)))
    return e
for d in ['_corpoff_boost', '_corpoff_def']:
    os.makedirs(d, exist_ok=True)
t0 = time.time()
print(f"[{LO}~{HI}] 자작corpaction OFF 재생성 → _corpoff_boost/_corpoff_def 병렬", flush=True)
pb = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=_corpoff_boost'], env=env_for('boost'),
                      stdout=open('_corpoff_boost.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
pd_ = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=_corpoff_def'], env=env_for('defense'),
                       stdout=open('_corpoff_def.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
rb, rd_ = pb.wait(), pd_.wait()
print(f"FG 완료 (boost rc={rb}, defense rc={rd_}) {time.time()-t0:.0f}s", flush=True)
class _L:
    def write(self, *a): pass
    def flush(self): pass
log = _L()
for sd, mode in [('_corpoff_boost', 'boost'), ('_corpoff_def', 'defense')]:
    days = sorted(os.path.basename(f)[8:16] for f in glob.glob(f'{sd}/ranking_*.json')
                  if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16]) == 8)
    ok = sum(1 for d in days if rd._postprocess_ranking(d, sd, mode, log))
    print(f"  {mode}: {sd} wr후처리 {ok}/{len(days)}일", flush=True)
print(f"ALL DONE {time.time()-t0:.0f}s", flush=True)
