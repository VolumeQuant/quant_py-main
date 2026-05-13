"""Tier 2 — Multiprocess version (2~3워커)

Windows spawn:
  - 메인이 데이터 1회 로드
  - 워커 init에서 TSIM 1회 생성 (각 워커 메모리 ~2GB)
  - 워커당 combo 청크 실행

워커 3개 권장 (메모리 6GB, BT 1.7s/combo → 1200/3 ≈ 11분)
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

# ── 공유 데이터 (worker init에서 채움) ──
TSIM = None
REGIME = None
DATES_74 = None

GS_FIXED = ('rev_z', 'oca_z', None, None, None, None)
DEFENSE_BASE = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'mom':'6m-1m'}


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
    """공통 데이터 로드"""
    from turbo_simulator import TurboSimulator

    boost_rd = load_rankings([PROJECT / 'state'])
    defense_rd = load_rankings([PROJECT / 'state' / 'defense'])
    all_dates = sorted(set(boost_rd) & set(defense_rd))
    boost_rk = {d: boost_rd[d]['rankings'] for d in all_dates}

    START, END = '20190102', '20260512'
    dates_74 = [d for d in all_dates if START <= d <= END]

    ohlcv = pd.read_parquet(PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet').replace(0, np.nan)

    kdf = pd.read_parquet(PROJECT / 'data_cache' / 'kospi_yf.parquet')
    kospi = kdf.iloc[:, 0].copy()
    for c in kdf.columns[1:]:
        kospi = kospi.fillna(kdf[c])
    kospi = kospi.dropna()
    ma170 = kospi.rolling(170).mean()

    def calc_regime(target_dates):
        reg = {}; md = False; stk = 0; ss = None
        for d in target_dates:
            ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
            if kv is None or pd.isna(mv): reg[d] = md; continue
            s = kv > mv
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= 8 and md != s: md = s
            reg[d] = md
        return reg
    regime = calc_regime(dates_74)

    tsim = TurboSimulator({d: boost_rk[d] for d in dates_74}, dates_74, ohlcv)
    return tsim, regime, dates_74


def worker_init():
    """워커 시작 시 TSIM 1회 생성"""
    global TSIM, REGIME, DATES_74
    print(f'[worker {os.getpid()}] data load 시작...', flush=True)
    t0 = time.time()
    TSIM, REGIME, DATES_74 = load_all()
    print(f'[worker {os.getpid()}] 로드 완료 ({time.time()-t0:.1f}초)', flush=True)


def run_combo(params):
    """단일 combo 실행"""
    sb, sd, sl, ts, gr = params
    boost_p = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':gr,
               'entry':2,'exit':6,'slots':sb,'mom':'12m'}
    defense_p = {**DEFENSE_BASE, 'slots':sd}
    try:
        r = TSIM.run_regime(defense_params=defense_p, offense_params=boost_p,
                            regime_dict=REGIME, trailing_stop=ts, stop_loss=sl,
                            g_sub1_o=GS_FIXED[0], g_sub2_o=GS_FIXED[1], g_sub3_o=GS_FIXED[2],
                            g_w1_o=GS_FIXED[3], g_w2_o=GS_FIXED[4], g_w3_o=GS_FIXED[5],
                            g_sub1_d=GS_FIXED[0], g_sub2_d=GS_FIXED[1], g_sub3_d=GS_FIXED[2],
                            g_w1_d=GS_FIXED[3], g_w2_d=GS_FIXED[4], g_w3_d=GS_FIXED[5])
        return {'sb': sb, 'sd': sd, 'sl': sl, 'ts': ts, 'gr': gr,
                'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'],
                'sharpe': r['sharpe'], 'sortino': r['sortino']}
    except Exception as e:
        return {'sb':sb,'sd':sd,'sl':sl,'ts':ts,'gr':gr,
                'cal':0,'cagr':0,'mdd':99,'sharpe':0,'sortino':0,'err':str(e)[:50]}


def main():
    print('=== Tier 2 — Multiprocess (3 workers) ===', flush=True)
    t_start = time.time()

    # 격자
    SLOTS_BOOST = [4, 5, 6, 7]
    SLOTS_DEF = [4, 5, 6, 7]
    SL_VALS = [-0.07, -0.08, -0.09, -0.10, -0.11]
    TS_VALS = [-0.08, -0.10, -0.12]
    G_REV_BOOST = [0.3, 0.4, 0.5, 0.6, 0.7]
    combos = list(product(SLOTS_BOOST, SLOTS_DEF, SL_VALS, TS_VALS, G_REV_BOOST))
    print(f'총 {len(combos)}조합, 워커 3개', flush=True)

    # 텔레그램
    from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
    def send_tg(msg):
        if len(msg) > 4096: msg = msg[:4090] + '...'
        try:
            requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                          data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
        except: pass

    # ProcessPool
    results = []
    t_pool = time.time()
    with ProcessPoolExecutor(max_workers=3, initializer=worker_init) as ex:
        futures = {ex.submit(run_combo, c): c for c in combos}
        done_count = 0
        for fut in as_completed(futures):
            results.append(fut.result())
            done_count += 1
            if done_count % 100 == 0 or done_count == len(combos):
                elapsed = time.time() - t_pool
                avg = elapsed / done_count
                remain = avg * (len(combos) - done_count) / 60
                print(f'  {done_count}/{len(combos)} ({elapsed/60:.1f}분 경과, {remain:.1f}분 남음)', flush=True)

    wall = time.time() - t_start
    print(f'\n=== 완료: {wall/60:.1f}분, 평균 {wall/len(combos)*1000:.0f}ms/combo ===\n', flush=True)

    df = pd.DataFrame(results)
    df_sorted = df.sort_values('cal', ascending=False)

    print('=' * 80)
    print(f'{"순위":>3} {"sb":>3} {"sd":>3} {"SL":>5} {"TS":>5} {"gr":>4} {"Cal":>6} {"CAGR":>6} {"MDD":>6} {"Sharpe":>7}')
    print('-' * 80)
    for i, (_, r) in enumerate(df_sorted.head(30).iterrows(), 1):
        print(f'{i:>3} {r.sb:>3.0f} {r.sd:>3.0f} {r.sl:>5.0%} {r.ts:>5.0%} {r.gr:>4.1f} '
              f'{r.cal:>6.2f} {r.cagr:>6.1f} {r.mdd:>6.1f} {r.sharpe:>7.2f}')

    print(f'\n=== 변수별 평균 Cal ===')
    print(f'sb: {dict(df.groupby("sb").cal.mean().round(2))}')
    print(f'sd: {dict(df.groupby("sd").cal.mean().round(2))}')
    print(f'SL: {dict(df.groupby("sl").cal.mean().round(2))}')
    print(f'TS: {dict(df.groupby("ts").cal.mean().round(2))}')
    print(f'gr: {dict(df.groupby("gr").cal.mean().round(2))}')

    df.to_csv(PROJECT.parent / '_tier2_results_20260513.csv', index=False)
    print(f'\n저장: _tier2_results_20260513.csv')

    top10 = df_sorted.head(10)
    msg = f'<b>[Tier 2 grid 결과 — entry=2, MP 3워커]</b>\n\n총 {len(combos)}조합, {wall/60:.1f}분\n\n<b>Top 10:</b>\n'
    for i, (_, r) in enumerate(top10.iterrows(), 1):
        msg += f'{i}. sb{int(r.sb)} sd{int(r.sd)} SL{int(r.sl*100)} TS{int(r.ts*100)} gr{r.gr}: Cal={r.cal:.2f} CAGR={r.cagr:.0f}%\n'
    send_tg(msg)
    print('telegram sent')


if __name__ == '__main__':
    main()
