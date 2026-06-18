# -*- coding: utf-8 -*-
"""down-only CA페널티 production state 재생성 (7.4년, boost+defense).
staging(_do_boost/_do_def)에 생성 → 검증 후 deploy_prod 패턴으로 state/ 교체.
env: OHLCV_FILE=수정주가, CORPACTION_ADJ_DISABLE=1, CA_EVENTS_FILE=ca_events.json(down-only),
     _build_mode_env(boost=페널티0.3/K126, defense=무페널티). production daily와 정확히 일치."""
import sys, os, io, glob, subprocess, time
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable
FG = str(rd.SCRIPT_DIR / 'backtest' / 'fast_generate_rankings_v2.py')
ADJ = sorted(glob.glob(str(rd.SCRIPT_DIR / 'data_cache' / 'all_ohlcv_adj_*.parquet')))[-1]
CAEV = str(rd.SCRIPT_DIR / 'data_cache' / 'ca_events.json')
LO, HI = '20190102', '20260617'
# ★PRODUCTION_MODE 금지: 그건 MC 최근30일만 로드(daily용) → 전체 7.4년엔 full MC 필요.
COMMON = {**os.environ, 'PYTHONIOENCODING': 'utf-8',
          'OHLCV_FILE': ADJ, 'CORPACTION_ADJ_DISABLE': '1', 'CA_EVENTS_FILE': CAEV}
COMMON.pop('PRODUCTION_MODE', None)
def env_for(mode):
    e = dict(COMMON); e.update(rd._build_mode_env(get_regime_params(mode))); return e
for d in ['_do_boost', '_do_def']:
    os.makedirs(d, exist_ok=True)
print(f"OHLCV={os.path.basename(ADJ)} | ca_events=down-only | {LO}~{HI}", flush=True)
t0 = time.time()
pb = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=_do_boost'], env=env_for('boost'),
                      cwd=str(rd.SCRIPT_DIR), stdout=open('_do_boost.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
pdf = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=_do_def'], env=env_for('defense'),
                       cwd=str(rd.SCRIPT_DIR), stdout=open('_do_def.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
rb, rdf = pb.wait(), pdf.wait()
print(f"FG 완료 boost rc={rb} defense rc={rdf} ({time.time()-t0:.0f}s)", flush=True)
class _L:
    def write(self, *a): pass
    def flush(self): pass
for sd, mode in [('_do_boost', 'boost'), ('_do_def', 'defense')]:
    days = sorted(os.path.basename(f)[8:16] for f in glob.glob(f'{sd}/ranking_*.json')
                  if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16]) == 8)
    ok = sum(1 for d in days if rd._postprocess_ranking(d, sd, mode, _L()))
    print(f"  {mode}: {sd} {len(days)}일 wr후처리 {ok}", flush=True)
print(f"ALL DONE {time.time()-t0:.0f}s", flush=True)
