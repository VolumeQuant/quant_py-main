"""다른 회계항목 깊이 검사 (DART 호출 0, 캐시만)

검사 방향:
1. 각 항목별 DART vs FN 차이 분포 (정상 베이스라인 vs 이상치)
2. 매출과 다른 항목의 부정합 (영업이익 > 매출 같은 경우)
3. 같은 종목 같은 분기에 매출 == 다른 항목 (cross match)
4. 부호 이상 (자산 음수, 자본 너무 큰 음수 등)
"""
import sys, os, glob, json
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from collections import Counter, defaultdict

print('=' * 60)
print('다른 매핑 항목 정밀 검사 (캐시만, DART 호출 0)')
print('=' * 60)

all_files = sorted(glob.glob('C:/dev/data_cache/fs_dart_*.parquet'))
print(f'대상: {len(all_files)} 종목')

# ── 1. 항목별 DART vs FN 5배+ 차이 분포 ──
ACCTS = ['매출액', '영업이익', '순이익', '당기순이익', '자산', '자본',
         '유동자산', '유동부채', '비유동자산', '부채',
         '영업활동으로인한현금흐름', '매출총이익']

per_acct_diff = defaultdict(list)  # {계정: [(ticker, n_diff_qtrs), ...]}

for fp in all_files:
    tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
    fn_fp = f'C:/dev/data_cache/fs_fnguide_{tk}.parquet'
    if not os.path.exists(fn_fp): continue
    try:
        d = pd.read_parquet(fp); f = pd.read_parquet(fn_fp)
        for acct in ACCTS:
            d_q = d[(d['공시구분']=='q') & (d['계정']==acct) & d['값'].notna() & (d['값']!=0)]
            f_q = f[(f['공시구분']=='q') & (f['계정']==acct) & f['값'].notna() & (f['값']!=0)]
            if d_q.empty or f_q.empty: continue
            m = d_q.merge(f_q, on='기준일', suffixes=('_d','_f'))
            m = m[(m['값_d']!=0) & (m['값_f']!=0)]
            if m.empty: continue
            ratio = m['값_d'] / m['값_f']
            # 부호 다르거나 5배+ 차이
            bad = (m['값_d']>0) != (m['값_f']>0)
            bad |= (ratio.abs() > 5) | (ratio.abs() < 0.2)
            n = int(bad.sum())
            if n >= 2:
                per_acct_diff[acct].append((tk, n))
    except Exception:
        pass

print(f'\n[1] 항목별 DART vs FN 5배+ 차이 종목 (2분기 이상)')
for acct, items in sorted(per_acct_diff.items(), key=lambda x: -len(x[1])):
    if not items: continue
    print(f'\n  [{acct}] {len(items)}종목')
    items.sort(key=lambda x: -x[1])
    for tk, n in items[:5]:
        print(f'    {tk}: {n}분기 차이')

# ── 2. 매출과 다른 항목 cross match (같은 분기 매출 == 영업이익 등) ──
print(f'\n[2] 같은 분기 매출 == 다른 항목 (cross match, 의심)')
cross_match = []
for fp in all_files:
    tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
    try:
        b = pd.read_parquet(fp)
        for qtr in b[(b['공시구분']=='q') & (b['기준일']>=pd.Timestamp('2024-01-01'))]['기준일'].unique():
            sub = b[(b['공시구분']=='q') & (b['기준일']==qtr) & b['값'].notna()]
            if len(sub) < 2: continue
            rev_r = sub[sub['계정']=='매출액']
            if rev_r.empty: continue
            rev_v = float(rev_r['값'].iloc[0])
            if abs(rev_v) < 1: continue  # 0 또는 매우 작은 값 무시
            for acct in ['영업이익','당기순이익','자산','자본','매출총이익','영업활동으로인한현금흐름']:
                o = sub[sub['계정']==acct]
                if o.empty: continue
                ov = float(o['값'].iloc[0])
                if abs(rev_v - ov) < max(1, abs(ov)*0.005):
                    cross_match.append((tk, qtr.strftime('%Y-%m'), acct, rev_v))
    except Exception:
        pass

print(f'  cross match 발견: {len(cross_match)}건')
tk_freq = Counter(item[0] for item in cross_match)
print(f'  종목별 빈도 (상위 10):')
for tk, c in tk_freq.most_common(10):
    print(f'    {tk}: {c}건')

# ── 3. 부호 이상 (자산 음수 등) ──
print(f'\n[3] 부호 이상 검사 (자산/자본/매출 음수)')
sign_anomalies = []
for fp in all_files:
    tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
    try:
        b = pd.read_parquet(fp)
        for acct in ['자산','자본','매출액','유동자산']:
            neg = b[(b['공시구분'].isin(['q','y'])) & (b['계정']==acct) & b['값'].notna() & (b['값']<0)]
            if not neg.empty:
                sign_anomalies.append((tk, acct, len(neg)))
    except Exception:
        pass

print(f'  음수 이상치: {len(sign_anomalies)}건')
for tk, acct, n in sign_anomalies[:15]:
    print(f'    {tk} [{acct}]: {n}건')

# ── 4. 영업이익 > 매출 비정상 케이스 ──
print(f'\n[4] 영업이익 > 매출 비정상 (정의상 불가능)')
opi_over_rev = []
for fp in all_files:
    tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
    try:
        b = pd.read_parquet(fp)
        for qtr in b[b['공시구분']=='q']['기준일'].unique():
            sub = b[(b['공시구분']=='q') & (b['기준일']==qtr) & b['값'].notna()]
            r = sub[sub['계정']=='매출액']
            o = sub[sub['계정']=='영업이익']
            if r.empty or o.empty: continue
            rv, ov = float(r['값'].iloc[0]), float(o['값'].iloc[0])
            if rv > 0 and ov > rv * 1.1:  # 매출 양수 + 영업이익이 매출보다 10%+ 큼
                opi_over_rev.append((tk, qtr.strftime('%Y-%m'), rv, ov))
    except Exception:
        pass

print(f'  영업이익 > 매출 케이스: {len(opi_over_rev)}건')
tk_freq2 = Counter(item[0] for item in opi_over_rev)
print(f'  종목별 빈도 (상위 10):')
for tk, c in tk_freq2.most_common(10):
    print(f'    {tk}: {c}건')

# 저장
result = {
    'per_acct_diff': {acct: [(tk, n) for tk, n in items] for acct, items in per_acct_diff.items()},
    'cross_match_total': len(cross_match),
    'cross_match_top_tickers': dict(tk_freq.most_common(20)),
    'sign_anomalies': sign_anomalies,
    'opi_over_rev_count': len(opi_over_rev),
    'opi_over_rev_top': dict(tk_freq2.most_common(20)),
}
with open('C:/dev/deep_check_summary.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=1, default=str)

print(f'\n저장: deep_check_summary.json')

# 추가 BAD 후보 — 기존 v3에 없는 종목 중 다른 항목 이상
with open('C:/dev/bad_tickers_v3.txt') as f:
    existing = set(l.strip() for l in f if l.strip())

extra_bad = set()
for acct, items in per_acct_diff.items():
    if acct == '매출액': continue  # 이미 다룸
    for tk, n in items:
        if n >= 3 and tk not in existing:
            extra_bad.add(tk)
# cross match 4건+ 종목
for tk, c in tk_freq.items():
    if c >= 3 and tk not in existing:
        extra_bad.add(tk)
# 영업이익>매출 2분기+
for tk, c in tk_freq2.items():
    if c >= 2 and tk not in existing:
        extra_bad.add(tk)

with open('C:/dev/bad_tickers_extra.txt', 'w') as f:
    for tk in sorted(extra_bad):
        f.write(tk + '\n')

print(f'\n추가 BAD 후보 (기존 v3 외): {len(extra_bad)}종목')
print(f'  예시: {sorted(extra_bad)[:15]}')
print(f'저장: bad_tickers_extra.txt')
