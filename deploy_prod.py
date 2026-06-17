# -*- coding: utf-8 -*-
"""검증 통과 후 배포: _prod_boost→state/, _prod_def→state/defense/ ranking JSON 교체.
git이 기존 state 추적하므로 롤백=git checkout. 비-ranking 파일(regime_state 등)은 보존."""
import sys, io, os, glob, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
def deploy(src, dst):
    os.makedirs(dst, exist_ok=True)
    n = 0
    for f in glob.glob(f'{src}/ranking_*.json'):
        shutil.copy2(f, os.path.join(dst, os.path.basename(f))); n += 1
    return n
nb = deploy('_prod_boost', 'state')
nd = deploy('_prod_def', 'state/defense')
print(f"배포 완료: boost {nb} → state/, defense {nd} → state/defense/")
print("롤백: git checkout state/ state/defense/")
