"""국면 전환 단일 트랙 시뮬레이션

HY 분면에 따라 매일 Core/Boost 파라미터 전환.
하루 하루는 하나의 전략만 운용 (원 트랙).
"""
import sys, io, json, glob, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main/backtest')

import pandas as pd, numpy as np
from pathlib import Path
from scipy.stats import norm
from turbo_simulator import TurboSimulator, TurboRunner

PROJECT = Path('C:/dev/claude-code/quant_py-main')
CACHE_DIR = PROJECT / 'data_cache'

_ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
_full_files = [f for f in _ohlcv_files if '_full' in f.stem]
if _full_files:
    _ohlcv_files = _full_files
prices = pd.read_parquet(
    sorted(_ohlcv_files, key=lambda f: f.stem.split('_')[2])[0]
).replace(0, np.nan)

# bt_2b (rev_accel)
bt2b_r = {}
for fp in sorted((PROJECT / 'state' / 'bt_2b').glob('ranking_*.json')):
    d = fp.stem.replace('ranking_', '')
    with open(fp, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    bt2b_r[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt2b_d = sorted(bt2b_r.keys())

# 일반 bt
bt_r = {}
for y in range(2021, 2026):
    for fp in sorted((PROJECT / 'state' / f'bt_{y}').glob('ranking_*.json')):
        d = fp.stem.replace('ranking_', '')
        with open(fp, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        bt_r[d] = data.get('rankings', data) if isinstance(data, dict) else data

# Regime
regime_df = pd.read_parquet(CACHE_DIR / 'regime_daily.parquet')
regime_map = {}
for idx, row in regime_df.iterrows():
    d = idx.strftime('%Y%m%d')
    q = row.get('quadrant')
    vr = row.get('vix_regime')
    if q:
        regime_map[d] = (q, vr)


def reweight_rankings(rankings_list, v_w, q_w, g_w, m_w, g_rev):
    """ranking에서 팩터 점수를 재가중해서 composite_rank 재계산"""
    scored = []
    for r in rankings_list:
        vs = r.get('value_s', 0) or 0
        qs = r.get('quality_s', 0) or 0
        rev_z = r.get('rev_z', 0) or 0
        oca_z = r.get('oca_z', 0) or 0
        ms = r.get('momentum_s', 0) or 0

        # Growth 재계산
        g_raw = g_rev * rev_z + (1 - g_rev) * oca_z
        gs = r.get('growth_s', 0) or 0  # fallback

        new_score = v_w * vs + q_w * qs + g_w * g_raw + m_w * ms
        scored.append((new_score, r))

    scored.sort(key=lambda x: -x[0])
    result = []
    for i, (sc, r) in enumerate(scored):
        nr = r.copy()
        nr['composite_rank'] = i + 1
        nr['score'] = sc
        result.append(nr)
    return result


def simulate_regime_switch(dates, regime_rules, core_cfg, boost_cfg,
                            stop_loss=-0.10):
    """
    regime_rules: dict mapping quadrant -> 'core' or 'boost'
    각 날짜의 regime에 따라 Core/Boost 파라미터로 ranking 재가중 + 진입/퇴출
    """
    portfolio = {}  # ticker -> entry_price
    equity = 1.0
    peak = 1.0
    max_dd = 0
    daily_rets = []
    trade_count = 0

    def get_price(ticker, date_str):
        ts = pd.Timestamp(date_str)
        if ts in prices.index and ticker in prices.columns:
            v = prices.loc[ts, ticker]
            if pd.notna(v) and v > 0:
                return v
        return 0

    for i in range(len(dates)):
        d0 = dates[i]
        d1 = dates[i-1] if i >= 1 else None
        d2 = dates[i-2] if i >= 2 else None

        # 일간 수익률
        if i >= 1 and portfolio:
            rets = []
            for tk in portfolio:
                pp = get_price(tk, dates[i-1])
                cp = get_price(tk, d0)
                if pp > 0 and cp > 0:
                    rets.append(cp / pp - 1)
            if rets:
                day_ret = sum(rets) / len(rets)
                equity *= (1 + day_ret)
                if equity > peak:
                    peak = equity
                dd = (equity / peak - 1) * 100
                if dd < max_dd:
                    max_dd = dd
                daily_rets.append(day_ret)

        if i < 2:
            continue

        # 국면 결정
        regime = regime_map.get(d0)
        if regime:
            q_name = regime[0]
            strategy = regime_rules.get(q_name, 'core')
        else:
            strategy = 'core'

        cfg = core_cfg if strategy == 'core' else boost_cfg

        # ranking 가져오기 (Core는 bt_2b, Boost는 일반 bt)
        if strategy == 'core':
            r0 = bt2b_r.get(d0, {})
            r1 = bt2b_r.get(d1, {})
            r2 = bt2b_r.get(d2, {})
        else:
            r0 = bt_r.get(d0, bt2b_r.get(d0, {}))
            r1 = bt_r.get(d1, bt2b_r.get(d1, {}))
            r2 = bt_r.get(d2, bt2b_r.get(d2, {}))

        if isinstance(r0, dict):
            r0 = r0.get('rankings', r0) if 'rankings' in r0 else r0
        if isinstance(r1, dict):
            r1 = r1.get('rankings', r1) if 'rankings' in r1 else r1
        if isinstance(r2, dict):
            r2 = r2.get('rankings', r2) if 'rankings' in r2 else r2

        if not isinstance(r0, list) or not r0:
            continue

        # 재가중
        ranked0 = reweight_rankings(r0, cfg['v'], cfg['q'], cfg['g'], cfg['m'], cfg['g_rev'])
        ranked1 = reweight_rankings(r1, cfg['v'], cfg['q'], cfg['g'], cfg['m'], cfg['g_rev']) if isinstance(r1, list) and r1 else []
        ranked2 = reweight_rankings(r2, cfg['v'], cfg['q'], cfg['g'], cfg['m'], cfg['g_rev']) if isinstance(r2, list) and r2 else []

        # 손절
        for tk in list(portfolio.keys()):
            cp = get_price(tk, d0)
            ep = portfolio[tk]
            if cp > 0 and ep > 0 and (cp / ep - 1) <= stop_loss:
                del portfolio[tk]
                trade_count += 1

        # 퇴출: 전체 ranking에서 WR 계산
        all_t0 = {r['ticker']: r for r in ranked0}
        all_t1 = {r['ticker']: r for r in ranked1} if ranked1 else {}
        all_t2 = {r['ticker']: r for r in ranked2} if ranked2 else {}

        for tk in list(portfolio.keys()):
            if tk not in all_t0:
                del portfolio[tk]
                trade_count += 1
                continue
            cr0 = all_t0[tk].get('composite_rank', 999)
            cr1 = all_t1[tk].get('composite_rank', 999) if tk in all_t1 else 999
            cr2 = all_t2[tk].get('composite_rank', 999) if tk in all_t2 else 999
            wr = cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2
            if wr > cfg['exit']:
                del portfolio[tk]
                trade_count += 1

        # 진입: top20 교집합 + WR <= entry
        top20_0 = {r['ticker']: r for r in ranked0 if r['composite_rank'] <= 20}
        top20_1 = {r['ticker']: r for r in ranked1 if r['composite_rank'] <= 20} if ranked1 else {}
        top20_2 = {r['ticker']: r for r in ranked2 if r['composite_rank'] <= 20} if ranked2 else {}
        common = set(top20_0) & set(top20_1) & set(top20_2) if top20_1 and top20_2 else set()

        verified = []
        for tk in common:
            cr0 = top20_0[tk]['composite_rank']
            cr1 = top20_1[tk]['composite_rank']
            cr2 = top20_2[tk]['composite_rank']
            wr = cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2
            verified.append({'ticker': tk, 'weighted_rank': wr,
                             'price': top20_0[tk].get('price', 0)})
        verified.sort(key=lambda x: x['weighted_rank'])

        for v in verified[:cfg['entry']]:
            if v['ticker'] in portfolio:
                continue
            if len(portfolio) >= cfg['slots']:
                break
            ep = get_price(v['ticker'], d0)
            if ep > 0:
                portfolio[v['ticker']] = ep
                trade_count += 1

    if not daily_rets:
        return None

    days = len(daily_rets)
    years = days / 252
    cagr = (equity ** (1/years) - 1) * 100 if years > 0 else 0
    mean_r = np.mean(daily_rets)
    std_r = np.std(daily_rets, ddof=1)
    sharpe = (mean_r / std_r) * (252**0.5) if std_r > 0 else 0

    return {
        'cagr': cagr, 'mdd': max_dd, 'calmar': cagr / abs(max_dd) if max_dd != 0 else 0,
        'sharpe': sharpe, 'trades': trade_count, 'days': days,
    }


# 전략 설정
core_v25 = {'v': 0.25, 'q': 0.20, 'g': 0.35, 'm': 0.20, 'g_rev': 0.2, 'entry': 5, 'exit': 7, 'slots': 5}
boost = {'v': 0.15, 'q': 0.05, 'g': 0.65, 'm': 0.15, 'g_rev': 1.0, 'entry': 3, 'exit': 4, 'slots': 3}
golden1 = {'v': 0.20, 'q': 0.10, 'g': 0.45, 'm': 0.25, 'g_rev': 0.3, 'entry': 5, 'exit': 5, 'slots': 5}

# bt_2b 날짜 사용
dates = bt2b_d

t0 = time.time()

print('=' * 60)
print('  국면 전환 단일 트랙 시뮬레이션')
print('=' * 60)

def fmt(r):
    if r is None:
        return 'N/A'
    return f"CAGR={r['cagr']:>+6.1f}% MDD={r['mdd']:>5.1f}% Calmar={r['calmar']:>5.2f} Sharpe={r['sharpe']:>5.2f}"

# 테스트 조합들
switch_rules = [
    ('Core항상',    {'Q1': 'core', 'Q2': 'core', 'Q3': 'core', 'Q4': 'core'}),
    ('Boost항상',   {'Q1': 'boost', 'Q2': 'boost', 'Q3': 'boost', 'Q4': 'boost'}),
    ('Q1Q2=B Q3Q4=C', {'Q1': 'boost', 'Q2': 'boost', 'Q3': 'core', 'Q4': 'core'}),
    ('Q1=B 나머지=C', {'Q1': 'boost', 'Q2': 'core', 'Q3': 'core', 'Q4': 'core'}),
    ('Q1Q4=B Q2Q3=C', {'Q1': 'boost', 'Q2': 'core', 'Q3': 'core', 'Q4': 'boost'}),
    ('Q4=C 나머지=B', {'Q1': 'boost', 'Q2': 'boost', 'Q3': 'boost', 'Q4': 'core'}),
    ('Q3Q4=C 나머지=B', {'Q1': 'boost', 'Q2': 'boost', 'Q3': 'core', 'Q4': 'core'}),
]

# CoreV25 + Boost 조합
print('\n--- CoreV25 ↔ Boost 전환 ---')
for name, rules in switch_rules:
    r = simulate_regime_switch(dates, rules, core_v25, boost)
    print(f'  {name:<16}: {fmt(r)}')

# Golden1 + Boost 조합
print('\n--- Golden1 ↔ Boost 전환 ---')
for name, rules in switch_rules:
    r = simulate_regime_switch(dates, rules, golden1, boost)
    print(f'  {name:<16}: {fmt(r)}')

# 비교 기준
print('\n--- 비교 기준 (TurboSimulator) ---')
tsim_2b = TurboSimulator(bt2b_r, bt2b_d, prices)
tsim_bt = TurboSimulator(bt_r, sorted(bt_r.keys()), prices)

tsim_2b._ensure_cache(0.25, 0.20, 0.35, 0.20, 0.2, 20)
rr = TurboRunner(tsim_2b)
r = rr.run(5, 7, 5, corr_threshold=0.5)
print(f'  CoreV25 (Turbo):    {fmt(r)}')

tsim_2b._ensure_cache(0.20, 0.10, 0.45, 0.25, 0.3, 20)
rr = TurboRunner(tsim_2b)
r = rr.run(5, 5, 5, corr_threshold=None)
print(f'  Golden1-X5 (Turbo): {fmt(r)}')

tsim_bt._ensure_cache(0.15, 0.05, 0.65, 0.15, 1.0, 20)
rr = TurboRunner(tsim_bt)
r = rr.run(3, 4, 3, corr_threshold=None)
print(f'  Boost (Turbo):      {fmt(r)}')

print(f'\n소요: {(time.time()-t0)/60:.1f}분')
print('완료!')
