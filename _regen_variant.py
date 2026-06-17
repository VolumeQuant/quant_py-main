# -*- coding: utf-8 -*-
"""변형 신호 boost state 재생성 (7.4년). arg: adj/vdown/vup.
OHLCV_FILE 오버라이드 + CORPACTION_ADJ_DISABLE=1(이미 수정주가). defense는 기존 재활용(cash).
wr후처리 생략 — TurboSim BT가 z-score에서 자체 3일가중 재계산."""
import sys, os, io, glob, subprocess, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd

name = sys.argv[1]
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
VAR = sorted(glob.glob(f'C:/dev/data_cache/all_ohlcv_{name}_*.parquet'))[-1]
SD = f'_var_{name}'
os.makedirs(SD, exist_ok=True)
LO, HI = '20190102', '20260617'
e = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'OHLCV_FILE': VAR, 'CORPACTION_ADJ_DISABLE': '1'}
e.update(rd._build_mode_env(get_regime_params('boost')))
print(f"[{name}] boost {LO}~{HI} OHLCV={os.path.basename(VAR)} → {SD}/", flush=True)
t0 = time.time()
r = subprocess.run([PY, '-u', FG, LO, HI, f'--state-dir={SD}'], env=e,
                   stdout=open(f'_var_{name}.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
n = len(glob.glob(f'{SD}/ranking_*.json'))
print(f"[{name}] FG rc={r.returncode} {time.time()-t0:.0f}s, {n} ranking JSON", flush=True)
