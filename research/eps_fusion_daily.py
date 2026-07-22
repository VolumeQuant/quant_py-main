# -*- coding: utf-8 -*-
"""EPS×Volume 융합 일별 자동화 (2026-06-13).
매일: ① FnGuide 컨센서스 스냅샷(축적) ② 융합 추적기(volume vs fused top3 기록).
best-effort — 한 스텝 실패해도 다음 진행. 프로덕션 파이프라인과 독립.
스케줄: QuanT_EPS_Fusion_Daily (매일 17:30, 16:00 본 파이프라인 + EPS러너 후).
"""
import sys, io, subprocess, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJ = r'C:\dev\claude-code\quant_py-main'
PY = r'C:\Users\jkw88\miniconda3\envs\volumequant\python.exe'

STEPS = [
    # timeout 1500→3600 (2026-07-22): 943종목 크롤이 delay 0.5s만으로 ~16~25분 = 1500s 경계라
    # 대부분 저장 직전 kill → 스냅샷이 ~주 1회만 쌓이던 원인. 여유 1시간으로 확대.
    ('FnGuide 컨센서스 스냅샷 (축적)', [PY, os.path.join(PROJ, 'fnguide_consensus_snapshot.py')], 3600),
    ('융합 추적기 (volume vs fused)', [PY, os.path.join(PROJ, 'research', 'eps_fusion_tracker.py')], 300),
]

for name, cmd, to in STEPS:
    print(f'\n{"="*50}\n▶ {name}\n{"="*50}', flush=True)
    try:
        r = subprocess.run(cmd, cwd=PROJ, timeout=to)
        print(f'  → 종료코드 {r.returncode}', flush=True)
    except subprocess.TimeoutExpired:
        print(f'  → ⚠️ timeout({to}s) — 스킵', flush=True)
    except Exception as e:
        print(f'  → ⚠️ 실패: {e}', flush=True)

print('\n[완료] 융합 일별 자동화', flush=True)
