"""
순위 변동 & 점수 분포 EDA 분석
state/ranking_*.json 전체를 읽어서 분석
"""
import sys, json, glob, os
import numpy as np
from collections import defaultdict, Counter

sys.stdout.reconfigure(encoding='utf-8')

BASE = r"C:\dev\claude code\quant_py-main"
files = sorted(glob.glob(os.path.join(BASE, "state", "ranking_*.json")))

print(f"=== 한국주식 퀀트 순위 EDA 분석 ===")
print(f"분석 대상 파일: {len(files)}개")
print(f"기간: {os.path.basename(files[0]).replace('ranking_','').replace('.json','')} ~ "
      f"{os.path.basename(files[-1]).replace('ranking_','').replace('.json','')}")
print()

# ── 데이터 로드 ──
all_data = []  # list of (date_str, rankings_list)
for f in files:
    with open(f, 'r', encoding='utf-8') as fp:
        d = json.load(fp)
    date_str = d['date']
    rankings = d['rankings']
    all_data.append((date_str, rankings))

dates = [d[0] for d in all_data]
n_dates = len(dates)

# ════════════════════════════════════════════
# 1. 점수 분포 분석
# ════════════════════════════════════════════
print("=" * 70)
print("1. 점수 분포 분석 (모든 날짜 통합)")
print("=" * 70)

# 구간별 점수 수집
bands = {
    '1~5위': (1, 5),
    '6~10위': (6, 10),
    '11~20위': (11, 20),
    '21~30위': (21, 30),
}

band_scores = {k: [] for k in bands}

for date_str, rankings in all_data:
    for item in rankings:
        cr = item['composite_rank']
        score = item['score']
        for band_name, (lo, hi) in bands.items():
            if lo <= cr <= hi:
                band_scores[band_name].append(score)

print(f"\n{'구간':<12} {'개수':>6} {'평균':>8} {'표준편차':>8} {'최소':>8} {'최대':>8} {'중위':>8}")
print("-" * 70)
for band_name in bands:
    scores = band_scores[band_name]
    if scores:
        arr = np.array(scores)
        print(f"{band_name:<12} {len(arr):>6} {arr.mean():>8.4f} {arr.std():>8.4f} "
              f"{arr.min():>8.4f} {arr.max():>8.4f} {np.median(arr):>8.4f}")

# 인접 순위 간 점수 차이
print(f"\n── 인접 순위 간 점수 gap (composite_rank 기준, 전 날짜 평균) ──")
rank_gaps = defaultdict(list)  # key: (r, r+1), val: list of gaps

for date_str, rankings in all_data:
    by_cr = sorted(rankings, key=lambda x: x['composite_rank'])
    score_by_cr = {item['composite_rank']: item['score'] for item in by_cr}
    for r in range(1, 30):
        if r in score_by_cr and (r+1) in score_by_cr:
            gap = score_by_cr[r] - score_by_cr[r+1]
            rank_gaps[(r, r+1)].append(gap)

print(f"\n{'순위 gap':<12} {'평균 차이':>10} {'표준편차':>10} {'최대 차이':>10}")
print("-" * 50)
for r in range(1, 30):
    key = (r, r+1)
    if key in rank_gaps and rank_gaps[key]:
        arr = np.array(rank_gaps[key])
        marker = ""
        if arr.mean() > 0.15:
            marker = " *** 큰 gap"
        elif arr.mean() > 0.10:
            marker = " ** 주목"
        print(f"{r:>2}→{r+1:<2}위     {arr.mean():>10.4f} {arr.std():>10.4f} {arr.max():>10.4f}{marker}")

# 점수 분포 형태 분석
print(f"\n── 점수 분포 형태 ──")
all_scores_by_rank = defaultdict(list)
for date_str, rankings in all_data:
    for item in rankings:
        all_scores_by_rank[item['composite_rank']].append(item['score'])

top5_scores = []
rest_scores = []
for date_str, rankings in all_data:
    for item in rankings:
        if item['composite_rank'] <= 5:
            top5_scores.append(item['score'])
        elif item['composite_rank'] <= 30:
            rest_scores.append(item['score'])

top5_arr = np.array(top5_scores)
rest_arr = np.array(rest_scores)
print(f"  Top 5 평균: {top5_arr.mean():.4f}, 6~30위 평균: {rest_arr.mean():.4f}")
print(f"  차이: {top5_arr.mean() - rest_arr.mean():.4f}")
print(f"  Top 5 표준편차: {top5_arr.std():.4f}, 6~30위 표준편차: {rest_arr.std():.4f}")

# 상위 집중도: 1위 점수 / 30위 점수 비율
ratios = []
for date_str, rankings in all_data:
    by_cr = sorted(rankings, key=lambda x: x['composite_rank'])
    if len(by_cr) >= 30:
        r1 = by_cr[0]['score']
        r30 = by_cr[29]['score']
        if r30 != 0:
            ratios.append(r1 / r30)
if ratios:
    print(f"  1위/30위 점수 비율: 평균 {np.mean(ratios):.2f}x (범위 {np.min(ratios):.2f}~{np.max(ratios):.2f})")

# ════════════════════════════════════════════
# 2. 순위 변동성 분석
# ════════════════════════════════════════════
print()
print("=" * 70)
print("2. 순위 변동성 분석")
print("=" * 70)

# 종목별 composite_rank 히스토리
ticker_history = defaultdict(list)  # ticker -> list of (date, composite_rank, score, name)
for date_str, rankings in all_data:
    for item in rankings:
        ticker_history[item['ticker']].append({
            'date': date_str,
            'composite_rank': item['composite_rank'],
            'score': item['score'],
            'name': item['name'],
        })

# 등장 2회 이상 종목만 분석
print(f"\n── 순위 변동성 (Top 30에 2회 이상 등장한 종목) ──")
print(f"{'종목':<18} {'등장':>4} {'평균순위':>8} {'순위 StdDev':>12} {'최고':>5} {'최저':>5} {'Top5 일수':>9} {'Top10 일수':>10}")
print("-" * 90)

volatility_data = []
for ticker, history in ticker_history.items():
    if len(history) < 2:
        continue
    ranks = [h['composite_rank'] for h in history]
    name = history[0]['name']
    avg_rank = np.mean(ranks)
    std_rank = np.std(ranks)
    min_rank = min(ranks)
    max_rank = max(ranks)
    top5_days = sum(1 for r in ranks if r <= 5)
    top10_days = sum(1 for r in ranks if r <= 10)
    volatility_data.append({
        'ticker': ticker, 'name': name, 'count': len(history),
        'avg': avg_rank, 'std': std_rank, 'min': min_rank, 'max': max_rank,
        'top5': top5_days, 'top10': top10_days,
    })

# 평균순위 기준 정렬
volatility_data.sort(key=lambda x: x['avg'])
for v in volatility_data[:40]:  # 상위 40개만
    print(f"{v['name']:<18} {v['count']:>4} {v['avg']:>8.1f} {v['std']:>12.2f} "
          f"{v['min']:>5} {v['max']:>5} {v['top5']:>9} {v['top10']:>10}")

# TOP5 경계 분석 (5~6위 왔다갔다)
print(f"\n── TOP5 경계 종목 (5위~6위 근처에서 왔다갔다) ──")
boundary_tickers = []
for v in volatility_data:
    ticker = v['ticker']
    history = ticker_history[ticker]
    ranks = [h['composite_rank'] for h in history]
    in_top5 = sum(1 for r in ranks if r <= 5)
    out_top5 = sum(1 for r in ranks if r > 5)
    if in_top5 >= 2 and out_top5 >= 2:
        # 경계 전환 횟수
        transitions = 0
        for i in range(1, len(ranks)):
            was_in = ranks[i-1] <= 5
            now_in = ranks[i] <= 5
            if was_in != now_in:
                transitions += 1
        if transitions >= 2:
            boundary_tickers.append({
                'name': v['name'], 'ticker': ticker,
                'in_top5': in_top5, 'out_top5': out_top5,
                'transitions': transitions,
                'ranks': ranks,
                'avg': v['avg'],
            })

boundary_tickers.sort(key=lambda x: -x['transitions'])
for bt in boundary_tickers:
    ranks_str = '→'.join(str(r) for r in bt['ranks'][-8:])  # 최근 8일
    print(f"  {bt['name']:<16} Top5 {bt['in_top5']}일 / 이탈 {bt['out_top5']}일, "
          f"전환 {bt['transitions']}회, 최근: {ranks_str}")

# ════════════════════════════════════════════
# 3. TOP5 턴오버
# ════════════════════════════════════════════
print()
print("=" * 70)
print("3. TOP5 턴오버 분석")
print("=" * 70)

daily_top5 = []
for date_str, rankings in all_data:
    top5_set = set()
    for item in rankings:
        if item['composite_rank'] <= 5:
            top5_set.add(item['ticker'])
    daily_top5.append((date_str, top5_set))

# 날짜별 변동
print(f"\n── 날짜별 TOP5 변동 ──")
print(f"{'날짜':<12} {'변동':>4} {'신규 진입':<30} {'이탈':<30}")
print("-" * 80)
total_changes = 0
for i in range(len(daily_top5)):
    date_str, current = daily_top5[i]
    if i == 0:
        print(f"{date_str:<12} {'(시작)':>4}")
        continue
    prev = daily_top5[i-1][1]
    new_in = current - prev
    dropped = prev - current
    n_changes = len(new_in)
    total_changes += n_changes

    # 이름 찾기
    name_map = {}
    for _, rankings in all_data:
        for item in rankings:
            name_map[item['ticker']] = item['name']

    new_names = ', '.join(name_map.get(t, t) for t in new_in) if new_in else '-'
    drop_names = ', '.join(name_map.get(t, t) for t in dropped) if dropped else '-'
    print(f"{date_str:<12} {n_changes:>4} {new_names:<30} {drop_names:<30}")

print(f"\n  총 턴오버: {total_changes}회 / {n_dates-1}거래일 = 일평균 {total_changes/(n_dates-1):.2f}종목/일")

# TOP5에 한번이라도 진입한 종목
all_top5_tickers = set()
for _, top5_set in daily_top5:
    all_top5_tickers |= top5_set

name_map = {}
for _, rankings in all_data:
    for item in rankings:
        name_map[item['ticker']] = item['name']

print(f"\n  TOP5 진입 경험 종목 수: {len(all_top5_tickers)}개")
top5_counts = []
for t in all_top5_tickers:
    days_in = sum(1 for _, s in daily_top5 if t in s)
    top5_counts.append((name_map.get(t, t), days_in))
top5_counts.sort(key=lambda x: -x[1])
print(f"  {'종목':<18} {'Top5 일수':>10} {'비율':>8}")
print(f"  {'-'*40}")
for name, days in top5_counts:
    print(f"  {name:<18} {days:>10} {days/n_dates*100:>7.1f}%")

# ════════════════════════════════════════════
# 4. 클러스터 분석 (점수 gap 기반)
# ════════════════════════════════════════════
print()
print("=" * 70)
print("4. 클러스터 분석 (점수 기반 자연 그룹)")
print("=" * 70)

# 각 날짜별로 순위 간 gap 패턴 분석
print(f"\n── 날짜별 가장 큰 gap 위치 (자연 경계선) ──")
print(f"{'날짜':<12} {'1st gap 위치':>12} {'gap 크기':>10} {'2nd gap 위치':>12} {'gap 크기':>10} {'3rd gap 위치':>12} {'gap 크기':>10}")
print("-" * 90)

gap_positions_counter = Counter()

for date_str, rankings in all_data:
    by_cr = sorted(rankings, key=lambda x: x['composite_rank'])
    gaps = []
    for i in range(len(by_cr) - 1):
        gap = by_cr[i]['score'] - by_cr[i+1]['score']
        pos = by_cr[i]['composite_rank']
        gaps.append((gap, pos))

    gaps.sort(key=lambda x: -x[0])
    top3 = gaps[:3]

    line = f"{date_str:<12}"
    for gap_val, pos in top3:
        line += f" {pos:>2}→{pos+1:<2}위    {gap_val:>10.4f}"
        gap_positions_counter[pos] += 1
    print(line)

print(f"\n── gap 빈출 위치 (자연 클러스터 경계) ──")
print(f"  위치 = '이 순위와 다음 순위 사이에 큰 gap이 자주 발생'")
for pos, count in gap_positions_counter.most_common(10):
    bar = '█' * count
    print(f"  {pos:>2}→{pos+1:<2}위 경계: {count:>3}회 {bar}")

# 평균 점수 프로파일 (순위별)
print(f"\n── 순위별 평균 점수 프로파일 ──")
print(f"{'순위':>4} {'평균점수':>10} {'StdDev':>8} {'시각화'}")
print("-" * 60)
for r in range(1, 31):
    if r in all_scores_by_rank and all_scores_by_rank[r]:
        arr = np.array(all_scores_by_rank[r])
        bar_len = max(0, int((arr.mean() + 1) * 20))  # scale for display
        bar = '█' * bar_len
        print(f"{r:>4} {arr.mean():>10.4f} {arr.std():>8.4f}  {bar}")

# 누적 gap 분석 (1위 대비 점수 하락)
print(f"\n── 1위 대비 누적 점수 하락 ──")
cumul_drops = defaultdict(list)
for date_str, rankings in all_data:
    by_cr = sorted(rankings, key=lambda x: x['composite_rank'])
    if by_cr:
        top_score = by_cr[0]['score']
        for item in by_cr:
            drop = top_score - item['score']
            cumul_drops[item['composite_rank']].append(drop)

print(f"{'순위':>4} {'1위 대비 평균 하락':>18} {'시각화'}")
print("-" * 50)
for r in range(1, 31):
    if r in cumul_drops:
        avg_drop = np.mean(cumul_drops[r])
        bar = '▓' * int(avg_drop * 15)
        print(f"{r:>4} {avg_drop:>18.4f}  {bar}")

# ── 팩터별 기여도 분석 (보너스) ──
print()
print("=" * 70)
print("5. [보너스] 팩터별 기여도 (Top5 vs 나머지)")
print("=" * 70)

factors = ['value_s', 'quality_s', 'growth_s', 'momentum_s']
factor_top5 = {f: [] for f in factors}
factor_rest = {f: [] for f in factors}

for date_str, rankings in all_data:
    for item in rankings:
        for f in factors:
            if f in item and item[f] is not None:
                if item['composite_rank'] <= 5:
                    factor_top5[f].append(item[f])
                else:
                    factor_rest[f].append(item[f])

print(f"\n{'팩터':<14} {'Top5 평균':>10} {'6~30위 평균':>12} {'차이':>10} {'우위 배수':>10}")
print("-" * 60)
for f in factors:
    t5 = np.array(factor_top5[f])
    rest = np.array(factor_rest[f])
    diff = t5.mean() - rest.mean()
    ratio = t5.mean() / rest.mean() if rest.mean() != 0 else float('inf')
    print(f"{f:<14} {t5.mean():>10.4f} {rest.mean():>12.4f} {diff:>10.4f} {ratio:>10.2f}x")

# 종합 요약
print()
print("=" * 70)
print("종합 요약")
print("=" * 70)
avg_turnover = total_changes / (n_dates - 1)
print(f"  - 분석 기간: {n_dates}거래일")
print(f"  - TOP5 일평균 턴오버: {avg_turnover:.2f}종목/일")
print(f"  - TOP5 진입 경험 종목: {len(all_top5_tickers)}개")
print(f"  - Top5 평균 점수: {top5_arr.mean():.4f} vs 6~30위: {rest_arr.mean():.4f} (gap: {top5_arr.mean()-rest_arr.mean():.4f})")

# 안정성 지표
stable_top5 = [v for v in volatility_data if v['avg'] <= 5 and v['std'] < 2]
volatile_top5 = [v for v in volatility_data if v['top5'] >= 3 and v['std'] > 3]
print(f"  - 안정적 Top5 종목 (평균순위<=5, StdDev<2): {len(stable_top5)}개 → {', '.join(v['name'] for v in stable_top5)}")
if volatile_top5:
    print(f"  - 변동 큰 Top5 출입 종목 (Top5>=3일, StdDev>3): {len(volatile_top5)}개 → {', '.join(v['name'] for v in volatile_top5)}")

# 클러스터 결론
top_gaps = gap_positions_counter.most_common(3)
print(f"  - 주요 점수 클러스터 경계: {', '.join(f'{p}→{p+1}위' for p, _ in top_gaps)}")
print(f"  - 해석: 이 위치에서 점수 차이가 크게 벌어져 자연 그룹이 형성")
