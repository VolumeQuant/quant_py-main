"""기저효과 필터 백테스트 — 8개 조합 비교

필터:
  A: 전년 영업이익 적자 → G=0
  B: 2년 연속 영업이익 흑자 요구 (아니면 G=0)
  C: 매출성장률 YoY > 150% → 캡 (150%로 제한 후 re-z-score)

조합: 기준선, A, B, C, AB, AC, BC, ABC
"""
import sys, io, os, glob, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
from production_simulator import ProductionSimulator

CACHE = r'C:\dev\data_cache'
t0 = time.time()

# ============================================================
# 1. DART에서 종목별 연간 영업이익 + 매출 테이블 구축
# ============================================================
print('=== DART 재무 데이터 로드 ===')
dart_files = glob.glob(os.path.join(CACHE, 'fs_dart_*.parquet'))
print(f'DART 파일: {len(dart_files)}개')

# {ticker: {year: {'op_income': float, 'revenue': float}}}
fin_table = {}
for fp in dart_files:
    ticker = os.path.basename(fp).replace('fs_dart_', '').replace('.parquet', '')
    try:
        df = pd.read_parquet(fp)
    except:
        continue

    # 영업이익 연간 (12월 결산 기준)
    op = df[df['계정'] == '영업이익'].copy()
    rev = df[df['계정'] == '매출액'].copy()

    if op.empty and rev.empty:
        continue

    fin_table[ticker] = {}

    for acc_df, key in [(op, 'op_income'), (rev, 'revenue')]:
        if acc_df.empty:
            continue
        acc_df = acc_df.copy()
        acc_df['기준일'] = pd.to_datetime(acc_df['기준일'])
        # 연간 = 12월 결산 (공시구분 '사업보고서' 또는 Q4)
        # 12월 기준일 중 가장 큰 값 (누적) 사용
        for year in range(2017, 2026):
            year_data = acc_df[(acc_df['기준일'].dt.year == year) &
                               (acc_df['기준일'].dt.month == 12)]
            if not year_data.empty:
                # 연간 누적값 = 가장 큰 값 (보통 마지막 row)
                val = year_data['값'].max()
                if year not in fin_table[ticker]:
                    fin_table[ticker][year] = {}
                fin_table[ticker][year][key] = float(val)

print(f'종목 수: {len(fin_table)}')

# ============================================================
# 2. 필터 플래그 계산
# ============================================================
# {ticker: {year: {'prev_loss': bool, 'two_year_profit': bool, 'rev_growth_pct': float}}}
filter_flags = {}
for ticker, years in fin_table.items():
    filter_flags[ticker] = {}
    sorted_years = sorted(years.keys())
    for year in sorted_years:
        flags = {}

        # Filter A: 전년 영업이익 적자
        prev_year = year - 1
        if prev_year in years and 'op_income' in years[prev_year]:
            flags['prev_loss'] = years[prev_year]['op_income'] < 0
        else:
            flags['prev_loss'] = False  # 데이터 없으면 통과

        # Filter B: 2년 연속 영업이익 흑자
        prev2_year = year - 2
        cur_profit = years[year].get('op_income', 0) > 0 if 'op_income' in years.get(year, {}) else True
        prev_profit = years[prev_year].get('op_income', 0) > 0 if prev_year in years and 'op_income' in years[prev_year] else True
        prev2_profit = years[prev2_year].get('op_income', 0) > 0 if prev2_year in years and 'op_income' in years[prev2_year] else True
        flags['two_year_profit'] = prev_profit and prev2_profit

        # Filter C: 매출성장률 YoY
        if prev_year in years and 'revenue' in years[prev_year] and 'revenue' in years.get(year, {}):
            prev_rev = years[prev_year]['revenue']
            cur_rev = years[year]['revenue']
            if prev_rev > 0:
                flags['rev_growth_pct'] = (cur_rev / prev_rev - 1) * 100
            else:
                flags['rev_growth_pct'] = 999  # 전년 매출 0 이하 → 극단값
        else:
            flags['rev_growth_pct'] = None  # 데이터 없음

        filter_flags[ticker][year] = flags

# 필터 적용 대상 확인
sample_year = 2024
prev_loss_count = sum(1 for t in filter_flags if sample_year in filter_flags[t] and filter_flags[t][sample_year].get('prev_loss'))
no_two_year = sum(1 for t in filter_flags if sample_year in filter_flags[t] and not filter_flags[t][sample_year].get('two_year_profit', True))
high_growth = sum(1 for t in filter_flags if sample_year in filter_flags[t] and (filter_flags[t][sample_year].get('rev_growth_pct') or 0) > 150)
print(f'\n{sample_year}년 필터 영향:')
print(f'  A (전년적자): {prev_loss_count}종목 G=0')
print(f'  B (2년연속흑자 미충족): {no_two_year}종목 G=0')
print(f'  C (매출성장>150%): {high_growth}종목 캡 적용')

# ============================================================
# 3. 데이터 로드
# ============================================================
print('\n=== 백테스트 데이터 로드 ===')
all_rankings = {}
for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{year}/ranking_*.json'))):
        date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[date] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())

ohlcv_file = sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]
prices = pd.read_parquet(ohlcv_file)
prices = prices.replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))
print(f'데이터: {len(dates)}거래일, {len(all_rankings)}개 ranking')

# ============================================================
# 4. 필터 적용 함수
# ============================================================
def get_fiscal_year(date_str):
    """거래일에 해당하는 재무 기준 연도 (3월까지는 전전년, 4월부터 전년)"""
    month = int(date_str[4:6])
    year = int(date_str[:4])
    # 사업보고서는 보통 3월 말 공시 → 4월부터 반영
    if month <= 3:
        return year - 2  # 아직 전년 사업보고서 미공시
    else:
        return year - 1

def apply_filters(rankings, date_str, use_a=False, use_b=False, use_c=False):
    """필터 적용 후 rankings 반환 (growth_s 수정)"""
    if not use_a and not use_b and not use_c:
        return rankings

    fiscal_year = get_fiscal_year(date_str)
    modified = []

    for item in rankings:
        item = dict(item)  # shallow copy
        ticker = item.get('ticker', '')

        flags = filter_flags.get(ticker, {}).get(fiscal_year, {})

        zero_growth = False

        # Filter A: 전년 적자 → G=0
        if use_a and flags.get('prev_loss', False):
            zero_growth = True

        # Filter B: 2년 연속 흑자 미충족 → G=0
        if use_b and not flags.get('two_year_profit', True):
            zero_growth = True

        if zero_growth:
            item['growth_s'] = 0.0
            item['rev_z'] = 0.0
            item['oca_z'] = 0.0

        # Filter C: 매출성장률 > 150% → growth_s 캡
        if use_c and not zero_growth:
            rg = flags.get('rev_growth_pct')
            if rg is not None and rg > 150:
                # growth_s를 1.5 std로 캡 (상위 ~7% 수준)
                if item.get('growth_s', 0) > 1.5:
                    item['growth_s'] = 1.5
                if item.get('rev_z', 0) > 1.5:
                    item['rev_z'] = 1.5

        modified.append(item)

    return modified

# ============================================================
# 5. 8개 조합 실행
# ============================================================
combos = [
    ('기준선',      False, False, False),
    ('A(전년적자)',  True,  False, False),
    ('B(2년흑자)',   False, True,  False),
    ('C(성장캡)',    False, False, True),
    ('AB',          True,  True,  False),
    ('AC',          True,  False, True),
    ('BC',          False, True,  True),
    ('ABC',         True,  True,  True),
]

# v70 전략 파라미터
V, Q, G, M = 0.20, 0.20, 0.30, 0.30
G_REV = 0.7
STRATEGY = 'rank'
ENTRY = 5
EXIT = 15
SLOTS = 7
STOP_LOSS = -0.10

print(f'\n=== 필터 백테스트 ({len(combos)}개 조합) ===')
print(f'전략: V{int(V*100)}Q{int(Q*100)}G{int(G*100)}M{int(M*100)} g_rev={G_REV}')
print(f'진입: rank≤{ENTRY} 이탈: rank>{EXIT} 슬롯: {SLOTS} 손절: {int(STOP_LOSS*100)}%')
print()

results = []
for label, use_a, use_b, use_c in combos:
    # 필터 적용된 rankings 생성
    filtered_rankings = {}
    for date, ranks in all_rankings.items():
        filtered_rankings[date] = apply_filters(ranks, date, use_a, use_b, use_c)

    sim = ProductionSimulator(filtered_rankings, dates, prices, bench)
    m = sim.run(V, Q, G, M, g_rev=G_REV, strategy=STRATEGY,
                entry_param=ENTRY, exit_param=EXIT,
                max_slots=SLOTS, stop_loss=STOP_LOSS)

    results.append((label, m))
    print(f'  {label:<12} CAGR={m["cagr"]:5.1f}% Sharpe={m["sharpe"]:.3f} Sortino={m["sortino"]:.3f} '
          f'MDD={m["mdd"]:5.1f}% Alpha={m["alpha"]:+.1f}% Hold={m["avg_holdings"]:.1f}')

# ============================================================
# 6. 연도별 상세 비교 (기준선 vs 최고 필터)
# ============================================================
print('\n=== 연도별 Sharpe 비교 ===')
header = f'{"필터":<12}'
years_list = ['2020', '2021', '2022', '2023', '2024', '2025']
for y in years_list:
    header += f' {y:>6}'
header += f' {"전체":>6}'
print(header)
print('-' * (12 + 7 * (len(years_list) + 1)))

for label, m in results:
    line = f'{label:<12}'
    for y in years_list:
        # 연도별 Sharpe 계산
        year_dates = [d for d in dates if d.startswith(y)]
        if len(year_dates) < 20:
            line += f' {"N/A":>6}'
            continue

        # 해당 연도 시뮬레이션
        filtered_rankings = {}
        use_a = 'A' in label or label == 'ABC'
        use_b = 'B' in label or label == 'ABC'
        use_c = 'C' in label or label == 'ABC'
        if label == '기준선':
            use_a = use_b = use_c = False

        for date, ranks in all_rankings.items():
            if date.startswith(y):
                filtered_rankings[date] = apply_filters(ranks, date, use_a, use_b, use_c)
            else:
                filtered_rankings[date] = ranks

        yr_sim = ProductionSimulator(filtered_rankings, dates, prices, bench)
        yr_m = yr_sim.run(V, Q, G, M, g_rev=G_REV, strategy=STRATEGY,
                         entry_param=ENTRY, exit_param=EXIT,
                         max_slots=SLOTS, stop_loss=STOP_LOSS)
        line += f' {yr_m["sharpe"]:6.3f}'

    line += f' {m["sharpe"]:6.3f}'
    print(line)

elapsed = time.time() - t0
print(f'\n완료: {elapsed:.0f}초')
