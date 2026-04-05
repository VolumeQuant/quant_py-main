"""진입/퇴출 기준 그리드 서치 — 값 기반 vs 순위 기반, 전체 ranking wr 퇴출"""
import os, json, glob, time
import pandas as pd
import numpy as np
from pathlib import Path

STATE_DIR = Path(__file__).parent / 'state'
OHLCV_DIR = Path(__file__).parent / 'data_cache'

# ranking 로드 (bt_2020~2025 + 프로덕션)
print("데이터 로딩...")
all_data = {}
for bt_dir in sorted(glob.glob(str(STATE_DIR / 'bt_20*'))):
    for fp in glob.glob(os.path.join(bt_dir, 'ranking_*.json')):
        d = os.path.basename(fp).replace('ranking_', '').replace('.json', '')
        with open(fp, 'r', encoding='utf-8') as fh:
            all_data[d] = json.load(fh)
for fp in glob.glob(str(STATE_DIR / 'ranking_*.json')):
    d = os.path.basename(fp).replace('ranking_', '').replace('.json', '')
    with open(fp, 'r', encoding='utf-8') as fh:
        all_data[d] = json.load(fh)
dates = sorted(all_data.keys())

# OHLCV 가격
ohlcv_files = sorted(glob.glob(str(OHLCV_DIR / 'all_ohlcv_*.parquet')))
full_files = [f for f in ohlcv_files if '_full' in f]
if full_files:
    ohlcv_files = full_files
if ohlcv_files:
    parts = [pd.read_parquet(f).replace(0, np.nan) for f in ohlcv_files]
    ohlcv = pd.concat(parts).groupby(level=0).first()
else:
    ohlcv = pd.DataFrame()

def get_price(ticker, date_str):
    ts = pd.Timestamp(date_str)
    if not ohlcv.empty and ts in ohlcv.index and ticker in ohlcv.columns:
        v = ohlcv.loc[ts, ticker]
        if pd.notna(v) and v > 0:
            return v
    return 0

# score_100 계산 (ranking_manager와 동일)
def calc_score_100(tk, r0_map, r1_map, r2_map):
    def _get_score(rmap, ticker):
        if not rmap:
            return 0
        item = rmap.get(ticker)
        if not item:
            return 0
        return item.get('score', 0)
    s0 = _get_score(r0_map, tk)
    s1 = _get_score(r1_map, tk)
    s2 = _get_score(r2_map, tk)
    ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
    return max(0.0, min(100.0, (ws + 0.7) / 2.4 * 100))


def simulate(entry_mode, exit_mode, entry_param, exit_param, max_slots=7):
    """
    entry_mode: 'value' (wr <= param), 'rank' (top N), 'score' (score_100 >= param)
    exit_mode:  'value' (wr > param), 'rank' (top N 밖), 'score' (score_100 < param)
    """
    portfolio = {}
    equity = 1.0
    start_date = None
    max_dd = 0
    peak = 1.0

    for i in range(len(dates)):
        d0 = dates[i]
        d1 = dates[i - 1] if i >= 1 else None
        d2 = dates[i - 2] if i >= 2 else None

        # 일간 수익률
        if i >= 1 and portfolio:
            daily_rets = []
            for tk in portfolio:
                pp = get_price(tk, dates[i - 1])
                cp = get_price(tk, d0)
                if pp > 0 and cp > 0:
                    daily_rets.append(cp / pp - 1)
            if daily_rets:
                equity *= (1 + sum(daily_rets) / len(daily_rets))
                if equity > peak:
                    peak = equity
                dd = (equity / peak - 1) * 100
                if dd < max_dd:
                    max_dd = dd

        if i < 2:
            continue

        # 손절 -10%
        for tk in list(portfolio.keys()):
            cp = get_price(tk, d0)
            ep = portfolio[tk]
            if cp > 0 and ep > 0 and (cp / ep - 1) <= -0.10:
                del portfolio[tk]

        r0 = all_data[d0].get('rankings', [])
        r1 = all_data[d1].get('rankings', [])
        r2 = all_data[d2].get('rankings', [])

        # 전체 ranking 맵
        all_t0 = {r['ticker']: r for r in r0}
        all_t1 = {r['ticker']: r for r in r1}
        all_t2 = {r['ticker']: r for r in r2}

        def _wr(tk):
            if tk not in all_t0:
                return 999
            cr0 = all_t0[tk].get('composite_rank', all_t0[tk].get('rank', 999))
            cr1 = all_t1[tk].get('composite_rank', all_t1[tk].get('rank', 999)) if tk in all_t1 else 999
            cr2 = all_t2[tk].get('composite_rank', all_t2[tk].get('rank', 999)) if tk in all_t2 else 999
            return cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2

        # === 퇴출 ===
        for tk in list(portfolio.keys()):
            if exit_mode == 'value':
                if _wr(tk) > exit_param:
                    del portfolio[tk]
            elif exit_mode == 'rank':
                if _wr(tk) > exit_param:
                    del portfolio[tk]
            elif exit_mode == 'score':
                sc = calc_score_100(tk, all_t0, all_t1, all_t2)
                if sc < exit_param:
                    del portfolio[tk]

        # === 진입 후보: 3일 교집합 ===
        top20_t0 = {r['ticker']: r for r in r0 if r.get('composite_rank', r['rank']) <= 20}
        top20_t1 = {r['ticker']: r for r in r1 if r.get('composite_rank', r['rank']) <= 20}
        top20_t2 = {r['ticker']: r for r in r2 if r.get('composite_rank', r['rank']) <= 20}
        common = set(top20_t0) & set(top20_t1) & set(top20_t2)

        verified = []
        for tk in common:
            cr0 = top20_t0[tk].get('composite_rank', top20_t0[tk]['rank'])
            cr1 = top20_t1[tk].get('composite_rank', top20_t1[tk]['rank'])
            cr2 = top20_t2[tk].get('composite_rank', top20_t2[tk]['rank'])
            wr = cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2
            sc = calc_score_100(tk, all_t0, all_t1, all_t2)
            verified.append({'ticker': tk, 'weighted_rank': wr, 'score_100': sc})
        verified.sort(key=lambda x: x['weighted_rank'])

        # === 진입 ===
        if entry_mode == 'value':
            candidates = [v for v in verified if v['weighted_rank'] <= entry_param]
        elif entry_mode == 'rank':
            candidates = verified[:entry_param]
        elif entry_mode == 'score':
            candidates = [v for v in verified if v['score_100'] >= entry_param]

        for v in candidates:
            if v['ticker'] in portfolio:
                continue
            if len(portfolio) >= max_slots:
                break
            ep = get_price(v['ticker'], d0)
            if ep > 0:
                portfolio[v['ticker']] = ep
                if start_date is None:
                    start_date = d0

    if start_date is None:
        return None
    days = len([d for d in dates if d >= start_date])
    years = days / 252
    total = equity
    cagr = (total ** (1 / years) - 1) * 100 if years > 0 and total > 0 else 0
    return {
        'cum': (total - 1) * 100,
        'cagr': cagr,
        'mdd': max_dd,
        'days': days,
        'holdings': len(portfolio),
    }


print(f"데이터: {dates[0]} ~ {dates[-1]} ({len(dates)}거래일)\n")
t0 = time.time()

# 그리드
results = []

# 1. 값 기반 (현행 스타일)
for entry in [3, 4, 5, 6, 7, 8, 10]:
    for exit_ in [10, 12, 15, 18, 20, 25]:
        if exit_ <= entry:
            continue
        for slots in [5, 7, 10]:
            r = simulate('value', 'value', entry, exit_, slots)
            if r:
                results.append({
                    'type': '값', 'entry': f'wr≤{entry}', 'exit': f'wr>{exit_}',
                    'slots': slots, **r})

# 2. 순위 기반 (포지션)
for entry in [3, 4, 5, 6, 7, 8, 10]:
    for exit_ in [10, 12, 15, 18, 20, 25]:
        if exit_ <= entry:
            continue
        for slots in [5, 7, 10]:
            r = simulate('rank', 'value', entry, exit_, slots)
            if r:
                results.append({
                    'type': '순위', 'entry': f'top{entry}', 'exit': f'wr>{exit_}',
                    'slots': slots, **r})

# 3. 점수 기반
for entry_sc in [65, 68, 70, 72, 74, 76, 78, 80]:
    for exit_sc in [55, 58, 60, 62, 65, 68]:
        if exit_sc >= entry_sc:
            continue
        for slots in [5, 7, 10]:
            r = simulate('score', 'score', entry_sc, exit_sc, slots)
            if r:
                results.append({
                    'type': '점수', 'entry': f'sc≥{entry_sc}', 'exit': f'sc<{exit_sc}',
                    'slots': slots, **r})

# 4. 하이브리드: 순위 진입 + 점수 퇴출
for entry in [3, 4, 5, 6, 7, 8, 10]:
    for exit_sc in [55, 58, 60, 62, 65, 68]:
        for slots in [5, 7, 10]:
            r = simulate('rank', 'score', entry, exit_sc, slots)
            if r:
                results.append({
                    'type': '순위+점수', 'entry': f'top{entry}', 'exit': f'sc<{exit_sc}',
                    'slots': slots, **r})

# 5. 하이브리드: 점수 진입 + 순위(값) 퇴출
for entry_sc in [65, 68, 70, 72, 74, 76, 78, 80]:
    for exit_ in [10, 12, 15, 18, 20, 25]:
        for slots in [5, 7, 10]:
            r = simulate('score', 'value', entry_sc, exit_, slots)
            if r:
                results.append({
                    'type': '점수+값', 'entry': f'sc≥{entry_sc}', 'exit': f'wr>{exit_}',
                    'slots': slots, **r})

# 6. 하이브리드: 값 진입 + 점수 퇴출
for entry in [3, 4, 5, 6, 7, 8, 10]:
    for exit_sc in [55, 58, 60, 62, 65, 68]:
        for slots in [5, 7, 10]:
            r = simulate('value', 'score', entry, exit_sc, slots)
            if r:
                results.append({
                    'type': '값+점수', 'entry': f'wr≤{entry}', 'exit': f'sc<{exit_sc}',
                    'slots': slots, **r})

elapsed = time.time() - t0
print(f"완료: {len(results)}개 조합, {elapsed:.0f}초\n")

# CAGR 기준 정렬
results.sort(key=lambda x: -x['cagr'])

print(f"{'#':>3} {'유형':>4} {'진입':<10} {'퇴출':<10} {'슬롯':>3} {'누적':>10} {'CAGR':>7} {'MDD':>7} {'보유':>3}")
print('-' * 70)
for i, r in enumerate(results[:30]):
    marker = ' ◀' if r['type'] == '값' and r['entry'] == 'wr≤5' and r['exit'] == 'wr>15' and r['slots'] == 7 else ''
    print(f"{i+1:>3} {r['type']:>4} {r['entry']:<10} {r['exit']:<10} {r['slots']:>3} "
          f"{r['cum']:>+9.1f}% {r['cagr']:>+6.1f}% {r['mdd']:>6.1f}% {r['holdings']:>3}{marker}")

# 유형별 1등
print(f"\n{'='*70}")
print("유형별 CAGR 1등:")
for t in ['값', '순위', '점수', '순위+점수', '점수+값', '값+점수']:
    best = [r for r in results if r['type'] == t]
    if best:
        b = best[0]
        print(f"  {t}: {b['entry']} / {b['exit']} / 슬롯{b['slots']}  →  CAGR {b['cagr']:+.1f}%  MDD {b['mdd']:.1f}%")
