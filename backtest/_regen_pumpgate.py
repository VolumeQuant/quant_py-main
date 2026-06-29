# -*- coding: utf-8 -*-
"""펌프게이트 배포 — 7.4년 state 재생성 (boost+defense, full모드, 펌프게이트 기본 ON).
temp 디렉토리에 FG 전범위 생성 후 날짜순 postprocess. 검증 후 수동 swap."""
import sys, os, subprocess, time, glob
sys.path.insert(0,'C:/dev')
from regime_indicator import get_regime_params
import run_daily as RD
ST='20190102'; EN='20260629'
boost=get_regime_params('boost'); defense=get_regime_params('defense')
benv={**os.environ,'PYTHONIOENCODING':'utf-8',**RD._build_mode_env(boost)}; benv.pop('PRODUCTION_MODE',None)
denv={**os.environ,'PYTHONIOENCODING':'utf-8',**RD._build_mode_env(defense)}; denv.pop('PRODUCTION_MODE',None)
FG='C:/dev/backtest/fast_generate_rankings_v2.py'
def regen(tag, env, sd):
    os.makedirs(sd,exist_ok=True)
    t0=time.time()
    print(f'[{tag}] FG 재생성 {ST}~{EN} → {sd}',flush=True)
    r=subprocess.run([sys.executable,'-u',FG,ST,EN,f'--state-dir={sd}'],env=env,cwd='C:/dev',
                     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
    n=len(glob.glob(sd+'/ranking_*.json'))
    pg=sum(1 for ln in (r.stdout or '').splitlines() if '펌프게이트' in ln)
    print(f'[{tag}] 완료: {n}일, 펌프게이트발동 {pg}일, {(time.time()-t0)/60:.0f}분, rc={r.returncode}',flush=True)
    return n
regen('boost', benv, 'C:/dev/state_pump')
regen('defense', denv, 'C:/dev/state_pump/defense')
print('[FG 재생성 전체 완료]',flush=True)
