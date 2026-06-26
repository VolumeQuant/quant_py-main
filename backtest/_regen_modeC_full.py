import sys, os, subprocess, time
sys.path.insert(0,'C:/dev')
from regime_indicator import get_regime_params
import run_daily as RD
boost=get_regime_params('boost')
env={**os.environ,'PYTHONIOENCODING':'utf-8',**RD._build_mode_env(boost)};env.pop('PRODUCTION_MODE',None);env['EXTREME_MODE']='C'
sd='C:/dev/state_Cfull';os.makedirs(sd,exist_ok=True)
t0=time.time()
print('mode C 전체범위 재생성 시작 (캐시 1회 로드)...',flush=True)
r=subprocess.run([sys.executable,'-u','C:/dev/backtest/fast_generate_rankings_v2.py','20190102','20260625',f'--state-dir={sd}'],env=env,cwd='C:/dev')
import glob
n=len(glob.glob(sd+'/ranking_*.json'))
print(f'완료: {n}일, {(time.time()-t0)/60:.0f}분, rc={r.returncode}',flush=True)
