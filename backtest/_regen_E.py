import sys, os, subprocess, time
sys.path.insert(0,'C:/dev')
from regime_indicator import get_regime_params
import run_daily as RD
mode=sys.argv[1] if len(sys.argv)>1 else ''   # '' or 'E'
sd=sys.argv[2]
boost=get_regime_params('boost')
env={**os.environ,'PYTHONIOENCODING':'utf-8',**RD._build_mode_env(boost)}
env.pop('PRODUCTION_MODE',None)  # ★full 모드 (CLAUDE.md: 반드시 full)
if mode: env['EXTREME_MODE']=mode
os.makedirs(sd,exist_ok=True)
t0=time.time()
r=subprocess.run([sys.executable,'-u','C:/dev/backtest/fast_generate_rankings_v2.py','20190102','20260625',f'--state-dir={sd}'],env=env,cwd='C:/dev')
print(f'[regen {mode or "base"}] rc={r.returncode} {(time.time()-t0)/60:.0f}분',flush=True)
