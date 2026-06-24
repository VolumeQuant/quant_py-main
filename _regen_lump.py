# -*- coding: utf-8 -*-
"""일회성 분기(lumpiness) 페널티 배포용 전체 재생성 → staging(state_lump/, state_lump/defense/).
_regen_full.py와 동일 env(raw OHLCV·full모드·_build_mode_env) + LUMPINESS 기본 ON.
검증 후 state/로 스왑. boost+defense 병렬 FG + wr 후처리(production 함수)."""
import sys, os, io, glob, subprocess, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
LO, HI = '20190102', '20260624'
SB, SD = 'state_lump', 'state_lump/defense'
def env_for(mode):
    e = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}  # full 모드 (PRODUCTION_MODE 미설정)
    e.update(rd._build_mode_env(get_regime_params(mode)))
    return e
assert os.environ.get('CORPACTION_ADJ_ENABLE') != '1', "corp 켜지면 안 됨"
assert os.environ.get('LUMPINESS_DISABLE') != '1', "lumpiness 꺼지면 안 됨(이번 배포 대상)"
os.makedirs(SD, exist_ok=True)
t0 = time.time()
print(f"[{LO}~{HI}] lumpiness ON, boost→{SB}/ + defense→{SD}/ 병렬 재생성", flush=True)
pb = subprocess.Popen([PY, '-u', FG, LO, HI, f'--state-dir={SB}'], env=env_for('boost'),
                      stdout=open('_lump_boost.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
pd_ = subprocess.Popen([PY, '-u', FG, LO, HI, f'--state-dir={SD}'], env=env_for('defense'),
                       stdout=open('_lump_def.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
rb, rd_ = pb.wait(), pd_.wait()
print(f"FG 완료 (boost rc={rb}, defense rc={rd_}) {time.time()-t0:.0f}s", flush=True)
class _L:
    def write(self, *a): pass
    def flush(self): pass
log = _L()
for sdir, mode in [(SB, 'boost'), (SD, 'defense')]:
    days = sorted(os.path.basename(f)[8:16] for f in glob.glob(f'{sdir}/ranking_*.json')
                  if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16]) == 8)
    ok = 0
    for d in days:
        if rd._postprocess_ranking(d, sdir, mode, log): ok += 1
    print(f"  {mode}: {sdir} wr후처리 {ok}/{len(days)}일", flush=True)
print(f"ALL DONE {time.time()-t0:.0f}s", flush=True)
