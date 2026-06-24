# -*- coding: utf-8 -*-
"""1조+ (시총 10000억) 유니버스로 boost 랭킹 재생성 → state_1jo/.
현재전략 env(_build_mode_env boost) 그대로 + --min-mcap=10000. 표본/전체 range는 인자로."""
import sys, os, io, glob, subprocess, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
LO, HI, SDIR = sys.argv[1], sys.argv[2], sys.argv[3]
e = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
e.update(rd._build_mode_env(get_regime_params('boost')))
assert e.get('CORPACTION_ADJ_ENABLE') != '1'
os.makedirs(SDIR, exist_ok=True)
t0 = time.time()
print(f"[{LO}~{HI}] min-mcap=10000 boost → {SDIR} 재생성 시작", flush=True)
p = subprocess.Popen([PY, '-u', FG, LO, HI, f'--state-dir={SDIR}', '--min-mcap=10000'],
                     env=e, stdout=open(f'_{os.path.basename(SDIR)}.log', 'w', encoding='utf-8'),
                     stderr=subprocess.STDOUT)
rc = p.wait()
print(f"FG 완료 rc={rc} {time.time()-t0:.0f}s", flush=True)
class _L:
    def write(self, *a): pass
    def flush(self): pass
log = _L()
days = sorted(os.path.basename(f)[8:16] for f in glob.glob(f'{SDIR}/ranking_*.json')
              if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16]) == 8)
ok = 0
for d in days:
    if rd._postprocess_ranking(d, SDIR, 'boost', log): ok += 1
print(f"wr후처리 {ok}/{len(days)}일  TOTAL {time.time()-t0:.0f}s", flush=True)
