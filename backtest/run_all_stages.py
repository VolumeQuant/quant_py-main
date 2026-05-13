"""모든 Stage 순차 자동 실행 — baseline → 1 → 2 → 3 → 4a → 4b → 5 → 6"""
import sys, os, subprocess, time
sys.stdout.reconfigure(encoding='utf-8')
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable

stages = [
    ('baseline', PROJECT + '/backtest/bt_with_new_ohlcv.py'),
    ('stage1_regime', PROJECT + '/backtest/stage1_regime_grid.py'),
    ('stage23_vqgm', PROJECT + '/backtest/stage23_vqgm_grid.py'),
    ('stage4_gsub_mom', PROJECT + '/backtest/stage4_gsub_mom_grid.py'),
    ('stage56_entry_sl', PROJECT + '/backtest/stage56_entry_sl_grid.py'),
]

env = {**os.environ, 'DISP_MAX': '1.5', 'PYTHONIOENCODING': 'utf-8'}

t_total = time.time()
for name, script in stages:
    print(f'\n{"="*60}')
    print(f'>>> {name} 시작 ({time.strftime("%H:%M:%S")})')
    print(f'{"="*60}')
    log_path = f'{PROJECT}/logs/grid_{name}.log'
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.time()
    with open(log_path, 'w', encoding='utf-8') as logf:
        result = subprocess.run([PYTHON, '-u', script], cwd=PROJECT,
                                env=env, stdout=logf, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace')
    elapsed = time.time() - t0
    status = 'OK' if result.returncode == 0 else f'FAIL (rc={result.returncode})'
    print(f'<<< {name} {status} ({elapsed/60:.1f}분, log: {log_path})', flush=True)

print(f'\n{"="*60}')
print(f'전체 완료: {(time.time()-t_total)/60:.1f}분')
print(f'{"="*60}')
