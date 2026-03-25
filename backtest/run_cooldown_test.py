"""손절 후 쿨다운 백테스트 — 쿨다운 0/3/5/7/10일 비교"""
import sys, io, os, glob, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
from production_simulator import ProductionSimulator

CACHE = r'C:\dev\data_cache'
t0 = time.time()

# 데이터 로드
all_rankings = {}
for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{year}/ranking_*.json'))):
        date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[date] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())

ohlcv_file = sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')))[-1]
prices = pd.read_parquet(ohlcv_file).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))
print(f'데이터: {len(dates)}거래일')

# v70 파라미터
V, Q, G, M = 0.20, 0.20, 0.30, 0.30
G_REV = 0.7
ENTRY, EXIT, SLOTS = 5, 15, 7
STOP_LOSS = -0.10

cooldowns = [0, 3, 5, 7, 10, 15, 20]

print(f'\n=== 쿨다운 백테스트 ({len(cooldowns)}개) ===')
print(f'전략: V{int(V*100)}Q{int(Q*100)}G{int(G*100)}M{int(M*100)} rank≤{ENTRY} rank>{EXIT} 슬롯{SLOTS} 손절{int(STOP_LOSS*100)}%')
print()

# ProductionSimulator에 쿨다운이 없으므로 직접 시뮬레이션
for cd in cooldowns:
    sim = ProductionSimulator(all_rankings, dates, prices, bench)

    portfolio = {}  # ticker → entry_price
    cooldown_map = {}  # ticker → cooldown_end_date_index
    daily_rets = []
    holdings_count = []
    stop_count = 0
    reentry_blocked = 0

    for i, date in enumerate(dates):
        if i < 2:
            daily_rets.append(0)
            holdings_count.append(0)
            continue

        d0, d1, d2 = dates[i], dates[i-1], dates[i-2]

        # 일간 수익률
        cur_ts = pd.Timestamp(date)
        prev_ts = pd.Timestamp(dates[i-1])
        if portfolio and cur_ts in prices.index and prev_ts in prices.index:
            rets = []
            for tk in portfolio:
                if tk in prices.columns:
                    cp = prices.loc[cur_ts, tk]
                    pp = prices.loc[prev_ts, tk]
                    if pd.notna(cp) and pd.notna(pp) and pp > 0:
                        rets.append(cp / pp - 1)
            daily_rets.append(np.mean(rets) if rets else 0)
        else:
            daily_rets.append(0)

        # 스코어링
        scored_t0 = sim._reweight(all_rankings.get(d0, []), V, Q, G, M, G_REV)
        scored_t1 = sim._reweight(all_rankings.get(d1, []), V, Q, G, M, G_REV)
        scored_t2 = sim._reweight(all_rankings.get(d2, []), V, Q, G, M, G_REV)
        pipeline = sim._compute_status(scored_t0, scored_t1, scored_t2, 20)
        status_map = {s['ticker']: s for s in pipeline}

        # 손절
        for tk in list(portfolio.keys()):
            if tk in prices.columns and cur_ts in prices.index:
                cp = prices.loc[cur_ts, tk]
                ep = portfolio[tk]
                if pd.notna(cp) and ep > 0 and (cp / ep - 1) <= STOP_LOSS:
                    del portfolio[tk]
                    stop_count += 1
                    if cd > 0:
                        cooldown_map[tk] = i + cd  # i + cd일까지 재진입 금지

        # 이탈
        for tk in list(portfolio.keys()):
            s = status_map.get(tk)
            if s is None or s['weighted_rank'] > EXIT:
                del portfolio[tk]

        # 진입
        for s in pipeline:
            tk = s['ticker']
            if tk in portfolio or s['price'] is None or s['status'] != 'verified':
                continue
            if len(portfolio) >= SLOTS:
                break
            if s['weighted_rank'] <= ENTRY:
                # 쿨다운 체크
                if cd > 0 and tk in cooldown_map and i < cooldown_map[tk]:
                    reentry_blocked += 1
                    continue
                portfolio[tk] = s['price']

        holdings_count.append(len(portfolio))

    # 메트릭 계산
    arr = np.array(daily_rets)
    eq = np.cumprod(1 + arr)
    n = len(arr)
    cagr = (eq[-1] ** (252 / max(n, 1)) - 1) * 100
    sharpe = arr.mean() / arr.std() * np.sqrt(252) if arr.std() > 0 else 0
    down = arr[arr < 0]
    sortino = (arr.mean() / down.std() * np.sqrt(252)) if len(down) > 0 and down.std() > 0 else sharpe
    peak = np.maximum.accumulate(np.concatenate([[1], eq]))
    dd = (np.concatenate([[1], eq]) - peak) / peak
    mdd = abs(dd.min()) * 100
    b_rets = [0, 0]
    for j in range(2, len(dates)):
        t_j = pd.Timestamp(dates[j])
        t_j1 = pd.Timestamp(dates[j-1])
        if t_j in bench.index and t_j1 in bench.index:
            bc = bench.loc[t_j, 'kospi']
            bp = bench.loc[t_j1, 'kospi']
            if pd.notna(bc) and pd.notna(bp) and bp > 0:
                b_rets.append(bc / bp - 1)
            else:
                b_rets.append(0)
        else:
            b_rets.append(0)
    b_arr = np.array(b_rets)
    b_eq = np.cumprod(1 + b_arr)
    b_cagr = (b_eq[-1] ** (252 / max(len(b_arr), 1)) - 1) * 100
    avg_h = np.mean(holdings_count[2:]) if holdings_count[2:] else 0

    print(f'  CD={cd:2d}일  CAGR={cagr:5.1f}%  Sharpe={sharpe:.3f}  Sortino={sortino:.3f}  '
          f'MDD={mdd:5.1f}%  Alpha={cagr-b_cagr:+.1f}%  Hold={avg_h:.1f}  '
          f'손절={stop_count}  재진입차단={reentry_blocked}')

elapsed = time.time() - t0
print(f'\n완료: {elapsed:.0f}초')
