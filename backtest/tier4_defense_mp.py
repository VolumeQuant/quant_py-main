"""Tier 4 — Defense 격자 (MP 3워커)

Boost: v80.5 plateau 고정 (e2 sb5 SL-10 TS-8 gr0.5)
Defense 흔드는 변수:
  - VQGM weights (8 조합)
  - G_REV defense (4)
  - MOM defense (4)
  - slots_defense (4)

총 512 조합 × 1.7s / 3워커 ≈ 5분
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

# 공유 글로벌
TSIM = None
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
    ma170 = kospi.rolling(170).mean()
    def calc_regime(td):
        reg = {}; md = False; stk = 0; ss = None
        for d in td:
            ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
            if kv is None or pd.isna(mv): reg[d] = md; continue
            s = kv > mv
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= 8 and md != s: md = s
            reg[d] = md
        return reg
    return TurboSimulator({d: boost_rk[d] for d in dates_74}, dates_74, ohlcv), calc_regime(dates_74)


def worker_init():
    global TSIM, REGIME
    print(f'[worker {os.getpid()}] load...', flush=True)
    t0 = time.time()
    TSIM, REGIME = load_all()
    print(f'[worker {os.getpid()}] done ({time.time()-t0:.1f}s)', flush=True)


# Boost 고정 (v80.5 plateau)
BOOST_FIXED = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.5,
               'entry':2,'exit':6,'slots':5,'mom':'12m'}
GS_FIXED = ('rev_z', 'oca_z', None, None, None, None)


def run_combo(params):
    """defense 단일 combo 실행"""
    v, q, g, m, gr_d, mom_d, sd = params
    defense_p = {'v':v/100,'q':q/100,'g':g/100,'m':m/100,'g_rev':gr_d,
                 'entry':3,'exit':6,'slots':sd,'mom':mom_d}
    try:
        r = TSIM.run_regime(defense_params=defense_p, offense_params=BOOST_FIXED,
                            regime_dict=REGIME, trailing_stop=-0.08, stop_loss=-0.10,
                            g_sub1_o=GS_FIXED[0], g_sub2_o=GS_FIXED[1], g_sub3_o=GS_FIXED[2],
                            g_w1_o=GS_FIXED[3], g_w2_o=GS_FIXED[4], g_w3_o=GS_FIXED[5],
                            g_sub1_d=GS_FIXED[0], g_sub2_d=GS_FIXED[1], g_sub3_d=GS_FIXED[2],
                            g_w1_d=GS_FIXED[3], g_w2_d=GS_FIXED[4], g_w3_d=GS_FIXED[5])
        return {'v':v,'q':q,'g':g,'m':m,'gr_d':gr_d,'mom_d':mom_d,'sd':sd,
                'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'],
                'sharpe': r['sharpe'], 'sortino': r['sortino']}
    except Exception as e:
        return {'v':v,'q':q,'g':g,'m':m,'gr_d':gr_d,'mom_d':mom_d,'sd':sd,
                'cal':0,'cagr':0,'mdd':99,'sharpe':0,'sortino':0,'err':str(e)[:50]}


def main():
    print('=== Tier 4 — Defense 격자 (MP 3워커) ===', flush=True)

    # Defense VQGM 후보 (v80 baseline = 30,15,15,40)
    VQGM = [
        (30, 15, 15, 40),  # baseline
        (25, 15, 20, 40),  # G ↑
        (30, 10, 20, 40),  # Q→G
        (35, 10, 15, 40),  # V ↑ Q ↓
        (25, 15, 15, 45),  # M ↑
        (35, 15, 15, 35),  # V ↑ M ↓
        (30, 20, 15, 35),  # Q ↑
        (30, 15, 20, 35),  # G ↑ M ↓
    ]
    GR_DEF = [0.5, 0.6, 0.7, 0.8]
    MOM_DEF = ['6m', '6m-1m', '12m', '12m-1m']
    SLOTS_DEF = [4, 5, 6, 7]

    combos = [(v,q,g,m, gr, mom, sd) for (v,q,g,m), gr, mom, sd
              in product(VQGM, GR_DEF, MOM_DEF, SLOTS_DEF)]
    print(f'총 {len(combos)} 조합, 워커 3개', flush=True)

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
            if done % 50 == 0 or done == len(combos):
                elapsed = time.time() - t_start
                avg = elapsed / done
                remain = avg * (len(combos) - done) / 60
                print(f'  {done}/{len(combos)} ({elapsed/60:.1f}분 경과, {remain:.1f}분 남음)', flush=True)

    wall = time.time() - t_start
    print(f'\n=== 완료: {wall/60:.1f}분 ===\n', flush=True)

    df = pd.DataFrame(results)
    df_sorted = df.sort_values('cal', ascending=False)

    # baseline (defense baseline)
    bl = df[(df.v==30) & (df.q==15) & (df.g==15) & (df.m==40) &
            (df.gr_d==0.7) & (df.mom_d=='6m-1m') & (df.sd==5)]
    if not bl.empty:
        bl = bl.iloc[0]
        print(f'baseline defense (V30Q15G15M40 gr0.7 6m-1m sd5): Cal={bl["cal"]:.2f}\n')

    print('=' * 100)
    print(f'{"순위":>3} {"V":>3} {"Q":>3} {"G":>3} {"M":>3} {"gr_d":>5} {"mom_d":>9} {"sd":>3} {"Cal":>6} {"CAGR":>6} {"MDD":>6}')
    print('-' * 100)
    for i, (_, r) in enumerate(df_sorted.head(30).iterrows(), 1):
        print(f'{i:>3} {r.v:>3.0f} {r.q:>3.0f} {r.g:>3.0f} {r.m:>3.0f} {r.gr_d:>5.1f} {r.mom_d:>9} {r.sd:>3.0f} '
              f'{r.cal:>6.2f} {r.cagr:>6.1f} {r.mdd:>6.1f}')

    print(f'\n=== 변수별 평균 ===')
    print(f'VQGM: {dict(df.groupby(["v","q","g","m"]).cal.mean().round(2))}')
    print(f'gr_d: {dict(df.groupby("gr_d").cal.mean().round(2))}')
    print(f'mom_d: {dict(df.groupby("mom_d").cal.mean().round(2))}')
    print(f'sd: {dict(df.groupby("sd").cal.mean().round(2))}')

    df.to_csv('C:/dev/_tier4_results_20260513.csv', index=False)
    print(f'\n저장: C:/dev/_tier4_results_20260513.csv')

    top10 = df_sorted.head(10)
    msg = f'<b>[Tier 4 — Defense, MP 3워커]</b>\n\n총 {len(combos)}조합, {wall/60:.1f}분\n\n<b>Top 10:</b>\n'
    for i, (_, r) in enumerate(top10.iterrows(), 1):
        msg += f'{i}. V{int(r.v)}Q{int(r.q)}G{int(r.g)}M{int(r.m)} gr{r.gr_d} {r.mom_d} sd{int(r.sd)}: Cal={r.cal:.2f}\n'
    send_tg(msg)
    print('telegram sent')


if __name__ == '__main__':
    main()
