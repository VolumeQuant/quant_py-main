# -*- coding: utf-8 -*-
"""lumpiness OFF 풀재생성 (boost) → state_lumpoff/. production env + LUMPINESS_DISABLE=1만 차이."""
import sys, os, io, glob, subprocess, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
LO, HI, SDIR = '20190102', '20260624', 'state_lumpoff'
e = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
e.update(rd._build_mode_env(get_regime_params('boost')))
e['LUMPINESS_DISABLE'] = '1'   # ★ 유일한 차이
assert e.get('CORPACTION_ADJ_DISABLE') == '1' and e.get('SEASONALITY_DISABLE') == '1'
os.makedirs(SDIR, exist_ok=True)
t0 = time.time()
print(f"[{LO}~{HI}] LUMPINESS OFF boost → {SDIR}", flush=True)
p = subprocess.Popen([PY, '-u', FG, LO, HI, f'--state-dir={SDIR}'], env=e,
                     stdout=open('_lumpoff.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
rc = p.wait()
print(f"FG rc={rc} {time.time()-t0:.0f}s", flush=True)
class _L:
    def write(self,*a): pass
    def flush(self): pass
log=_L(); ok=0
days=sorted(os.path.basename(f)[8:16] for f in glob.glob(f'{SDIR}/ranking_*.json') if os.path.basename(f)[8:16].isdigit())
for d in days:
    if rd._postprocess_ranking(d, SDIR, 'boost', log): ok+=1
print(f"wr후처리 {ok}/{len(days)}일  TOTAL {time.time()-t0:.0f}s", flush=True)
