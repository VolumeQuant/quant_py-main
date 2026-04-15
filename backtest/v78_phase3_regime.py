"""v78 Phase 3: 국면 서치 — 다양한 지표 × Attack/Defense Top 조합"""
import sys, json, numpy as np, pandas as pd, time, csv, os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
OHLCV_PATH = str(sorted(DATA_DIR.glob('all_ohlcv_20170601_*.parquet'))[-1])
BENCH_PATH = str(DATA_DIR / 'kospi_yf.parquet')


# =============================================
# 국면 지표 생성 함수들
# =============================================

def get_kospi_price():
    bench = pd.read_parquet(BENCH_PATH)
    price = bench['종가'].combine_first(bench['kospi']).dropna()
    return price


def make_ma_regime(price, ma_period, confirm_days):
    """KOSPI > MA(period), confirm_days 연속 확인"""
    ma = price.rolling(ma_period).mean()
    above = (price > ma).astype(int)
    # confirm_days 연속 확인
    confirmed = above.copy()
    if confirm_days > 1:
        confirmed = above.rolling(confirm_days).min()
    # 상태 머신: 전환은 confirm_days 연속일 때만
    regime = {}
    state = False  # 방어 시작
    for dt, val in confirmed.items():
        if pd.isna(val):
            regime[dt.strftime('%Y%m%d')] = state
            continue
        if val == 1.0 and not state:
            state = True
        elif val == 0.0 and state:
            # 하락 confirm도 동일 기간 체크
            below_confirmed = (price <= ma).astype(int).rolling(confirm_days).min()
            if dt in below_confirmed.index and below_confirmed[dt] == 1.0:
                state = False
        regime[dt.strftime('%Y%m%d')] = state
    return regime


def make_momentum_regime(price, lookback_days, confirm_days):
    """KOSPI N일 수익률 > 0, confirm_days 확인"""
    ret = price.pct_change(lookback_days)
    positive = (ret > 0).astype(int)
    if confirm_days > 1:
        confirmed_up = positive.rolling(confirm_days).min()
        confirmed_down = (1 - positive).rolling(confirm_days).min()
    else:
        confirmed_up = positive
        confirmed_down = 1 - positive
    regime = {}
    state = False
    for dt in price.index:
        d = dt.strftime('%Y%m%d')
        if dt in confirmed_up.index and not pd.isna(confirmed_up[dt]):
            if confirmed_up[dt] == 1.0:
                state = True
            elif confirmed_down[dt] == 1.0:
                state = False
        regime[d] = state
    return regime


def make_volatility_regime(price, vol_window, threshold, confirm_days):
    """실현 변동성 < threshold → 공격, >= threshold → 방어"""
    log_ret = np.log(price / price.shift(1))
    vol = log_ret.rolling(vol_window).std() * np.sqrt(252) * 100  # 연율화 %
    calm = (vol < threshold).astype(int)
    if confirm_days > 1:
        confirmed_calm = calm.rolling(confirm_days).min()
        confirmed_vol = (1 - calm).rolling(confirm_days).min()
    else:
        confirmed_calm = calm
        confirmed_vol = 1 - calm
    regime = {}
    state = False
    for dt in price.index:
        d = dt.strftime('%Y%m%d')
        if dt in confirmed_calm.index and not pd.isna(confirmed_calm[dt]):
            if confirmed_calm[dt] == 1.0:
                state = True
            elif confirmed_vol[dt] == 1.0:
                state = False
        regime[d] = state
    return regime


def make_drawdown_regime(price, threshold_pct, confirm_days):
    """52주 고점 대비 -threshold% 이상 → 방어"""
    rolling_high = price.rolling(252).max()
    dd = (price / rolling_high - 1) * 100
    ok = (dd > threshold_pct).astype(int)  # threshold는 음수 (예: -15)
    if confirm_days > 1:
        confirmed_ok = ok.rolling(confirm_days).min()
        confirmed_bad = (1 - ok).rolling(confirm_days).min()
    else:
        confirmed_ok = ok
        confirmed_bad = 1 - ok
    regime = {}
    state = False
    for dt in price.index:
        d = dt.strftime('%Y%m%d')
        if dt in confirmed_ok.index and not pd.isna(confirmed_ok[dt]):
            if confirmed_ok[dt] == 1.0:
                state = True
            elif confirmed_bad[dt] == 1.0:
                state = False
        regime[d] = state
    return regime


def make_rsi_regime(price, rsi_period, threshold, confirm_days):
    """RSI > threshold → 공격"""
    delta = price.diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    above = (rsi > threshold).astype(int)
    if confirm_days > 1:
        confirmed_up = above.rolling(confirm_days).min()
        confirmed_down = (1 - above).rolling(confirm_days).min()
    else:
        confirmed_up = above
        confirmed_down = 1 - above
    regime = {}
    state = False
    for dt in price.index:
        d = dt.strftime('%Y%m%d')
        if dt in confirmed_up.index and not pd.isna(confirmed_up[dt]):
            if confirmed_up[dt] == 1.0:
                state = True
            elif confirmed_down[dt] == 1.0:
                state = False
        regime[d] = state
    return regime


def make_golden_cross_regime(price, short_ma, long_ma, confirm_days):
    """골든크로스: 단기MA > 장기MA → 공격"""
    ma_short = price.rolling(short_ma).mean()
    ma_long = price.rolling(long_ma).mean()
    above = (ma_short > ma_long).astype(int)
    if confirm_days > 1:
        confirmed_up = above.rolling(confirm_days).min()
        confirmed_down = (1 - above).rolling(confirm_days).min()
    else:
        confirmed_up = above
        confirmed_down = 1 - above
    regime = {}
    state = False
    for dt in price.index:
        d = dt.strftime('%Y%m%d')
        if dt in confirmed_up.index and not pd.isna(confirmed_up[dt]):
            if confirmed_up[dt] == 1.0:
                state = True
            elif confirmed_down[dt] == 1.0:
                state = False
        regime[d] = state
    return regime


def make_ma_slope_regime(price, ma_period, slope_window, confirm_days):
    """MA 기울기: MA가 상승중 → 공격"""
    ma = price.rolling(ma_period).mean()
    slope = ma.diff(slope_window)
    rising = (slope > 0).astype(int)
    if confirm_days > 1:
        confirmed_up = rising.rolling(confirm_days).min()
        confirmed_down = (1 - rising).rolling(confirm_days).min()
    else:
        confirmed_up = rising
        confirmed_down = 1 - rising
    regime = {}
    state = False
    for dt in price.index:
        d = dt.strftime('%Y%m%d')
        if dt in confirmed_up.index and not pd.isna(confirmed_up[dt]):
            if confirmed_up[dt] == 1.0:
                state = True
            elif confirmed_down[dt] == 1.0:
                state = False
        regime[d] = state
    return regime


def make_all_attack_regime(dates):
    """국면전환 없음 — 항상 공격"""
    return {d: True for d in dates}


def count_switches(regime, dates):
    """국면 전환 횟수"""
    switches = 0
    prev = None
    for d in dates:
        cur = regime.get(d, False)
        if prev is not None and cur != prev:
            switches += 1
        prev = cur
    return switches


# =============================================
# 워커
# =============================================

def load_rankings():
    rk = {}
    for d_dir in [Path(__file__).parent / 'bt_extended', Path(__file__).parent / 'bt_test_A']:
        for f in sorted(d_dir.glob('ranking_*.json')):
            d = f.stem.replace('ranking_', '')
            rk[d] = json.load(open(f, 'r', encoding='utf-8')).get('rankings', [])
    return rk


def run_worker(args):
    from turbo_simulator import TurboSimulator
    worker_tasks = args  # list of (regime_name, regime_dict, atk_params, def_params)
    rk = load_rankings()
    dates = sorted(rk.keys())
    ohlcv = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    bench = pd.read_parquet(BENCH_PATH)
    tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)

    results = []
    for regime_name, regime_dict, atk, dfn in worker_tasks:
        atk_p = dict(v=atk['v']/100, q=atk['q']/100, g=atk['g']/100, m=atk['m']/100,
                     g_rev=0.5 if atk.get('s3') else atk['w1'],
                     entry=atk['entry'], exit=atk['exit'], slots=atk['slots'],
                     mom=atk['mom'])
        def_p = dict(v=dfn['v']/100, q=dfn['q']/100, g=dfn['g']/100, m=dfn['m']/100,
                     g_rev=0.5 if dfn.get('s3') else dfn['w1'],
                     entry=dfn['entry'], exit=dfn['exit'], slots=dfn['slots'],
                     mom=dfn['mom'])

        r = tsim.run_regime(
            defense_params=def_p, offense_params=atk_p,
            regime_dict=regime_dict,
            stop_loss=-0.10, trailing_stop=-0.15,
            g_sub1_o=atk['s1'], g_sub2_o=atk['s2'],
            g_sub3_o=atk.get('s3'), g_w1_o=atk.get('w1'), g_w2_o=atk.get('w2'), g_w3_o=atk.get('w3'),
            g_sub1_d=dfn['s1'], g_sub2_d=dfn['s2'],
            g_sub3_d=dfn.get('s3'), g_w1_d=dfn.get('w1'), g_w2_d=dfn.get('w2'), g_w3_d=dfn.get('w3'),
        )
        switches = count_switches(regime_dict, dates)
        results.append((regime_name,
                        f"V{atk['v']}Q{atk['q']}G{atk['g']}M{atk['m']}",
                        f"V{dfn['v']}Q{dfn['q']}G{dfn['g']}M{dfn['m']}",
                        r['calmar'], r['cagr'], r['mdd'], r['sharpe'], r['sortino'], switches))
    return results


if __name__ == '__main__':
    t0 = time.time()
    price = get_kospi_price()

    # 날짜 목록 (ranking 기준)
    rk_dates = []
    for d_dir in [Path('bt_extended'), Path('bt_test_A')]:
        for f in sorted(d_dir.glob('ranking_*.json')):
            rk_dates.append(f.stem.replace('ranking_', ''))
    rk_dates = sorted(rk_dates)

    # =============================================
    # 국면 지표 생성
    # =============================================
    regimes = {}

    # 0. 국면전환 없음 (attack-only)
    regimes['NO_REGIME'] = make_all_attack_regime(rk_dates)

    # A. MA 기반 (기존 + 주변)
    for ma in [100, 120, 150, 200, 250]:
        for cd in [3, 5, 7, 10, 15]:
            name = f'MA{ma}_{cd}d'
            regimes[name] = make_ma_regime(price, ma, cd)

    # B. 모멘텀 기반 (KOSPI N일 수익률)
    for lb in [60, 90, 120, 180, 252]:
        for cd in [3, 5, 10]:
            name = f'MOM{lb}_{cd}d'
            regimes[name] = make_momentum_regime(price, lb, cd)

    # C. 변동성 기반
    for vw in [20, 60]:
        for th in [15, 20, 25, 30]:
            for cd in [3, 5, 10]:
                name = f'VOL{vw}_{th}pct_{cd}d'
                regimes[name] = make_volatility_regime(price, vw, th, cd)

    # D. 52주 고점 대비 낙폭
    for th in [-10, -15, -20, -25]:
        for cd in [3, 5, 10]:
            name = f'DD{abs(th)}pct_{cd}d'
            regimes[name] = make_drawdown_regime(price, th, cd)

    # E. RSI 기반
    for rp in [14, 21]:
        for th in [40, 45, 50, 55]:
            for cd in [3, 5, 10]:
                name = f'RSI{rp}_{th}_{cd}d'
                regimes[name] = make_rsi_regime(price, rp, th, cd)

    # F. 골든크로스 (단기MA vs 장기MA)
    for short, long in [(20, 60), (50, 200), (20, 200), (60, 200), (50, 150)]:
        for cd in [3, 5, 10]:
            name = f'GC{short}x{long}_{cd}d'
            regimes[name] = make_golden_cross_regime(price, short, long, cd)

    # G. MA 기울기 (MA가 상승중인지)
    for ma in [120, 200]:
        for sw in [5, 10, 20]:
            for cd in [3, 5, 10]:
                name = f'SLOPE{ma}_{sw}w_{cd}d'
                regimes[name] = make_ma_slope_regime(price, ma, sw, cd)

    print(f'국면 지표: {len(regimes)}개 생성 ({time.time()-t0:.1f}초)')
    for name, rd in list(regimes.items())[:5]:
        sw = count_switches(rd, rk_dates)
        atk_days = sum(1 for d in rk_dates if rd.get(d, False))
        print(f'  {name}: 전환={sw}회, 공격={atk_days}일/{len(rk_dates)}일')

    # =============================================
    # Attack/Defense Top 5 조합 (Phase 2b 결과)
    # =============================================
    atk_df = pd.read_csv(RESULT_DIR / 'v78_phase2b_attack.csv')
    def_df = pd.read_csv(RESULT_DIR / 'v78_phase2b_defense.csv')

    G_SUB_MAP_3F = {
        'rev+oca+gp': ('rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),
        'rev+oca+opm': ('rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2),
        'rev+gp+opm': ('rev_z', 'gp_growth_z', 'op_margin_z', 0.5, 0.3, 0.2),
    }
    G_SUB_MAP_2F = {
        'rev+opm 7:3': ('rev_z', 'op_margin_z', None, 0.7, None, None),
        'rev+oca 7:3': ('rev_z', 'oca_z', None, 0.7, None, None),
        'raccel+opm 5:5': ('rev_accel_z', 'op_margin_z', None, 0.5, None, None),
    }

    def make_params(row, is_3f=True):
        gs = row.g_sub
        if gs in G_SUB_MAP_3F:
            s1, s2, s3, w1, w2, w3 = G_SUB_MAP_3F[gs]
        else:
            s1, s2, s3, w1, w2, w3 = G_SUB_MAP_2F[gs]
        return dict(v=int(row.v), q=int(row.q), g=int(row.g), m=int(row.m),
                   mom=row.mom, entry=int(row.entry), exit=int(row['exit']), slots=int(row.slots),
                   s1=s1, s2=s2, s3=s3, w1=w1, w2=w2, w3=w3)

    atk_top5 = [make_params(r) for _, r in atk_df.nlargest(5, 'cal').iterrows()]
    def_top5 = [make_params(r) for _, r in def_df.nlargest(5, 'cal').iterrows()]

    print(f'\nAttack Top 5:')
    for a in atk_top5:
        print(f"  V{a['v']}Q{a['q']}G{a['g']}M{a['m']} {a['mom']} E{a['entry']}X{a['exit']}S{a['slots']}")
    print(f'Defense Top 5:')
    for d in def_top5:
        print(f"  V{d['v']}Q{d['q']}G{d['g']}M{d['m']} {d['mom']} E{d['entry']}X{d['exit']}S{d['slots']}")

    # =============================================
    # 조합 생성: 국면 × Atk Top 5 × Def Top 5
    # =============================================
    all_tasks = []
    for rname, rdict in regimes.items():
        for atk in atk_top5:
            if rname == 'NO_REGIME':
                # attack-only: defense 무시, 하나만
                all_tasks.append((rname, rdict, atk, atk))
                break
            for dfn in def_top5:
                all_tasks.append((rname, rdict, atk, dfn))

    print(f'\n총 조합: {len(all_tasks)}개')
    est_sec = len(all_tasks) * 0.9 / 3
    print(f'예상 시간: {est_sec:.0f}초 ({est_sec/60:.1f}분), 3워커')

    # 3워커로 분할
    chunk_size = len(all_tasks) // 3 + 1
    chunks = [all_tasks[i:i+chunk_size] for i in range(0, len(all_tasks), chunk_size)]

    print(f'\n=== 국면 서치 시작 ===', flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=3) as exe:
        futs = {exe.submit(run_worker, chunk): i for i, chunk in enumerate(chunks)}
        for fut in as_completed(futs):
            res = fut.result()
            results.extend(res)
            print(f'  워커{futs[fut]}: {len(res)}개 ({time.time()-t0:.0f}초)', flush=True)

    # 결과 정렬
    results.sort(key=lambda x: -x[3])  # cal

    print(f'\n=== 전체 결과: {len(results)}개, {time.time()-t0:.0f}초 ({(time.time()-t0)/60:.1f}분) ===')
    print(f'\nTop 20:')
    for i, (rn, atk_l, def_l, cal, cagr, mdd, sh, so, sw) in enumerate(results[:20]):
        print(f'  {i+1}. {rn:25s} ATK={atk_l} DEF={def_l}: Cal={cal:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}% 전환={sw}')

    print(f'\n--- 국면 유형별 최고 Cal ---')
    # 유형 분류
    type_best = {}
    for rn, atk_l, def_l, cal, cagr, mdd, sh, so, sw in results:
        prefix = rn.split('_')[0] if '_' in rn else rn
        if prefix.startswith('MA') and not prefix.startswith('MOM'):
            typ = 'MA'
        elif prefix.startswith('MOM'):
            typ = 'MOM'
        elif prefix.startswith('VOL'):
            typ = 'VOL'
        elif prefix.startswith('DD'):
            typ = 'DD'
        elif prefix.startswith('RSI'):
            typ = 'RSI'
        elif prefix.startswith('GC'):
            typ = 'GC'
        elif prefix.startswith('SLOPE'):
            typ = 'SLOPE'
        else:
            typ = rn
        if typ not in type_best or cal > type_best[typ][3]:
            type_best[typ] = (rn, atk_l, def_l, cal, cagr, mdd, sh, so, sw)

    for typ in ['NO_REGIME', 'MA', 'MOM', 'VOL', 'DD', 'RSI', 'GC', 'SLOPE']:
        if typ in type_best:
            rn, atk_l, def_l, cal, cagr, mdd, sh, so, sw = type_best[typ]
            print(f'  {typ:10s}: {rn:25s} Cal={cal:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}% 전환={sw}')

    # CSV 저장
    with open(RESULT_DIR / 'v78_phase3_regime.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['regime', 'atk', 'def', 'cal', 'cagr', 'mdd', 'sharpe', 'sortino', 'switches'])
        for row in results:
            w.writerow(row)

    print(f'\n저장: {RESULT_DIR / "v78_phase3_regime.csv"}')
