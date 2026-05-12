"""verify_after_refetch.py 시뮬레이션 — 가상 정상 상태에서 종료 코드 0 검증

방법:
1. bad_tickers_v3.txt를 빈 리스트로 임시 변경 (검증 후 원복)
2. 또는 verify 로직을 직접 호출해서 정상 상태 시뮬레이션
"""
import sys, os, shutil
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

# 백업
SRC = 'C:/dev/bad_tickers_v3.txt'
BAK = SRC + '.bak_sim'
shutil.copy2(SRC, BAK)

print('=' * 50)
print('verify_after_refetch.py 시뮬레이션')
print('=' * 50)

# 시나리오 1: 정상 상태 (BAD 리스트가 모두 정상화됐다고 가정)
# bad_tickers_v3.txt를 표본 4종목 (이미 정상)로 임시 교체
print('\n[시나리오 1] 모두 정상화된 상태 (표본 4 정상 종목만 BAD 리스트)')
with open(SRC, 'w') as f:
    f.write('042500\n024840\n046940\n072950\n')

import subprocess
PYTHON = r'C:\Users\user\miniconda3\envs\volumequant\python.exe'
result = subprocess.run(
    [PYTHON, 'C:/dev/verify_after_refetch.py'],
    capture_output=True, text=True, encoding='utf-8'
)
print(f'  종료 코드: {result.returncode}')
if result.returncode == 0:
    print('  ✓ 정상 상태 → 코드 0 (통과)')
else:
    print(f'  ⚠️ 정상이라야 하는데 코드 {result.returncode}')
    print(f'  출력 마지막 15줄:')
    for line in result.stdout.splitlines()[-15:]:
        print(f'    {line}')

# 원복
shutil.copy2(BAK, SRC)
os.remove(BAK)

# 시나리오 2: 잔여 1~5개 BAD (수동 검토 권장 케이스)
print('\n[시나리오 2] 잔여 5개 BAD (수동 검토 케이스, 코드 1 기대)')
# bad_tickers_v3에 5개 진짜 잔여 BAD 케이스 시뮬레이션
shutil.copy2(SRC, BAK)
import json
d = json.load(open('C:/dev/diagnose_all_detail.json',encoding='utf-8'))
real_bad = [tk for tk,v in d.items() if len(v['bad_qtrs'])>=2][:5]
with open(SRC, 'w') as f:
    for tk in real_bad:
        f.write(tk + '\n')

result2 = subprocess.run(
    [PYTHON, 'C:/dev/verify_after_refetch.py'],
    capture_output=True, text=True, encoding='utf-8'
)
print(f'  종료 코드: {result2.returncode}')
if result2.returncode in [0, 1]:
    print(f'  ✓ 잔여 5개 → 코드 {result2.returncode} 적절')
else:
    print(f'  ⚠️ 잔여 5개라면 코드 0 또는 1 기대했는데 {result2.returncode}')

# 원복
shutil.copy2(BAK, SRC)
os.remove(BAK)

print('\n시뮬레이션 완료. 원본 bad_tickers_v3.txt 복원됨.')
sys.exit(0 if result.returncode == 0 else 1)
