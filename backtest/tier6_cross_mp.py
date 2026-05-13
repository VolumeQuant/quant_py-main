"""Tier 6 — 교차검증 (regime × boost × defense)

격자:
  regime: MA170/8d, MA170/5d, MA200/10d, MA250/7d, MA250/8d (Top 5)
  boost: v80.5 plateau + 인접 변형 (Top 5)
  defense: baseline + Tier 4 top (Top 3)

총 5×5×3 = 75 조합

목적:
  - Tier 1~3 boost가 MA250 기준에서도 최적인지 확인
  - 만약 다른 boost가 더 좋으면 → 재최적 트리거
  - 동일 최적이면 → A 가설 확정 → 통합 production
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from pathlib import Path
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT = Path(__file__).parent.parent

TSIM = None
KOSPI = None
MA_CACHE = None
DATES_74 = None


def load_rankings(dirs):
    data = {}
    for d in dirs:
        d = Path(d)
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8 or not k.isdigit(): continue
            if k not in data:
                with open(fp, 'r', encoding='utf-8') as f:
                    data[k] = json.load(f)
    return data


def load_all():
    from turbo_simulator import TurboSimulator
    boost_rd = load_rankings([PROJECT / 'state'])
    defense_rd = load_rankings([PROJECT / 'state' / 'defense'])
    all_dates = sorted(set(boost_rd) & set(defense_rd))
    boost_rk = {d: boost_rd[d]['rankings'] for d in all_dates}
    dates_74 = [d for d in all_dates if '20190102' <= d <= '20260512']
    ohlcv = pd.read_parquet(PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet').replace(0, np.nan)
    kdf = pd.read_parquet(PROJECT / 'data_cache' / 'kospi_yf.parquet')
    kospi = kdf.iloc[:, 0].copy()
    for c in kdf.columns[1:]:
        kospi = kospi.fillna(kdf[c])
    kospi = kospi.dropna()
    ma_cache = {p: kospi.rolling(p).mean() for p in [150, 170, 200, 250]}
    return TurboSimulator({d: boost_rk[d] for d in dates_74}, dates_74, ohlcv), kospi, ma_cache, dates_74


def worker_init():
    global TSIM, KOSPI, MA_CACHE, DATES_74
    print(f'[w {os.getpid()}] load...', flush=True)
    t0 = time.time()
    TSIM, KOSPI, MA_CACHE, DATES_74 = load_all()
    print(f'[w {os.getpid()}] done ({time.time()-t0:.1f}s)', flush=True)


def calc_regime(ma_period, confirm):
    ma = MA_CACHE[ma_period]
    reg = {}; md = False; stk = 0; ss = None
    for d in DATES_74:
        ts = pd.Timestamp(d); kv = KOSPI.get(ts); mv = ma.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg


GS = ('rev_z', 'oca_z', None, None, None, None)


def run_combo(params):
    regime_name, ma_p, conf, boost_name, b_p, defense_name, d_p, sl, ts = params
    reg = calc_regime(ma_p, conf)
    try:
        r = TSIM.run_regime(defense_params=d_p, offense_params=b_p,
                            regime_dict=reg, trailing_stop=ts, stop_loss=sl,
                            g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
                            g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
                            g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
                            g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
        return {'regime': regime_name, 'boost': boost_name, 'defense': defense_name,
                'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'],
                'sharpe': r['sharpe'], 'sortino': r['sortino']}
    except Exception as e:
        return {'regime': regime_name, 'boost': boost_name, 'defense': defense_name,
                'cal':0,'cagr':0,'mdd':99,'sharpe':0,'sortino':0,'err':str(e)[:50]}


def main():
    print('=== Tier 6 — 교차검증 (MP 3워커) ===', flush=True)

    # 5 regime
    REGIMES = [
        ('MA170/8d', 170, 8),   # 현 baseline
        ('MA170/5d', 170, 5),
        ('MA200/10d', 200, 10),
        ('MA250/7d', 250, 7),
        ('MA250/8d', 250, 8),   # Tier 5 best
    ]

    # 5 boost (Top 5)
    BOOSTS = [
        ('v80.5_plateau', {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.5,
                           'entry':2,'exit':6,'slots':5,'mom':'12m'}, -0.10, -0.08),
        ('v80.5_TS10', {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.5,
                        'entry':2,'exit':6,'slots':5,'mom':'12m'}, -0.10, -0.10),
        ('Tier1_best', {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.6,
                        'entry':2,'exit':6,'slots':5,'mom':'12m'}, -0.07, -0.10),
        ('v80.5_gr0.6', {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.6,
                         'entry':2,'exit':6,'slots':5,'mom':'12m'}, -0.10, -0.08),
        ('v80.5_gr0.4', {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.4,
                         'entry':2,'exit':6,'slots':5,'mom':'12m'}, -0.10, -0.08),
    ]

    # 3 defense
    DEFENSES = [
        ('baseline', {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
                      'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}),
        ('Tier4_best', {'v':0.35,'q':0.15,'g':0.15,'m':0.35,'g_rev':0.8,
                        'entry':3,'exit':6,'slots':4,'mom':'6m-1m'}),
        ('Tier4_alt', {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.8,
                       'entry':3,'exit':6,'slots':4,'mom':'6m-1m'}),
    ]

    combos = []
    for (rn, mp, conf), (bn, bp, sl, ts), (dn, dp) in product(REGIMES, BOOSTS, DEFENSES):
        combos.append((rn, mp, conf, bn, bp, dn, dp, sl, ts))
    print(f'총 {len(combos)} 조합 (5 regime × 5 boost × 3 defense)', flush=True)

    from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
    def send_tg(msg):
        if len(msg) > 4096: msg = msg[:4090] + '...'
        try:
            requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                          data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
        except: pass

    results = []
    t_start = time.time()
    with ProcessPoolExecutor(max_workers=3, initializer=worker_init) as ex:
        futures = {ex.submit(run_combo, c): c for c in combos}
        done = 0
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if done % 20 == 0 or done == len(combos):
                elapsed = time.time() - t_start
                avg = elapsed / done
                remain = avg * (len(combos) - done) / 60
                print(f'  {done}/{len(combos)} ({elapsed/60:.1f}분 경과, {remain:.1f}분 남음)', flush=True)

    wall = time.time() - t_start
    print(f'\n=== 완료: {wall/60:.1f}분 ===\n', flush=True)

    df = pd.DataFrame(results)
    df_sorted = df.sort_values('cal', ascending=False)

    print('=' * 100)
    print(f'{"순위":>3} {"regime":>12} {"boost":>16} {"defense":>14} {"Cal":>6} {"CAGR":>6} {"MDD":>6} {"Sharpe":>7}')
    print('-' * 100)
    for i, (_, r) in enumerate(df_sorted.head(25).iterrows(), 1):
        print(f'{i:>3} {r.regime:>12} {r.boost:>16} {r.defense:>14} '
              f'{r.cal:>6.2f} {r.cagr:>6.1f} {r.mdd:>6.1f} {r.sharpe:>7.2f}')

    # regime별 best boost+defense 패턴 확인
    print(f'\n=== regime별 best (boost+defense 최적이 같은지) ===')
    for rn, _, _ in REGIMES:
        sub = df[df.regime == rn].sort_values('cal', ascending=False).head(3)
        print(f'\n  {rn}:')
        for _, r in sub.iterrows():
            print(f'    {r.boost} + {r.defense}: Cal {r.cal:.2f}')

    # boost별 평균
    print(f'\n=== boost별 평균 Cal ===')
    for b in df.boost.unique():
        print(f'  {b}: {df[df.boost==b].cal.mean():.2f}')

    print(f'\n=== defense별 평균 Cal ===')
    for d in df.defense.unique():
        print(f'  {d}: {df[df.defense==d].cal.mean():.2f}')

    print(f'\n=== regime별 평균 Cal ===')
    for r in df.regime.unique():
        print(f'  {r}: {df[df.regime==r].cal.mean():.2f}')

    df.to_csv('C:/dev/_tier6_results_20260513.csv', index=False)
    print(f'\n저장: C:/dev/_tier6_results_20260513.csv')

    top10 = df_sorted.head(10)
    msg = f'<b>[Tier 6 — 교차검증 75 조합]</b>\n\n{wall/60:.1f}분\n\n<b>Top 10:</b>\n'
    for i, (_, r) in enumerate(top10.iterrows(), 1):
        msg += f'{i}. {r.regime}/{r.boost}/{r.defense}: Cal={r.cal:.2f} CAGR={r.cagr:.0f}%\n'
    send_tg(msg)
    print('telegram sent')


if __name__ == '__main__':
    main()
