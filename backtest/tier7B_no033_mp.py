"""Tier 7B — 033100 제외 환경에서 entry/slots/exit 재최적

목적:
  033100 (제룡전기) 단일 종목 의존도 21% 완화 방안 탐색.
  같은 격자를 원본 / 033100 제외 환경 둘 다 측정 → 어떤 조합이 robust한지.

격자:
  entry: 2, 3
  slots: 3, 5, 7, 10
  exit: 4, 5, 6

24 조합 × 2 환경 = 48 조합
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
TSIM_NO033 = None
REGIME = None


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
    ma250 = kospi.rolling(250).mean()
    def calc_regime(td):
        reg = {}; md = False; stk = 0; ss = None
        for d in td:
            ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma250.get(ts)
            if kv is None or pd.isna(mv): reg[d] = md; continue
            s = kv > mv
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= 8 and md != s: md = s
            reg[d] = md
        return reg
    regime = calc_regime(dates_74)
    tsim = TurboSimulator({d: boost_rk[d] for d in dates_74}, dates_74, ohlcv)

    # 033100 제외 ranking (boost만 — defense는 그대로)
    boost_rk_no033 = {d: [r for r in boost_rk[d] if r['ticker'] != '033100'] for d in dates_74}
    tsim_no033 = TurboSimulator(boost_rk_no033, dates_74, ohlcv)
    return tsim, tsim_no033, regime


def worker_init():
    global TSIM, TSIM_NO033, REGIME
    print(f'[w {os.getpid()}] load...', flush=True)
    t0 = time.time()
    TSIM, TSIM_NO033, REGIME = load_all()
    print(f'[w {os.getpid()}] done ({time.time()-t0:.1f}s)', flush=True)


GS = ('rev_z', 'oca_z', None, None, None, None)
DEFENSE_V806 = {'v':0.35,'q':0.15,'g':0.15,'m':0.35,'g_rev':0.8,
                'entry':3,'exit':6,'slots':4,'mom':'6m-1m'}


def run_combo(params):
    env, entry, slots, exit_r = params
    sim = TSIM_NO033 if env == 'no033' else TSIM
    boost_p = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.5,
               'entry':entry,'exit':exit_r,'slots':slots,'mom':'12m'}
    try:
        r = sim.run_regime(defense_params=DEFENSE_V806, offense_params=boost_p,
                           regime_dict=REGIME, trailing_stop=-0.08, stop_loss=-0.10,
                           g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
                           g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
                           g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
                           g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
        return {'env': env, 'entry': entry, 'slots': slots, 'exit': exit_r,
                'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'], 'sharpe': r['sharpe']}
    except Exception as e:
        return {'env': env, 'entry': entry, 'slots': slots, 'exit': exit_r,
                'cal':0,'cagr':0,'mdd':99,'sharpe':0, 'err':str(e)[:50]}


def main():
    print('=== Tier 7B — 033100 의존 완화 격자 (MP 3워커) ===', flush=True)

    ENTRY = [2, 3]
    SLOTS = [3, 5, 7, 10]
    EXIT = [4, 5, 6]
    ENVS = ['orig', 'no033']

    combos = [(env, e, s, x) for env, e, s, x in product(ENVS, ENTRY, SLOTS, EXIT)]
    print(f'총 {len(combos)} 조합', flush=True)

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
        for fut in as_completed(futures):
            results.append(fut.result())

    wall = time.time() - t_start
    print(f'\n=== 완료: {wall/60:.1f}분 ===\n', flush=True)

    df = pd.DataFrame(results)
    # 환경별 비교
    pivot = df.pivot_table(values='cal', index=['entry','slots','exit'], columns='env').reset_index()
    pivot['delta'] = pivot['orig'] - pivot['no033']
    pivot['robust_score'] = pivot['no033'] - pivot['delta'] * 0.5  # 033100 의존 적을수록 robust

    pivot = pivot.sort_values('no033', ascending=False)
    print('=' * 90)
    print(f'{"entry":>5} {"slots":>5} {"exit":>4} {"orig":>6} {"no033":>6} {"delta":>6} {"robust":>7}')
    print('-' * 90)
    for _, r in pivot.iterrows():
        print(f'{r.entry:>5.0f} {r.slots:>5.0f} {r.exit:>4.0f} {r.orig:>6.2f} {r.no033:>6.2f} {r.delta:>6.2f} {r.robust_score:>7.2f}')

    print(f'\n=== 033100 의존 최소 Top 5 (no033 Cal 높고 delta 작음) ===')
    pivot_robust = pivot.sort_values('robust_score', ascending=False)
    for i, (_, r) in enumerate(pivot_robust.head(5).iterrows(), 1):
        print(f'{i}. e{int(r.entry)} s{int(r.slots)} x{int(r.exit)}: orig {r.orig:.2f} / no033 {r.no033:.2f} (delta {r.delta:.2f})')

    df.to_csv('C:/dev/_tier7B_results_20260513.csv', index=False)
    print(f'\n저장: C:/dev/_tier7B_results_20260513.csv')

    msg = '<b>[Tier 7B — 033100 의존 완화]</b>\n\n'
    msg += '<b>orig Cal Top 5:</b>\n'
    for i, (_, r) in enumerate(pivot.head(5).iterrows(), 1):
        msg += f'{i}. e{int(r.entry)}s{int(r.slots)}x{int(r.exit)}: {r.orig:.2f}(orig)/{r.no033:.2f}(no033)\n'
    msg += '\n<b>robust Top 5 (no033 Cal):</b>\n'
    for i, (_, r) in enumerate(pivot_robust.head(5).iterrows(), 1):
        msg += f'{i}. e{int(r.entry)}s{int(r.slots)}x{int(r.exit)}: {r.no033:.2f}(no033) delta={r.delta:.2f}\n'
    send_tg(msg)
    print('telegram sent')


if __name__ == '__main__':
    main()
