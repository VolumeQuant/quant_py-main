"""잘못된 fs_dart 캐시 종목 식별 → bad_cache_tickers.txt 저장

기준:
1. FN 매출이 DART 매출의 5배+ 인 종목 (캐시 값 잘못)
2. fs_div 컬럼이 없는 종목 (구 버전 캐시, 일관성 미검증)
3. 2024년부터만 데이터 있는 종목 + 시총 1000억+ (incomplete 추정)
"""
import pandas as pd, glob, os, sys
sys.stdout.reconfigure(encoding='utf-8')

# 백업 폴더 기준으로 식별 (이미 재수집된 표본 종목들이 빠지지 않도록)
fs_files = sorted(glob.glob('C:/dev/data_cache_backup_20260512/all_fs_dart/fs_dart_*.parquet'))

# 시총 데이터 (incomplete 종목 중 시총 큰 것만 재수집 대상으로)
mc_files = sorted(glob.glob('C:/dev/data_cache/market_cap_*.parquet'))
mc = None
if mc_files:
    mc = pd.read_parquet(mc_files[-1])
    if '시가총액' in mc.columns:
        mc = mc.set_index(mc.columns[0])['시가총액'] if mc.index.name != mc.columns[0] else mc['시가총액']

bad = set()

for fp in fs_files:
    ticker = os.path.basename(fp).replace('fs_dart_', '').replace('.parquet', '')
    try:
        dart = pd.read_parquet(fp)

        q_d = dart[(dart['공시구분']=='q') & (dart['계정']=='매출액') & dart['값'].notna() & (dart['값']!=0)].sort_values('기준일').drop_duplicates('기준일')

        # 기준 1: FN과 비교 시 매출 5배+ 차이 (cross-sectional mismatch)
        fn_fp = f'C:/dev/data_cache/fs_fnguide_{ticker}.parquet'
        fn_q = None
        if os.path.exists(fn_fp):
            fn = pd.read_parquet(fn_fp)
            fn_q = fn[(fn['공시구분']=='q') & (fn['계정']=='매출액') & fn['값'].notna() & (fn['값']!=0)]
            if not q_d.empty and not fn_q.empty:
                merged = q_d.merge(fn_q, on='기준일', suffixes=('_d', '_f'))
                merged = merged[(merged['값_d'] != 0) & (merged['값_f'] != 0)]
                if not merged.empty:
                    ratios = merged['값_f'] / merged['값_d']
                    if (ratios > 5).any() or (ratios < 0.2).any():
                        bad.add(ticker)

        # 기준 2: DART 시계열 5배+ 점프 + 점프 이전 데이터가 FN 부재
        # (링네트 케이스: 24년 별도 33-38 → 25년 연결 258-790)
        if len(q_d) >= 5:
            fn_dates = set(fn_q['기준일'].unique()) if fn_q is not None and not fn_q.empty else set()
            vals = q_d['값'].values
            dates = q_d['기준일'].values
            for i in range(1, len(vals)):
                if vals[i-1] < 1.0 or vals[i] < 1.0:
                    continue
                ratio = vals[i] / vals[i-1]
                if max(ratio, 1.0/ratio) >= 5.0:
                    # 점프 이전 분기들이 FN에 없으면 → 잘못된 캐시
                    before_dates = set(pd.Timestamp(d) for d in dates[:i])
                    before_in_fn = len(before_dates & fn_dates)
                    if len(before_dates) >= 2 and before_in_fn == 0:
                        bad.add(ticker)
                    break

        # 기준 3: 2024년부터만 데이터 + 시총 1000억+ (incomplete)
        if not q_d.empty:
            earliest = q_d['기준일'].min().year
            if earliest >= 2024:
                if mc is not None and ticker in mc.index:
                    cap = mc.get(ticker, 0)
                    if cap and cap > 1e11:
                        bad.add(ticker)
                else:
                    bad.add(ticker)
    except Exception as e:
        pass

print(f'재수집 대상 종목: {len(bad)} / {len(fs_files)}')

with open('C:/dev/bad_cache_tickers.txt', 'w', encoding='utf-8') as f:
    for tk in sorted(bad):
        f.write(tk + '\n')

print(f'저장: C:/dev/bad_cache_tickers.txt')
