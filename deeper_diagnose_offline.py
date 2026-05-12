"""캐시 자체만으로 추가 진단 (DART 호출 0)

목표:
1. 247 no_recent_q_rev 종목 → 매출 row 자체 결손 (BAD 별도 분류)
2. 다른 항목 매핑 버그 검출 (영업이익/자산/CF == 다른 항목?)
3. 캐시 매출액 row가 캐시 내 다른 항목값과 일치하는지 (SG&A 매핑 외 다른 매핑 버그 검출)
4. fs_fnguide와 cross-check (FN과 5배+ 차이나는 분기 검출)
"""
import sys, os, json, glob
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from collections import Counter, defaultdict

print('=' * 60)
print('Offline 추가 진단 (DART 호출 0)')
print('=' * 60)

# ----- 1. no_recent_q_rev 247종목 정밀 분류 -----
print('\n[Step 1] no_recent_q_rev 247종목 분류')
d = json.load(open('C:/dev/diagnose_all_detail.json', encoding='utf-8'))
no_recent = [tk for tk,v in d.items() if v['err']=='no_recent_q_rev']

classes = {'no_rev_at_all': [], 'old_only': [], 'has_some_recent': []}
for tk in no_recent:
    fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
    try:
        b = pd.read_parquet(fp)
        q_rev = b[(b['공시구분']=='q') & (b['계정']=='매출액') & b['값'].notna() & (b['값']!=0)]
        if q_rev.empty:
            classes['no_rev_at_all'].append(tk)
            continue
        years = sorted(set(d_.year for d_ in q_rev['기준일']))
        last_yr = years[-1] if years else 0
        if last_yr < 2024:
            classes['old_only'].append((tk, last_yr, len(q_rev)))
        else:
            classes['has_some_recent'].append((tk, last_yr))
    except Exception:
        pass

print(f'  매출 row 자체 없음: {len(classes["no_rev_at_all"])}')
print(f'  옛 분기만 있음 (last_yr < 2024): {len(classes["old_only"])}')
print(f'  일부 최근 (2024+) 있음: {len(classes["has_some_recent"])}')
if classes['old_only']:
    cnt = Counter(item[1] for item in classes['old_only'])
    print(f'  옛 분기 종목 last_year 분포: {dict(sorted(cnt.items()))}')

# old_only는 = 상장폐지/합병/거래정지 가능성. BAD 아님 (그냥 데이터 누락).
# no_rev_at_all는 = 신규상장 또는 매출 보고 안 함. BAD 아님.

# ----- 2. 다른 항목 매핑 버그 검출 (캐시 매출 row가 다른 회계항목과 동일한 분기) -----
print('\n[Step 2] 캐시 매출 row가 다른 회계항목 값과 일치하는지')
print('  (예: 매출 == 영업이익, 매출 == 자산 등 → 매핑 버그 의심)')

all_files = sorted(glob.glob('C:/dev/data_cache/fs_dart_*.parquet'))
suspicious_cross = []
checked = 0
for fp in all_files:
    tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
    try:
        b = pd.read_parquet(fp)
        # 매출/영업이익/자산/자본/순이익 같은 분기에 정확히 같은 값 있나
        for qtr in b[(b['공시구분']=='q') & (b['기준일']>=pd.Timestamp('2024-01-01'))]['기준일'].unique():
            sub = b[(b['공시구분']=='q') & (b['기준일']==qtr) & b['값'].notna() & (b['값']!=0)]
            if len(sub) < 2: continue
            rev = sub[sub['계정']=='매출액']
            if rev.empty: continue
            rev_v = float(rev['값'].iloc[0])
            for acct in ['영업이익','순이익','자산','자본','현금흐름']:
                other = sub[sub['계정']==acct]
                if other.empty: continue
                ov = float(other['값'].iloc[0])
                if abs(rev_v - ov) < max(1, abs(ov) * 0.005):
                    suspicious_cross.append((tk, qtr.strftime('%Y-%m'), '매출', acct, rev_v))
        checked += 1
    except Exception:
        pass

print(f'  검사: {checked}개 종목')
print(f'  의심 cross match: {len(suspicious_cross)}개')
if suspicious_cross:
    # 종목별 카운트
    cnt = Counter(item[0] for item in suspicious_cross)
    print(f'  종목별 빈도 (상위 10):')
    for tk, c in cnt.most_common(10):
        print(f'    {tk}: {c}건')

# ----- 3. fs_fnguide와 cross-check (DART 캐시 매출 vs FN 매출 5배+ 차이) -----
print('\n[Step 3] FN 매출과 5배+ 차이나는 분기 검출 (다른 매핑 버그 가능성)')
fn_mismatch = []
for fp in all_files:
    tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
    fn_fp = f'C:/dev/data_cache/fs_fnguide_{tk}.parquet'
    if not os.path.exists(fn_fp): continue
    try:
        d_df = pd.read_parquet(fp)
        f_df = pd.read_parquet(fn_fp)

        d_q = d_df[(d_df['공시구분']=='q') & (d_df['계정']=='매출액') & d_df['값'].notna() & (d_df['값']!=0)]
        f_q = f_df[(f_df['공시구분']=='q') & (f_df['계정']=='매출액') & f_df['값'].notna() & (f_df['값']!=0)]
        if d_q.empty or f_q.empty: continue

        # 같은 기준일 매칭
        m = d_q.merge(f_q, on='기준일', suffixes=('_d', '_f'))
        m = m[(m['값_d'] != 0) & (m['값_f'] != 0)]
        if m.empty: continue

        m['ratio'] = m['값_f'] / m['값_d']
        big_diff = m[(m['ratio'] > 5) | (m['ratio'] < 0.2)]
        if not big_diff.empty:
            fn_mismatch.append((tk, len(big_diff), big_diff['기준일'].tolist()))
    except Exception:
        pass

print(f'  FN과 5배+ 차이 종목: {len(fn_mismatch)}개')
# 정렬 — 차이 분기 많은 순
fn_mismatch.sort(key=lambda x: -x[1])
print(f'  상위 15:')
for tk, n, qs in fn_mismatch[:15]:
    # bad_tickers_v2에 이미 있는지
    in_bad = tk in [l.strip() for l in open('C:/dev/bad_tickers_v2.txt')]
    print(f'    {tk}: {n}분기 차이, 이미 BAD={in_bad}, 첫 분기={qs[0].strftime("%Y-%m")}')

# 저장
with open('C:/dev/offline_diag_summary.json', 'w', encoding='utf-8') as f:
    json.dump({
        'no_recent_classified': {k: (len(v) if isinstance(v,list) else v) for k,v in classes.items()},
        'suspicious_cross_count': len(suspicious_cross),
        'fn_mismatch_tickers': [{'ticker': tk, 'n_diff_qtrs': n} for tk,n,_ in fn_mismatch],
    }, f, ensure_ascii=False, indent=1)

print('\n저장: offline_diag_summary.json')
