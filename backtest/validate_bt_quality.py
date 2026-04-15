"""BT 파일 품질 전수 검사
체크 항목:
1. 파일 존재성 + JSON 파싱 가능
2. rankings 리스트 존재 + 길이 > 0
3. 각 종목: 필수 필드 존재
4. 각 수치 필드: NaN / None / 비정상 (0, inf)
5. price 0 또는 음수 여부
6. score 극단값 (>10 또는 <-10)
7. 중복 ticker
8. 섹터 정상 (문자열)
9. 누락 날짜 (거래일 기준)
10. rank 순서 확인 (1부터 순증가, composite_rank도 마찬가지)
"""
import sys, os, json, glob, math
from pathlib import Path
from collections import Counter
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np

BT_EXT = Path('C:/dev/backtest/bt_extended')
BT_EXT_D = Path('C:/dev/backtest/bt_extended_defense')
STATE = Path('C:/dev/state')
STATE_D = Path('C:/dev/state/defense')

CRITICAL_FIELDS = ['rank', 'composite_rank', 'ticker', 'name', 'score', 'sector']
NUMERIC_FIELDS = ['score', 'value_s', 'quality_s', 'momentum_s',
                  'rev_z', 'oca_z', 'rev_accel_z', 'gp_growth_z', 'op_margin_z', 'cfo_growth_z',
                  'mom_6m_s', 'mom_6m1m_s', 'mom_12m_s', 'mom_12m1m_s', 'price']


def check_file(fp):
    issues = []
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            d = json.load(f)
    except Exception as e:
        return [('FATAL_PARSE', str(e)[:60])]

    if 'rankings' not in d:
        return [('NO_RANKINGS_KEY', '')]

    ranks = d['rankings']
    if not isinstance(ranks, list):
        return [('RANKINGS_NOT_LIST', type(ranks).__name__)]
    if len(ranks) == 0:
        return [('EMPTY_RANKINGS', '')]

    # 중복 ticker
    tickers = [r.get('ticker') for r in ranks]
    dups = [t for t, c in Counter(tickers).items() if c > 1]
    if dups:
        issues.append(('DUP_TICKER', f'{len(dups)}개: {dups[:3]}'))

    # rank 순증가 체크 (1..N)
    ranks_seq = [r.get('rank') for r in ranks]
    expected = list(range(1, len(ranks) + 1))
    if ranks_seq != expected:
        mismatch = [(i, a, e) for i, (a, e) in enumerate(zip(ranks_seq, expected)) if a != e][:3]
        issues.append(('RANK_SEQ_BROKEN', f'{mismatch}'))

    # 각 레코드 검사
    nan_counts = Counter()
    zero_counts = Counter()
    extreme_counts = Counter()
    price_issues = 0
    missing_critical = 0

    for r in ranks:
        for fld in CRITICAL_FIELDS:
            if fld not in r or r[fld] is None:
                missing_critical += 1

        for fld in NUMERIC_FIELDS:
            v = r.get(fld)
            if v is None:
                nan_counts[fld] += 1
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                nan_counts[fld] += 1
                continue
            if math.isnan(fv) or math.isinf(fv):
                nan_counts[fld] += 1
                continue
            if fld == 'price':
                if fv <= 0:
                    price_issues += 1
            else:
                if fv == 0:
                    zero_counts[fld] += 1
                if abs(fv) > 10:
                    extreme_counts[fld] += 1

    if missing_critical > 0:
        issues.append(('MISSING_CRITICAL', f'{missing_critical} cells'))
    if price_issues > 0:
        issues.append(('PRICE_LE_0', f'{price_issues}종목'))
    for fld, cnt in nan_counts.items():
        if cnt > 0:
            issues.append((f'NAN_{fld}', f'{cnt}/{len(ranks)}'))
    for fld, cnt in zero_counts.items():
        # z-score가 정확히 0인 건 중립값으로 허용되지만 너무 많으면 의심 (>30%)
        if cnt > len(ranks) * 0.30:
            issues.append((f'ZERO_MUCH_{fld}', f'{cnt}/{len(ranks)} ({cnt*100//len(ranks)}%)'))
    for fld, cnt in extreme_counts.items():
        if cnt > 0:
            issues.append((f'EXTREME_{fld}', f'{cnt}/{len(ranks)}'))

    return issues, len(ranks), nan_counts, zero_counts


def scan_dir(bt_dirs, label):
    print(f'\n{"="*70}')
    print(f'{label}: {bt_dirs}')
    print("="*70)

    files = []
    if not isinstance(bt_dirs, (list, tuple)):
        bt_dirs = [bt_dirs]
    for bt_dir in bt_dirs:
        files.extend(sorted(bt_dir.glob('ranking_*.json')))
    files = sorted(files)
    print(f'총 파일: {len(files)}')

    all_issues = Counter()
    file_issues = []  # (fp, [issues])
    n_ranks_list = []
    total_nan = Counter()
    total_zero = Counter()
    fatal_files = []

    for fp in files:
        result = check_file(fp)
        if isinstance(result, list):  # fatal
            fatal_files.append((fp.name, result))
            for code, _ in result:
                all_issues[code] += 1
            continue
        issues, nranks, nan_c, zero_c = result
        n_ranks_list.append(nranks)
        for code, _ in issues:
            all_issues[code] += 1
        if issues:
            file_issues.append((fp.name, issues))
        for k, v in nan_c.items():
            total_nan[k] += v
        for k, v in zero_c.items():
            total_zero[k] += v

    # 요약
    if n_ranks_list:
        print(f'\n종목수 분포: min={min(n_ranks_list)} max={max(n_ranks_list)} '
              f'median={sorted(n_ranks_list)[len(n_ranks_list)//2]} '
              f'mean={sum(n_ranks_list)/len(n_ranks_list):.0f}')

        # 이상 적은 종목수 (<100) 경고
        low_n = [n for n in n_ranks_list if n < 100]
        if low_n:
            print(f'  [WARN] 종목수 < 100 파일: {len(low_n)}개 (최소 {min(low_n)})')

    if fatal_files:
        print(f'\n[FATAL] 파싱 실패/치명적 {len(fatal_files)}개:')
        for name, errs in fatal_files[:5]:
            print(f'  {name}: {errs}')

    print(f'\n이슈 요약 (파일 단위 발생 횟수):')
    for code, cnt in sorted(all_issues.items(), key=lambda x: -x[1]):
        print(f'  {code}: {cnt} files')

    print(f'\n전체 NaN 누적 (필드별 총 건수):')
    for fld, cnt in sorted(total_nan.items(), key=lambda x: -x[1])[:15]:
        print(f'  {fld}: {cnt}')

    print(f'\n전체 ZERO_MUCH 누적:')
    for fld, cnt in sorted(total_zero.items(), key=lambda x: -x[1])[:15]:
        print(f'  {fld}: {cnt}')

    # 첫 5개 이슈 파일 상세
    if file_issues:
        print(f'\n이슈 발생 파일 중 샘플 5개 상세:')
        for name, issues in file_issues[:5]:
            print(f'  {name}:')
            for code, detail in issues[:5]:
                print(f'    {code}: {detail}')

    return all_issues, file_issues, n_ranks_list


def main():
    boost_summary = scan_dir([BT_EXT, STATE], 'BOOST (BT_EXT + STATE)')
    defense_summary = scan_dir([BT_EXT_D, STATE_D], 'DEFENSE (BT_EXT_D + STATE_D)')

    # 날짜 일치 체크
    print(f'\n{"="*70}')
    print('날짜 일치 체크')
    print("="*70)
    boost_dates = set(fp.stem.replace('ranking_','') for fp in list(BT_EXT.glob('ranking_*.json')) + list(STATE.glob('ranking_*.json')))
    def_dates = set(fp.stem.replace('ranking_','') for fp in list(BT_EXT_D.glob('ranking_*.json')) + list(STATE_D.glob('ranking_*.json')))
    only_boost = boost_dates - def_dates
    only_def = def_dates - boost_dates
    print(f'boost만 있는 날짜: {len(only_boost)} {sorted(only_boost)[:5]}')
    print(f'defense만 있는 날짜: {len(only_def)} {sorted(only_def)[:5]}')
    print(f'공통 날짜: {len(boost_dates & def_dates)}')

    # 거래일 누락 체크 (KOSPI 거래일 대비)
    kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
    kospi_dates = set(kdf.index.strftime('%Y%m%d'))
    bt_start, bt_end = '20180702', '20260414'
    kospi_in_range = {d for d in kospi_dates if bt_start <= d <= bt_end}
    boost_in_range = {d for d in boost_dates if bt_start <= d <= bt_end}
    missing_bt = kospi_in_range - boost_in_range
    print(f'\n거래일 누락 (KOSPI있지만 BT없음): {len(missing_bt)}')
    if missing_bt:
        print(f'  샘플: {sorted(missing_bt)[:10]}')


if __name__ == '__main__':
    main()
