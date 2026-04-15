"""v79 섹터 쏠림이 진짜 쏠림인지, 아니면 시장 베타인지 검증

비교 대상:
1. KOSPI 전체 섹터 분포 (유니버스 기준)
2. KOSPI 시총 가중 섹터 분포 (시총 상위일수록 가중)
3. v77.1 Top 10 섹터 분포
4. v79 Top 10 섹터 분포

만약 한국 시장 자체가 전기전자 60%+ 라면 v79의 73%는 "베타 노출"에 가깝고
시장이 전기전자 20%인데 v79가 73%면 "의도적 쏠림"
"""
import sys, os, json, glob
from pathlib import Path
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np

paths = [Path('C:/dev/backtest/bt_extended'), Path('C:/dev/state')]
files = []
for p in paths:
    files.extend(sorted(p.glob('ranking_*.json')))
files = sorted(files)

# 최근 60일 + 2018~19 초기 60일 + 2020~21 60일 — 시기별 섹터 분포
periods_test = {
    '2018H2-19초기': files[:60],
    '2020-21 코로나': [f for f in files if '20200101' <= f.stem.replace('ranking_','') <= '20211231'][:60],
    '최근 60일': files[-60:],
}

for pname, plist in periods_test.items():
    print(f'\n========== {pname} ({len(plist)}일) ==========')

    # 유니버스 전체 섹터 분포 (빈도)
    univ_sec = Counter()
    # 유니버스 Top 10 섹터 분포 (v79 관심 영역)
    top10_sec = Counter()
    # Top 5 섹터
    top5_sec = Counter()
    # 유니버스 내 각 섹터의 "평균 위치"(mean rank)
    sec_ranks = defaultdict(list)

    for fp in plist:
        d = json.load(open(fp, 'r', encoding='utf-8'))
        ranks = d.get('rankings', [])
        for i, r in enumerate(ranks):
            sec = r.get('sector', 'UNK')
            univ_sec[sec] += 1
            sec_ranks[sec].append(r.get('rank', 999))
            if i < 10: top10_sec[sec] += 1
            if i < 5: top5_sec[sec] += 1

    total_univ = sum(univ_sec.values())
    total_t10 = sum(top10_sec.values())
    total_t5 = sum(top5_sec.values())

    print(f'\n유니버스 총 종목/일 = {total_univ/len(plist):.0f}')
    print(f'\n섹터 분포 비교 (%):')
    print(f'{"섹터":15s}  유니버스  Top10    Top5   오버웨이트(T10-유니)')
    all_secs = sorted(univ_sec.keys(), key=lambda s: -univ_sec[s])
    for sec in all_secs[:10]:
        u_pct = univ_sec[sec]/total_univ*100
        t10_pct = top10_sec.get(sec, 0)/total_t10*100 if total_t10 else 0
        t5_pct = top5_sec.get(sec, 0)/total_t5*100 if total_t5 else 0
        over = t10_pct - u_pct
        mark = '⬆' if over > 5 else ('⬇' if over < -5 else ' ')
        print(f'  {sec:15s}  {u_pct:5.1f}%   {t10_pct:5.1f}%  {t5_pct:5.1f}%    {over:+5.1f}%p {mark}')

# ========== KOSPI 시총 상위 섹터 (실제 한국 시장) ==========
print(f'\n\n========== KOSPI 시총 상위 섹터 (market_cap 기준) ==========')
try:
    # 최근 market_cap 파일
    mc_files = sorted(glob.glob('C:/dev/data_cache/market_cap_*.parquet'))
    print(f'market_cap 파일: {len(mc_files)}개, 최근: {mc_files[-1] if mc_files else "NONE"}')
    if mc_files:
        # 최근 날짜로부터 역산해 하나 로드
        mcdf = pd.read_parquet(mc_files[-1])
        print(f'columns: {list(mcdf.columns)[:10]}')
        print(f'shape: {mcdf.shape}')
        print(mcdf.head())
except Exception as e:
    print(f'market_cap 로드 실패: {e}')

# 최근 ranking에서 시총 가중 (시총 없으니 그냥 Top rank 영향 간접 추정)
# 대신 최근 30일에서 섹터별 평균 등장종목수 × 섹터 평균 rank 반비례 가중
print(f'\n섹터별 "유니버스 진입 평균 순위" (낮을수록 강함) — 최근 60일:')
last60 = files[-60:]
sec_ranks = defaultdict(list)
for fp in last60:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    for r in d.get('rankings', []):
        sec_ranks[r.get('sector', 'UNK')].append(r.get('rank', 999))

rows = []
for sec, ranks in sec_ranks.items():
    rows.append({'sector': sec, 'n_count': len(ranks),
                 'mean_rank': np.mean(ranks), 'median_rank': np.median(ranks)})
sdf = pd.DataFrame(rows).sort_values('n_count', ascending=False).head(15)
print(sdf.to_string(index=False))
