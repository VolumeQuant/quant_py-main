"""v78 Phase 3 보충: Breadth(bias수정) + KOSDAQ + 듀얼 지표"""
import sys, json, numpy as np, pandas as pd, time, csv, os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
OHLCV_PATH = str(sorted(DATA_DIR.glob('all_ohlcv_20170601_*.parquet'))[-1])
BENCH_PATH = str(DATA_DIR / 'kospi_yf.parquet')


def count_switches(regime, dates):
    switches = 0
    prev = None
    for d in dates:
        cur = regime.get(d, False)
        if prev is not None and cur != prev:
            switches += 1
        prev = cur
    return switches


# =============================================
# Breadth 지표 (look-ahead bias 수정)
# =============================================

def _build_monthly_universe(mc_dir, filter_fn):
    """월 첫 거래일 기준으로 유니버스 구축. filter_fn(mc_df) → ticker list."""
    mc_files = sorted(mc_dir.glob('market_cap_ALL_*.parquet'))
    monthly = {}
    seen_months = set()
    for f in mc_files:
        date_str = f.stem.split('_')[-1]
        ym = date_str[:6]
        if ym in seen_months:
            continue
        seen_months.add(ym)
        try:
            mc = pd.read_parquet(f)
            monthly[ym] = filter_fn(mc)
        except:
            continue
    return monthly


def make_breadth_regime(ohlcv, mc_dir, ma_period, threshold_pct, confirm_days,
                        universe='large'):
    """MA(period) 위 비율 > threshold → 공격.
    universe: 'large'=Top100, 'universe'=시총>=1000억, 'small'=1000~5000억"""

    if universe == 'large':
        monthly = _build_monthly_universe(mc_dir,
            lambda mc: mc.nlargest(100, '시가총액').index.tolist())
    elif universe == 'universe':
        monthly = _build_monthly_universe(mc_dir,
            lambda mc: mc[mc['시가총액'] >= 1e11].index.tolist())  # 1000억
    elif universe == 'small':
        monthly = _build_monthly_universe(mc_dir,
            lambda mc: mc[(mc['시가총액'] >= 1e11) & (mc['시가총액'] < 5e11)].index.tolist())
    else:
        return {}

    if not monthly:
        return {}

    regime = {}
    state = False
    confirm_count_up = 0
    confirm_count_down = 0

    for dt in ohlcv.index:
        d = dt.strftime('%Y%m%d')
        ym = d[:6]

        if ym in monthly:
            tickers = monthly[ym]
        else:
            prev_yms = [k for k in sorted(monthly.keys()) if k <= ym]
            if not prev_yms:
                regime[d] = state
                continue
            tickers = monthly[prev_yms[-1]]

        valid = [t for t in tickers if t in ohlcv.columns]
        if len(valid) < 20:
            regime[d] = state
            continue

        idx = ohlcv.index.get_loc(dt)
        if idx < ma_period:
            regime[d] = state
            continue

        window = ohlcv[valid].iloc[max(0, idx-ma_period+1):idx+1]
        ma = window.mean()
        current = ohlcv[valid].iloc[idx]
        above_ratio = (current > ma).sum() / len(valid) * 100

        if above_ratio >= threshold_pct:
            confirm_count_up += 1
            confirm_count_down = 0
            if confirm_count_up >= confirm_days:
                state = True
        else:
            confirm_count_down += 1
            confirm_count_up = 0
            if confirm_count_down >= confirm_days:
                state = False

        regime[d] = state

    return regime


def make_kosdaq_regime(ma_period, confirm_days):
    """KOSDAQ > MA(period), confirm_days 확인"""
    kd = pd.read_parquet(DATA_DIR / 'kosdaq_yf.parquet')
    price = kd['종가'].combine_first(kd['kosdaq']).dropna()

    ma = price.rolling(ma_period).mean()
    above = (price > ma).astype(int)

    regime = {}
    state = True  # KOSDAQ 데이터 없는 기간은 공격모드
    confirm_up = 0
    confirm_down = 0

    for dt, val in price.items():
        d = dt.strftime('%Y%m%d')
        if dt in ma.index and not pd.isna(ma[dt]):
            if val > ma[dt]:
                confirm_up += 1
                confirm_down = 0
                if confirm_up >= confirm_days:
                    state = True
            else:
                confirm_down += 1
                confirm_up = 0
                if confirm_down >= confirm_days:
                    state = False
        regime[d] = state

    return regime


def make_dual_regime(regime1, regime2, mode='AND'):
    """두 지표 조합. AND=둘 다 공격이면 공격, OR=하나라도 공격이면 공격"""
    all_dates = sorted(set(list(regime1.keys()) + list(regime2.keys())))
    regime = {}
    for d in all_dates:
        r1 = regime1.get(d, False)
        r2 = regime2.get(d, False)
        if mode == 'AND':
            regime[d] = r1 and r2
        else:
            regime[d] = r1 or r2
    return regime


def make_kospi_ma_regime(ma_period, confirm_days):
    """KOSPI MA - Phase 3 main과 동일 로직 (재사용)"""
    bench = pd.read_parquet(BENCH_PATH)
    price = bench['종가'].combine_first(bench['kospi']).dropna()
    ma = price.rolling(ma_period).mean()

    regime = {}
    state = False
    confirm_up = 0
    confirm_down = 0
    for dt, val in price.items():
        d = dt.strftime('%Y%m%d')
        if dt in ma.index and not pd.isna(ma[dt]):
            if val > ma[dt]:
                confirm_up += 1
                confirm_down = 0
                if confirm_up >= confirm_days:
                    state = True
            else:
                confirm_down += 1
                confirm_up = 0
                if confirm_down >= confirm_days:
                    state = False
        regime[d] = state
    return regime


# =============================================
# 워커 (Phase 3 main과 동일)
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
    worker_tasks = args
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


G_SUB_MAP_3F = {
    'rev+oca+gp': ('rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),
    'rev+oca+opm': ('rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2),
    'rev+gp+opm': ('rev_z', 'gp_growth_z', 'op_margin_z', 0.5, 0.3, 0.2),
}
G_SUB_MAP_2F = {
    'rev+opm 7:3': ('rev_z', 'op_margin_z', None, 0.7, None, None),
    'rev+oca 7:3': ('rev_z', 'oca_z', None, 0.7, None, None),
}

def make_params(row):
    gs = row.g_sub
    if gs in G_SUB_MAP_3F:
        s1, s2, s3, w1, w2, w3 = G_SUB_MAP_3F[gs]
    else:
        s1, s2, s3, w1, w2, w3 = G_SUB_MAP_2F[gs]
    return dict(v=int(row.v), q=int(row.q), g=int(row.g), m=int(row.m),
               mom=row.mom, entry=int(row.entry), exit=int(row['exit']), slots=int(row.slots),
               s1=s1, s2=s2, s3=s3, w1=w1, w2=w2, w3=w3)


if __name__ == '__main__':
    t0 = time.time()

    # OHLCV 로드 (breadth 계산용)
    print('OHLCV 로드 중...')
    ohlcv_df = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    mc_dir = DATA_DIR

    # ranking 날짜
    rk_dates = []
    for d_dir in [Path('bt_extended'), Path('bt_test_A')]:
        for f in sorted(d_dir.glob('ranking_*.json')):
            rk_dates.append(f.stem.replace('ranking_', ''))
    rk_dates = sorted(rk_dates)

    regimes = {}

    # =============================================
    # A. Breadth (look-ahead bias 수정, 3종 유니버스)
    # =============================================
    print('Breadth 지표 생성 중...')
    for univ, label in [('large', 'BL'), ('universe', 'BU'), ('small', 'BS')]:
        for ma in [126]:
            for th in [30, 40, 50, 60]:
                for cd in [3, 5, 10]:
                    name = f'{label}{ma}_{th}pct_{cd}d'
                    regimes[name] = make_breadth_regime(ohlcv_df, mc_dir, ma, th, cd, universe=univ)
                    if len(regimes) % 10 == 0:
                        print(f'  {len(regimes)}개 완료 ({time.time()-t0:.0f}초)', flush=True)

    # =============================================
    # B. KOSDAQ 기반
    # =============================================
    print('KOSDAQ 지표 생성 중...')
    for ma in [100, 150, 200]:
        for cd in [3, 5, 10]:
            name = f'KD_MA{ma}_{cd}d'
            regimes[name] = make_kosdaq_regime(ma, cd)

    # =============================================
    # C. KOSPI+KOSDAQ 듀얼
    # =============================================
    print('듀얼 지표 생성 중...')
    kospi_ma200_5d = make_kospi_ma_regime(200, 5)
    for kd_ma in [150, 200]:
        kd_regime = make_kosdaq_regime(kd_ma, 5)
        regimes[f'DUAL_KP200+KD{kd_ma}_AND_5d'] = make_dual_regime(kospi_ma200_5d, kd_regime, 'AND')
        regimes[f'DUAL_KP200+KD{kd_ma}_OR_5d'] = make_dual_regime(kospi_ma200_5d, kd_regime, 'OR')

    # KOSPI + Breadth 듀얼 (소형주 breadth 포함)
    for univ, label in [('large', 'BL'), ('universe', 'BU'), ('small', 'BS')]:
        for bth in [40, 50]:
            b_regime = make_breadth_regime(ohlcv_df, mc_dir, 126, bth, 5, universe=univ)
            regimes[f'DUAL_KP200+{label}126_{bth}_AND_5d'] = make_dual_regime(kospi_ma200_5d, b_regime, 'AND')
            regimes[f'DUAL_KP200+{label}126_{bth}_OR_5d'] = make_dual_regime(kospi_ma200_5d, b_regime, 'OR')

    print(f'\n국면 지표: {len(regimes)}개 ({time.time()-t0:.0f}초)')
    for name in list(regimes.keys())[:5]:
        sw = count_switches(regimes[name], rk_dates)
        atk_days = sum(1 for d in rk_dates if regimes[name].get(d, False))
        print(f'  {name}: 전환={sw}회, 공격={atk_days}일/{len(rk_dates)}일')

    # Attack/Defense Top 5
    atk_df = pd.read_csv(RESULT_DIR / 'v78_phase2b_attack.csv')
    def_df = pd.read_csv(RESULT_DIR / 'v78_phase2b_defense.csv')
    atk_top5 = [make_params(r) for _, r in atk_df.nlargest(5, 'cal').iterrows()]
    def_top5 = [make_params(r) for _, r in def_df.nlargest(5, 'cal').iterrows()]

    # 조합 생성
    all_tasks = []
    for rname, rdict in regimes.items():
        for atk in atk_top5:
            for dfn in def_top5:
                all_tasks.append((rname, rdict, atk, dfn))

    print(f'총 조합: {len(all_tasks)}개')

    # 3워커 실행
    chunk_size = len(all_tasks) // 3 + 1
    chunks = [all_tasks[i:i+chunk_size] for i in range(0, len(all_tasks), chunk_size)]

    print(f'\n=== 보충 국면 서치 시작 ===', flush=True)
    results = []
    with ProcessPoolExecutor(max_workers=3) as exe:
        futs = {exe.submit(run_worker, chunk): i for i, chunk in enumerate(chunks)}
        for fut in as_completed(futs):
            res = fut.result()
            results.extend(res)
            print(f'  워커{futs[fut]}: {len(res)}개 ({time.time()-t0:.0f}초)', flush=True)

    results.sort(key=lambda x: -x[3])

    print(f'\n=== 보충 결과: {len(results)}개, {time.time()-t0:.0f}초 ({(time.time()-t0)/60:.1f}분) ===')
    print(f'\nTop 15:')
    for i, (rn, atk_l, def_l, cal, cagr, mdd, sh, so, sw) in enumerate(results[:15]):
        print(f'  {i+1}. {rn:35s} ATK={atk_l} DEF={def_l}: Cal={cal:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}% 전환={sw}')

    # 유형별 최고
    print(f'\n--- 유형별 최고 Cal ---')
    type_best = {}
    for rn, atk_l, def_l, cal, cagr, mdd, sh, so, sw in results:
        if rn.startswith('BL'):
            typ = 'B_LARGE'
        elif rn.startswith('BU'):
            typ = 'B_UNIV'
        elif rn.startswith('BS'):
            typ = 'B_SMALL'
        elif rn.startswith('KD'):
            typ = 'KOSDAQ'
        elif rn.startswith('DUAL'):
            typ = 'DUAL'
        else:
            typ = rn
        if typ not in type_best or cal > type_best[typ][3]:
            type_best[typ] = (rn, atk_l, def_l, cal, cagr, mdd, sh, so, sw)
    for typ in ['B_LARGE', 'B_UNIV', 'B_SMALL', 'KOSDAQ', 'DUAL']:
        if typ in type_best:
            rn, atk_l, def_l, cal, cagr, mdd, sh, so, sw = type_best[typ]
            print(f'  {typ:10s}: {rn:35s} Cal={cal:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}% 전환={sw}')

    with open(RESULT_DIR / 'v78_phase3_supplement.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['regime', 'atk', 'def', 'cal', 'cagr', 'mdd', 'sharpe', 'sortino', 'switches'])
        for row in results:
            w.writerow(row)

    print(f'\n저장 완료')
