"""BT 재생성 시 (d)+(d')+(e) 필터 실제 적용 여부 검증

(e) 필터 직접 검증:
  각 ranking 파일의 모든 종목에 대해 G 서브팩터 6개 중 5개 이상이
  동일값이고 |값| > 1.5 인 종목이 있으면 → (e) 필터 미적용

  G 서브팩터 JSON 키: rev_z, oca_z, rev_accel_z, gp_growth_z, op_margin_z, cfo_growth_z

(d) 필터 간접 검증:
  종목수 추이 — 너무 급격히 변동 없어야 (신규 상장 급증 방어)
"""
import sys, os, json, glob
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')

G_SUB = ['rev_z', 'oca_z', 'rev_accel_z', 'gp_growth_z', 'op_margin_z', 'cfo_growth_z']

def is_capped(rec):
    """G 서브팩터 5개 이상 동일값 & |값|>1.5 이면 capped"""
    vals = []
    for k in G_SUB:
        v = rec.get(k)
        if v is None: continue
        try:
            fv = float(v)
            vals.append(fv)
        except:
            pass
    if len(vals) < 5: return False, None
    mc = Counter(vals).most_common(1)[0]
    if mc[1] >= 5 and abs(mc[0]) > 1.5:
        return True, (mc[0], mc[1], vals)
    return False, None


dirs = [
    ('BOOST', [Path('C:/dev/backtest/bt_extended'), Path('C:/dev/state')]),
    ('DEFENSE', [Path('C:/dev/backtest/bt_extended_defense'), Path('C:/dev/state/defense')]),
]

for label, paths in dirs:
    print(f'\n=== {label} (e) 필터 검증 ===')
    files = []
    for p in paths:
        files.extend(sorted(p.glob('ranking_*.json')))
    files = sorted(files)
    print(f'총 파일: {len(files)}')

    capped_count_total = 0
    capped_files = []

    for fp in files:
        with open(fp, 'r', encoding='utf-8') as f:
            d = json.load(f)
        ranks = d.get('rankings', [])
        capped = []
        for r in ranks:
            ok, info = is_capped(r)
            if ok:
                capped.append((r['ticker'], r['name'], r['rank'], info))
        if capped:
            capped_count_total += len(capped)
            capped_files.append((fp.stem.replace('ranking_',''), len(capped), capped[:2]))

    print(f'(e) 필터 우회 종목 총: {capped_count_total}')
    print(f'우회 발생 파일: {len(capped_files)}')

    if capped_files:
        print(f'샘플 10개:')
        for dt, n, samples in capped_files[:10]:
            print(f'  {dt}: {n}종목 capped')
            for tk, nm, rk, info in samples:
                val, cnt, _ = info
                print(f'    rank={rk} {tk} {nm}: 값={val:.2f} ×{cnt}개 동일')
    else:
        print('✅ (e) 필터 완벽 적용 — capped 종목 0건')

# 종목수 추이 (신규 상장 급증 방어 = (d) 간접 검증)
print(f'\n=== 종목수 시계열 (d/d\' 필터 간접 증거) ===')
for p in [Path('C:/dev/backtest/bt_extended'), Path('C:/dev/state')]:
    files = sorted(p.glob('ranking_*.json'))
    if not files: continue
    n_by_month = {}
    for fp in files:
        dt = fp.stem.replace('ranking_','')
        month = dt[:6]
        with open(fp, 'r', encoding='utf-8') as f:
            d = json.load(f)
        n = len(d.get('rankings', []))
        n_by_month.setdefault(month, []).append(n)
    print(f'{p}: {len(n_by_month)}개월')
    months_sorted = sorted(n_by_month.keys())
    # 첫 3, 중간 3, 최근 3
    samples = months_sorted[:3] + months_sorted[len(months_sorted)//2-1:len(months_sorted)//2+2] + months_sorted[-3:]
    for m in samples:
        lst = n_by_month[m]
        print(f'  {m}: mean={sum(lst)/len(lst):.0f} min={min(lst)} max={max(lst)} n_days={len(lst)}')
