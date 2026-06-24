# -*- coding: utf-8 -*-
"""계절성 OFF로 7.4년 재생성 (2026-06-25, lumpiness와 중복 정리).
production _build_mode_env(SEASONALITY_DISABLE=1 + CORPACTION_ADJ_DISABLE=1 포함) = 라이브와 동일 env.
별도폴더(_so_boost/_so_def) → 검증 후 state/ 배포."""
import sys, os, io, glob, subprocess, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
LO, HI = '20190102', '20260619'
def env_for(mode):
    e = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    e.update(rd._build_mode_env(get_regime_params(mode)))  # SEASONALITY_DISABLE=1 포함
    return e
for d in ['_so_boost', '_so_def']:
    os.makedirs(d, exist_ok=True)
assert rd._build_mode_env(get_regime_params('boost')).get('SEASONALITY_DISABLE') == '1', "계절성 OFF 아님!"
t0 = time.time()
print(f"[{LO}~{HI}] 계절성 OFF 재생성 → _so_boost/_so_def 병렬", flush=True)
pb = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=_so_boost'], env=env_for('boost'),
                      stdout=open('_so_boost.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
pd_ = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=_so_def'], env=env_for('defense'),
                       stdout=open('_so_def.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
rb, rd_ = pb.wait(), pd_.wait()
print(f"FG 완료 (boost rc={rb}, defense rc={rd_}) {time.time()-t0:.0f}s", flush=True)
class _L:
    def write(self, *a): pass
    def flush(self): pass
for sd, mode in [('_so_boost', 'boost'), ('_so_def', 'defense')]:
    dd = sorted(os.path.basename(f)[8:16] for f in glob.glob(f'{sd}/ranking_*.json')
                if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16]) == 8)
    ok = sum(1 for d in dd if rd._postprocess_ranking(d, sd, mode, _L()))
    print(f"  {mode}: {sd} wr후처리 {ok}/{len(dd)}일", flush=True)
print(f"ALL DONE {time.time()-t0:.0f}s", flush=True)
