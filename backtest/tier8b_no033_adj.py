"""Tier 8B — 033100 제외 환경에서 v80.6 인접 안정성

v80.6 plateau 기준 + 인접 13 변형 → 033100 제외 환경에서 Cal 분포 + CV
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT = Path(__file__).parent.parent

TSIM_ORIG = None
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
    tsim_orig = TurboSimulator({d: boost_rk[d] for d in dates_74}, dates_74, ohlcv)
    boost_rk_no033 = {d: [r for r in boost_rk[d] if r['ticker'] != '033100'] for d in dates_74}
    tsim_no033 = TurboSimulator(boost_rk_no033, dates_74, ohlcv)
    return tsim_orig, tsim_no033, regime


def worker_init():
    global TSIM_ORIG, TSIM_NO033, REGIME
    print(f'[w {os.getpid()}] load...', flush=True)
    t0 = time.time()
    TSIM_ORIG, TSIM_NO033, REGIME = load_all()
    print(f'[w {os.getpid()}] done ({time.time()-t0:.1f}s)', flush=True)


GS = ('rev_z', 'oca_z', None, None, None, None)
DEFENSE_T4 = {'v':0.35,'q':0.15,'g':0.15,'m':0.35,'g_rev':0.8,
              'entry':3,'exit':6,'slots':4,'mom':'6m-1m'}


def run_combo(params):
    name, boost_p, sl, ts, env = params
    sim = TSIM_NO033 if env == 'no033' else TSIM_ORIG
    try:
        r = sim.run_regime(defense_params=DEFENSE_T4, offense_params=boost_p,
                           regime_dict=REGIME, trailing_stop=ts, stop_loss=sl,
                           g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
                           g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
                           g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
                           g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
        return {'name': name, 'env': env,
                'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']}
    except Exception as e:
        return {'name': name, 'env': env, 'cal':0, 'cagr':0, 'mdd':99}


def main():
    print('=== Tier 8B — v80.6 + 인접 (033100 제외 환경 안정성) ===', flush=True)

    def bp(e, s, x, gr):
        return {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':gr,
                'entry':e,'exit':x,'slots':s,'mom':'12m'}

    candidates = [
        ('v80.6 plateau', bp(2, 5, 6, 0.5), -0.10, -0.08),
        # 인접
        ('adj: sb4',       bp(2, 4, 6, 0.5), -0.10, -0.08),
        ('adj: sb6',       bp(2, 6, 6, 0.5), -0.10, -0.08),
        ('adj: sb7',       bp(2, 7, 6, 0.5), -0.10, -0.08),
        ('adj: x5',        bp(2, 5, 5, 0.5), -0.10, -0.08),
        ('adj: x7',        bp(2, 5, 7, 0.5), -0.10, -0.08),
        ('adj: gr0.4',     bp(2, 5, 6, 0.4), -0.10, -0.08),
        ('adj: gr0.6',     bp(2, 5, 6, 0.6), -0.10, -0.08),
        ('adj: SL-8',      bp(2, 5, 6, 0.5), -0.08, -0.08),
        ('adj: SL-12',     bp(2, 5, 6, 0.5), -0.12, -0.08),
        ('adj: TS-7',      bp(2, 5, 6, 0.5), -0.10, -0.07),
        ('adj: TS-10',     bp(2, 5, 6, 0.5), -0.10, -0.10),
    ]

    combos = []
    for env in ['orig', 'no033']:
        for name, b, sl, ts in candidates:
            combos.append((name, b, sl, ts, env))
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

    print(f'\n=== 완료: {time.time()-t_start:.1f}초 ===\n')

    df = pd.DataFrame(results)
    pivot = df.pivot_table(values='cal', index='name', columns='env').reset_index()
    pivot['delta'] = pivot['orig'] - pivot['no033']

    # 원본 순서 유지
    name_order = [c[0] for c in candidates]
    pivot['order'] = pivot['name'].apply(lambda x: name_order.index(x) if x in name_order else 99)
    pivot = pivot.sort_values('order')

    print('=' * 70)
    print(f'{"name":<20} {"orig Cal":>10} {"no033 Cal":>10} {"delta":>8}')
    print('-' * 70)
    for _, r in pivot.iterrows():
        print(f'{r["name"]:<20} {r.orig:>10.2f} {r.no033:>10.2f} {r.delta:>8.2f}')

    # CV (033100 환경별)
    orig_cals = pivot['orig'].tolist()
    no033_cals = pivot['no033'].tolist()
    cv_orig = np.std(orig_cals) / np.mean(orig_cals)
    cv_no033 = np.std(no033_cals) / np.mean(no033_cals)
    print(f'\n=== 인접 안정성 (CV) ===')
    print(f'  orig 환경 ({len(orig_cals)} 후보):')
    print(f'    평균: {np.mean(orig_cals):.2f}, 표준편차: {np.std(orig_cals):.2f}')
    print(f'    CV: {cv_orig:.3f} {"PASS" if cv_orig < 0.30 else "FAIL"}')
    print(f'  no033 환경 ({len(no033_cals)} 후보):')
    print(f'    평균: {np.mean(no033_cals):.2f}, 표준편차: {np.std(no033_cals):.2f}')
    print(f'    CV: {cv_no033:.3f} {"PASS" if cv_no033 < 0.30 else "FAIL"}')

    msg = '<b>[Tier 8B — 033100 제외 환경 인접 안정성]</b>\n\n'
    msg += f'<b>v80.6 plateau:</b>\n  orig {pivot[pivot.name=="v80.6 plateau"].orig.iloc[0]:.2f} / no033 {pivot[pivot.name=="v80.6 plateau"].no033.iloc[0]:.2f}\n\n'
    msg += f'<b>인접 CV:</b>\n  orig 환경: {cv_orig:.3f} {"PASS" if cv_orig < 0.30 else "FAIL"}\n  no033 환경: {cv_no033:.3f} {"PASS" if cv_no033 < 0.30 else "FAIL"}\n'
    send_tg(msg)
    print('telegram sent')


if __name__ == '__main__':
    main()
