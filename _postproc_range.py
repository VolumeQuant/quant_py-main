# -*- coding: utf-8 -*-
"""재생성된 boost 랭킹(4/28~6/11)에 weighted_rank 후처리 — run_daily._postprocess_ranking 재사용."""
import sys, glob, os, io
sys.path.insert(0, r'C:\dev')
from run_daily import _postprocess_ranking
dummy = io.StringIO()
files = glob.glob('state/ranking_2026*.json')
dates = sorted([os.path.basename(f)[8:16] for f in files
                if len(os.path.basename(f)[8:16]) == 8
                and '20260428' <= os.path.basename(f)[8:16] <= '20260611'])
print(f'후처리 대상 {len(dates)}일')
ok = 0
for ds in dates:
    try:
        if _postprocess_ranking(ds, 'state', 'boost', dummy):
            ok += 1
    except Exception as e:
        print(f'  {ds} 오류: {e}')
print(f'완료: {ok}/{len(dates)}')
