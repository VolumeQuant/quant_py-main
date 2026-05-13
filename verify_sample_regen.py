"""표본 일자 재생성 검증 — state 결손 회복 확인

5개 결손 일자를 v80 boost 환경변수로 재생성 → 종목수 비교

검증 기준:
- 정상: 220+ 종목 (5/12 baseline 288에 근접)
- 부분 회복: 150~220
- 회복 안 됨: < 150

표본:
- 2018-10-29 (현재 15)
- 2020-03-19 (현재 3)
- 2022-10-13 (현재 26)
- 2024-08-05 (현재 54)
- 2026-01-02 (현재 189)
"""
import os, sys, subprocess, time, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path('C:/dev')
PYTHON = sys.executable
FG = str(PROJECT / 'backtest' / 'fast_generate_rankings_v2.py')

# v80 boost 환경변수
BOOST_ENV = {
    'FACTOR_V_W': '0.15',
    'FACTOR_Q_W': '0.00',
    'FACTOR_G_W': '0.55',
    'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z',
    'G_SUB2': 'oca_z',
    'G_REVENUE_WEIGHT': '0.6',
    'MOM_PERIOD': '12m',
    'PYTHONIOENCODING': 'utf-8',
    'PRODUCTION_MODE': '1',  # 빠른 preload
}

# 표본 5개
SAMPLES = [
    ('20181029', 15),
    ('20200319', 3),
    ('20221013', 26),
    ('20240805', 54),
    ('20260102', 189),
]

# 표본 일자만 재생성 (state_verify/ 별도 디렉토리)
state_dir = PROJECT / 'state_verify_sample'
state_dir.mkdir(exist_ok=True)

# 5일 다 한꺼번에 (연속이 아니라 fast_generate_rankings는 보통 구간 단위라 각각 실행)
# fast_generate_rankings_v2.py가 단일 일자 가능한지 확인 — START=END
for date_str, current_n in SAMPLES:
    print(f'\n=== {date_str} (현재 {current_n}종목) 재생성 ===', flush=True)
    log_path = PROJECT / 'logs' / f'verify_sample_{date_str}.log'
    log_path.parent.mkdir(exist_ok=True)
    merged = {**os.environ, **BOOST_ENV}

    cmd = [PYTHON, '-u', FG, date_str, date_str, f'--state-dir={state_dir}']
    t0 = time.time()
    with open(log_path, 'w', encoding='utf-8') as logf:
        result = subprocess.run(cmd, cwd=str(PROJECT), env=merged,
                                stdout=logf, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace',
                                timeout=600)
    elapsed = time.time() - t0
    print(f'  rc={result.returncode} ({elapsed:.0f}s)', flush=True)

    # 결과 확인
    out_fp = state_dir / f'ranking_{date_str}.json'
    if out_fp.exists():
        n = len(json.load(open(out_fp, encoding='utf-8')).get('rankings', []))
        delta = n - current_n
        status = '✓ 정상화' if n >= 220 else ('⚠️ 부분회복' if n >= 150 else '❌ 회복실패')
        print(f'  결과: {current_n} → {n} (Δ {delta:+}) {status}', flush=True)
    else:
        print(f'  결과: 파일 없음 (log: {log_path})', flush=True)

print('\n=== 검증 완료 ===')
