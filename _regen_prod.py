# -*- coding: utf-8 -*-
"""프로덕션 state 전체(7.4년) 재생성 — 수정주가 + 최근CA페널티 (정직한 전략).
안전: 별도 폴더(_prod_boost/_prod_def)에 생성 → 검증 후 state/로 배포(별도 단계).
config: OHLCV_FILE=수정주가, CORPACTION_ADJ_DISABLE=1(자작보정 OFF), CA페널티 W0.3 K126."""
import sys, os, io, glob, subprocess, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
VALL = sorted(glob.glob('C:/dev/data_cache/all_ohlcv_adj_*.parquet'))[-1]
LO, HI = '20190102', '20260617'
# 페널티(FACTOR_RECENT_CA_W)는 COMMON에 넣지 않음 → _build_mode_env(boost전용)이 주입.
# 라이브와 정확히 일치: boost=페널티 0.3, defense=페널티 없음(cash라 무관).
COMMON = {'OHLCV_FILE': VALL, 'CORPACTION_ADJ_DISABLE': '1',
          'CA_EVENTS_FILE': 'C:/dev/data_cache/ca_events.json'}
def env_for(mode):
    e = {**os.environ, 'PYTHONIOENCODING': 'utf-8', **COMMON}
    e.update(rd._build_mode_env(get_regime_params(mode)))
    return e
for d in ['_prod_boost', '_prod_def']:
    os.makedirs(d, exist_ok=True)
t0 = time.time()
print(f"[{LO}~{HI}] 수정주가+페널티 boost→_prod_boost + defense→_prod_def 병렬", flush=True)
pb = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=_prod_boost'], env=env_for('boost'),
                      stdout=open('_prod_boost.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
pdf = subprocess.Popen([PY, '-u', FG, LO, HI, '--state-dir=_prod_def'], env=env_for('defense'),
                       stdout=open('_prod_def.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
rb, rd_ = pb.wait(), pdf.wait()
print(f"FG 완료 (boost rc={rb}, defense rc={rd_}) {time.time()-t0:.0f}s", flush=True)
class _L:
    def write(self, *a): pass
    def flush(self): pass
for sd, mode in [('_prod_boost', 'boost'), ('_prod_def', 'defense')]:
    days = sorted(os.path.basename(f)[8:16] for f in glob.glob(f'{sd}/ranking_*.json')
                  if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16]) == 8)
    ok = sum(1 for d in days if rd._postprocess_ranking(d, sd, mode, _L()))
    print(f"  {mode}: {sd} wr후처리 {ok}/{len(days)}", flush=True)
print(f"ALL DONE {time.time()-t0:.0f}s", flush=True)
