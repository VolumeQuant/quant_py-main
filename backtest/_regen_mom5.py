import sys, os, subprocess, time
ROOT='C:/dev/claude-code/quant_py-main'
sys.path.insert(0,ROOT)
from regime_indicator import get_regime_params
import run_daily as RD
w=sys.argv[1]; start=sys.argv[2]; end=sys.argv[3]; sd=sys.argv[4]
boost=get_regime_params('boost')
env={**os.environ,'PYTHONIOENCODING':'utf-8',**RD._build_mode_env(boost)}
env.pop('PRODUCTION_MODE',None)          # full 모드
env['FACTOR_MOM_5_W']=w                    # mom_5 가중치 (→ mom_5_z 저장)
os.makedirs(sd,exist_ok=True)
t0=time.time()
r=subprocess.run([sys.executable,'-u',ROOT+'/backtest/fast_generate_rankings_v2.py',start,end,f'--state-dir={sd}'],env=env,cwd=ROOT)
print(f'[regen mom5 w={w}] rc={r.returncode} {(time.time()-t0)/60:.1f}분',flush=True)
