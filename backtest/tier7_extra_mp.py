"""Tier 7+ — A (단일 종목 제외) + 4 (boost MOM) + 5 (boost VQGM) + 6 (G_SUB factor)

모두 v80.6 기반 + 변경 1가지씩.
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
TSIM_NO033100 = None  # 033100 제외 ranking 사용
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

    # 033100 제외 ranking
    boost_rk_no033 = {}
    for d in dates_74:
        boost_rk_no033[d] = [r for r in boost_rk[d] if r['ticker'] != '033100']
    tsim_no033 = TurboSimulator(boost_rk_no033, dates_74, ohlcv)

    return tsim, tsim_no033, regime


def worker_init():
    global TSIM, TSIM_NO033100, REGIME
    print(f'[w {os.getpid()}] load...', flush=True)
    t0 = time.time()
    TSIM, TSIM_NO033100, REGIME = load_all()
    print(f'[w {os.getpid()}] done ({time.time()-t0:.1f}s)', flush=True)


# v80.6 base config
GS_DEFAULT = ('rev_z', 'oca_z', None, None, None, None)
DEFENSE_V806 = {'v':0.35,'q':0.15,'g':0.15,'m':0.35,'g_rev':0.8,
                'entry':3,'exit':6,'slots':4,'mom':'6m-1m'}


def run_combo(params):
    category, name, boost_p, defense_p, gs, tsim_kind = params
    sim = TSIM_NO033100 if tsim_kind == 'no033100' else TSIM
    try:
        r = sim.run_regime(defense_params=defense_p, offense_params=boost_p,
                           regime_dict=REGIME, trailing_stop=-0.08, stop_loss=-0.10,
                           g_sub1_o=gs[0],g_sub2_o=gs[1],g_sub3_o=gs[2],
                           g_w1_o=gs[3],g_w2_o=gs[4],g_w3_o=gs[5],
                           g_sub1_d=GS_DEFAULT[0],g_sub2_d=GS_DEFAULT[1],g_sub3_d=GS_DEFAULT[2],
                           g_w1_d=GS_DEFAULT[3],g_w2_d=GS_DEFAULT[4],g_w3_d=GS_DEFAULT[5])
        return {'cat': category, 'name': name,
                'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'],
                'sharpe': r['sharpe'], 'sortino': r['sortino']}
    except Exception as e:
        return {'cat': category, 'name': name,
                'cal':0,'cagr':0,'mdd':99,'sharpe':0,'sortino':0,'err':str(e)[:50]}


def main():
    print('=== Tier 7+ Extra — A + 4 + 5 + 6 (MP 3워커) ===', flush=True)

    BOOST_V806 = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.5,
                  'entry':2,'exit':6,'slots':5,'mom':'12m'}
    BASELINE_BOOST = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.6,
                      'entry':3,'exit':6,'slots':3,'mom':'12m'}
    BASELINE_DEF = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
                    'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}

    combos = []

    # === A. 단일 종목 (033100) 제외 ===
    combos.append(('A_033제외', 'baseline_no033100', BASELINE_BOOST, BASELINE_DEF, GS_DEFAULT, 'no033100'))
    combos.append(('A_033제외', 'v80.6_no033100', BOOST_V806, DEFENSE_V806, GS_DEFAULT, 'no033100'))
    combos.append(('A_원본', 'baseline_orig', BASELINE_BOOST, BASELINE_DEF, GS_DEFAULT, 'orig'))
    combos.append(('A_원본', 'v80.6_orig', BOOST_V806, DEFENSE_V806, GS_DEFAULT, 'orig'))

    # === 4. boost MOM 격자 ===
    for mom in ['12m', '12m-1m', '6m-1m', '6m']:
        b = dict(BOOST_V806); b['mom'] = mom
        combos.append(('4_MOM', f'mom_{mom}', b, DEFENSE_V806, GS_DEFAULT, 'orig'))

    # === 5. boost V/Q/G/M 격자 ===
    VQGM_CANDIDATES = [
        ('V15Q0G55M30', 15, 0, 55, 30),  # baseline (v80.6)
        ('V10Q0G60M30', 10, 0, 60, 30),  # G ↑
        ('V20Q0G50M30', 20, 0, 50, 30),  # V ↑ G ↓
        ('V15Q5G50M30', 15, 5, 50, 30),  # Q 추가
        ('V15Q0G50M35', 15, 0, 50, 35),  # M ↑
        ('V15Q0G60M25', 15, 0, 60, 25),  # G ↑ M ↓
        ('V20Q5G50M25', 20, 5, 50, 25),  # 다양
        ('V10Q5G55M30', 10, 5, 55, 30),  # 다양
    ]
    for name, v, q, g, m in VQGM_CANDIDATES:
        b = {'v':v/100, 'q':q/100, 'g':g/100, 'm':m/100, 'g_rev':0.5,
             'entry':2, 'exit':6, 'slots':5, 'mom':'12m'}
        combos.append(('5_VQGM', name, b, DEFENSE_V806, GS_DEFAULT, 'orig'))

    # === 6. G_SUB factor 격자 ===
    GS_CANDIDATES = [
        ('2f_rev_oca', ('rev_z', 'oca_z', None, None, None, None)),  # baseline
        ('2f_rev_opm', ('rev_z', 'op_margin_z', None, None, None, None)),
        ('2f_rev_gp', ('rev_z', 'gp_growth_z', None, None, None, None)),
        ('3f_rev_oca_opm', ('rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2)),
        ('3f_rev_oca_gp', ('rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2)),
        ('3f_rev_oca_opm_balanced', ('rev_z', 'oca_z', 'op_margin_z', 0.4, 0.3, 0.3)),
    ]
    for name, gs in GS_CANDIDATES:
        combos.append(('6_GSUB', name, BOOST_V806, DEFENSE_V806, gs, 'orig'))

    # === 7B. boost entry/slots/exit 격자 ===
    for entry, slots, exit_r in product([2, 3], [3, 4, 5], [4, 5, 6]):
        b = dict(BOOST_V806)
        b['entry'] = entry
        b['slots'] = slots
        b['exit'] = exit_r
        name = f'e{entry}_s{slots}_x{exit_r}'
        combos.append(('7B_ESX', name, b, DEFENSE_V806, GS_DEFAULT, 'orig'))

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

    # 카테고리별 출력
    for cat in sorted(df.cat.unique()):
        sub = df[df.cat == cat].sort_values('cal', ascending=False)
        print(f'\n=== {cat} ===')
        print(f'{"name":<32} {"Cal":>6} {"CAGR":>6} {"MDD":>6} {"Sharpe":>7}')
        for _, r in sub.iterrows():
            print(f'{r["name"]:<32} {r["cal"]:>6.2f} {r["cagr"]:>6.1f} {r["mdd"]:>6.1f} {r["sharpe"]:>7.2f}')

    df.to_csv('C:/dev/_tier7_extra_results_20260513.csv', index=False)
    print(f'\n저장: C:/dev/_tier7_extra_results_20260513.csv')

    # 텔레그램 — 카테고리별 best
    msg = '<b>[Tier 7+ Extra]</b>\n\n'
    for cat in sorted(df.cat.unique()):
        sub = df[df.cat == cat].sort_values('cal', ascending=False)
        msg += f'<b>{cat}</b>\n'
        for _, r in sub.head(3).iterrows():
            msg += f'  {r["name"][:30]}: Cal {r["cal"]:.2f}\n'
        msg += '\n'
    send_tg(msg)
    print('telegram sent')


if __name__ == '__main__':
    main()
