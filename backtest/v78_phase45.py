"""v78 Phase 4+5: 인접 안정성 + Walk-Forward — 후보 11개 전부"""
import sys, json, numpy as np, pandas as pd, time, csv, os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
OHLCV_PATH = str(sorted(DATA_DIR.glob('all_ohlcv_20170601_*.parquet'))[-1])
BENCH_PATH = str(DATA_DIR / 'kospi_yf.parquet')

# 후보 국면 지표 + 팩터 조합 (Phase 3 결과에서)
ATK = dict(v=20, q=0, g=45, m=35, mom='12m', entry=10, exit=11, slots=5,
           s1='rev_z', s2='oca_z', s3='op_margin_z', w1=0.5, w2=0.3, w3=0.2)
DEF = dict(v=30, q=15, g=25, m=30, mom='6m', entry=3, exit=4, slots=5,
           s1='rev_z', s2='oca_z', s3=None, w1=0.7, w2=None, w3=None)

CANDIDATES = [
    'BL126_40pct_5d', 'DUAL_KP200+BS126_50_OR_5d', 'MA150_3d',
    'RSI14_45_3d', 'MOM252_3d', 'SLOPE200_10w_10d', 'DD15pct_3d',
    'GC20x60_5d', 'KD_MA150_3d', 'BS126_30pct_5d', 'BU126_40pct_3d',
    'MA200_5d', 'NO_REGIME',
]


def load_rankings():
    rk = {}
    for d_dir in [Path(__file__).parent / 'bt_extended', Path(__file__).parent / 'bt_test_A']:
        for f in sorted(d_dir.glob('ranking_*.json')):
            d = f.stem.replace('ranking_', '')
            rk[d] = json.load(open(f, 'r', encoding='utf-8')).get('rankings', [])
    return rk


def run_wf_worker(args):
    """Walk-Forward: 4기간 각각 시뮬레이션"""
    from turbo_simulator import TurboSimulator
    tasks = args  # list of (regime_name, regime_dict, period_name, start, end)

    rk = load_rankings()
    all_dates = sorted(rk.keys())
    ohlcv = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    bench = pd.read_parquet(BENCH_PATH)
    tsim = TurboSimulator(rk, all_dates, ohlcv, bench=bench)

    results = []
    for regime_name, regime_dict, period_name, start, end in tasks:
        # 해당 기간 날짜만 필터
        period_dates = [d for d in all_dates if start <= d <= end]
        if len(period_dates) < 60:
            results.append((regime_name, period_name, start, end, 0, 0, 0, 0, 0, len(period_dates)))
            continue

        # 기간 제한된 TurboSim 생성
        period_rk = {d: rk[d] for d in period_dates}
        tsim_p = TurboSimulator(period_rk, period_dates, ohlcv, bench=bench)

        atk_p = dict(v=ATK['v']/100, q=ATK['q']/100, g=ATK['g']/100, m=ATK['m']/100,
                     g_rev=0.5, entry=ATK['entry'], exit=ATK['exit'], slots=ATK['slots'],
                     mom=ATK['mom'])
        def_p = dict(v=DEF['v']/100, q=DEF['q']/100, g=DEF['g']/100, m=DEF['m']/100,
                     g_rev=DEF['w1'], entry=DEF['entry'], exit=DEF['exit'], slots=DEF['slots'],
                     mom=DEF['mom'])

        if regime_name == 'NO_REGIME':
            r = tsim_p.run_fast(atk_p['v'], atk_p['q'], atk_p['g'], atk_p['m'], 0.5,
                entry_param=ATK['entry'], exit_param=ATK['exit'], max_slots=ATK['slots'],
                mom_type=ATK['mom'], stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1=ATK['s1'], g_sub2=ATK['s2'], g_sub3=ATK['s3'],
                g_w1=ATK['w1'], g_w2=ATK['w2'], g_w3=ATK['w3'])
        else:
            r = tsim_p.run_regime(
                defense_params=def_p, offense_params=atk_p,
                regime_dict=regime_dict,
                stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1_o=ATK['s1'], g_sub2_o=ATK['s2'],
                g_sub3_o=ATK['s3'], g_w1_o=ATK['w1'], g_w2_o=ATK['w2'], g_w3_o=ATK['w3'],
                g_sub1_d=DEF['s1'], g_sub2_d=DEF['s2'],
                g_sub3_d=DEF['s3'], g_w1_d=DEF['w1'], g_w2_d=DEF['w2'], g_w3_d=DEF['w3'],
            )
        results.append((regime_name, period_name, start, end,
                        r['calmar'], r['cagr'], r['mdd'], r.get('sharpe', 0), r.get('sortino', 0),
                        len(period_dates)))
    return results


def run_stability_worker(args):
    """인접 안정성: 팩터 ±5 이웃"""
    from turbo_simulator import TurboSimulator
    tasks = args

    rk = load_rankings()
    dates = sorted(rk.keys())
    ohlcv = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    bench = pd.read_parquet(BENCH_PATH)
    tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)

    results = []
    for regime_name, regime_dict, v, q, g, m in tasks:
        atk_p = dict(v=v/100, q=q/100, g=g/100, m=m/100,
                     g_rev=0.5, entry=ATK['entry'], exit=ATK['exit'], slots=ATK['slots'],
                     mom=ATK['mom'])
        def_p = dict(v=DEF['v']/100, q=DEF['q']/100, g=DEF['g']/100, m=DEF['m']/100,
                     g_rev=DEF['w1'], entry=DEF['entry'], exit=DEF['exit'], slots=DEF['slots'],
                     mom=DEF['mom'])

        if regime_name == 'NO_REGIME':
            r = tsim.run_fast(v/100, q/100, g/100, m/100, 0.5,
                entry_param=ATK['entry'], exit_param=ATK['exit'], max_slots=ATK['slots'],
                mom_type=ATK['mom'], stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1=ATK['s1'], g_sub2=ATK['s2'], g_sub3=ATK['s3'],
                g_w1=ATK['w1'], g_w2=ATK['w2'], g_w3=ATK['w3'])
        else:
            r = tsim.run_regime(
                defense_params=def_p, offense_params=atk_p,
                regime_dict=regime_dict,
                stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1_o=ATK['s1'], g_sub2_o=ATK['s2'],
                g_sub3_o=ATK['s3'], g_w1_o=ATK['w1'], g_w2_o=ATK['w2'], g_w3_o=ATK['w3'],
                g_sub1_d=DEF['s1'], g_sub2_d=DEF['s2'],
                g_sub3_d=DEF['s3'], g_w1_d=DEF['w1'], g_w2_d=DEF['w2'], g_w3_d=DEF['w3'],
            )
        results.append((regime_name, v, q, g, m, r['calmar'], r['cagr'], r['mdd']))
    return results


if __name__ == '__main__':
    t0 = time.time()

    # 국면 지표 재생성 (Phase 3 스크립트에서 가져옴)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from v78_phase3_regime import (get_kospi_price, make_ma_regime, make_momentum_regime,
        make_volatility_regime, make_drawdown_regime, make_rsi_regime,
        make_golden_cross_regime, make_ma_slope_regime, make_all_attack_regime)
    from v78_phase3_supplement import (make_breadth_regime, make_kosdaq_regime,
        make_dual_regime, make_kospi_ma_regime)

    price = get_kospi_price()
    ohlcv_df = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    mc_dir = DATA_DIR

    rk_dates = []
    for d_dir in [Path('bt_extended'), Path('bt_test_A')]:
        for f in sorted(d_dir.glob('ranking_*.json')):
            rk_dates.append(f.stem.replace('ranking_', ''))
    rk_dates = sorted(rk_dates)

    print('국면 지표 생성 중...')
    regimes = {}
    regimes['NO_REGIME'] = make_all_attack_regime(rk_dates)
    regimes['BL126_40pct_5d'] = make_breadth_regime(ohlcv_df, mc_dir, 126, 40, 5, 'large')
    regimes['BL126_40pct_3d'] = make_breadth_regime(ohlcv_df, mc_dir, 126, 40, 3, 'large')
    regimes['MA150_3d'] = make_ma_regime(price, 150, 3)
    regimes['MA150_5d'] = make_ma_regime(price, 150, 5)
    regimes['MA200_5d'] = make_ma_regime(price, 200, 5)
    regimes['RSI14_45_3d'] = make_rsi_regime(price, 14, 45, 3)
    regimes['MOM252_3d'] = make_momentum_regime(price, 252, 3)
    regimes['SLOPE200_10w_10d'] = make_ma_slope_regime(price, 200, 10, 10)
    regimes['DD15pct_3d'] = make_drawdown_regime(price, -15, 3)
    regimes['GC20x60_5d'] = make_golden_cross_regime(price, 20, 60, 5)
    regimes['KD_MA150_3d'] = make_kosdaq_regime(150, 3)
    regimes['BS126_30pct_5d'] = make_breadth_regime(ohlcv_df, mc_dir, 126, 30, 5, 'small')
    regimes['BU126_40pct_3d'] = make_breadth_regime(ohlcv_df, mc_dir, 126, 40, 3, 'universe')

    # 듀얼 지표
    kp200_5d = regimes['MA200_5d']
    bs50 = make_breadth_regime(ohlcv_df, mc_dir, 126, 50, 5, 'small')
    regimes['DUAL_KP200+BS126_50_OR_5d'] = make_dual_regime(kp200_5d, bs50, 'OR')

    print(f'지표 {len(regimes)}개 생성 ({time.time()-t0:.0f}초)')

    # =============================================
    # Walk-Forward: 4기간
    # =============================================
    WF_PERIODS = [
        ('P1_2018-19', '20180702', '20191231'),
        ('P2_2020-21', '20200102', '20211231'),
        ('P3_2022-23', '20220103', '20231229'),
        ('P4_2024-26', '20240102', '20260408'),
    ]

    wf_tasks = []
    for rname in regimes:
        for pname, start, end in WF_PERIODS:
            wf_tasks.append((rname, regimes[rname], pname, start, end))

    print(f'\n=== Walk-Forward: {len(wf_tasks)}개 (3워커) ===')
    chunk_size = len(wf_tasks) // 3 + 1
    chunks = [wf_tasks[i:i+chunk_size] for i in range(0, len(wf_tasks), chunk_size)]

    wf_results = []
    with ProcessPoolExecutor(max_workers=3) as exe:
        futs = {exe.submit(run_wf_worker, chunk): i for i, chunk in enumerate(chunks)}
        for fut in as_completed(futs):
            wf_results.extend(fut.result())
            print(f'  워커{futs[fut]}: ({time.time()-t0:.0f}초)', flush=True)

    # WF 결과 정리
    print(f'\n=== Walk-Forward 결과 ===')
    wf_df = pd.DataFrame(wf_results, columns=['regime','period','start','end','cal','cagr','mdd','sharpe','sortino','days'])

    # 후보별 WF 요약
    print(f'\n{"regime":35s} {"P1":>8s} {"P2":>8s} {"P3":>8s} {"P4":>8s} {"min":>8s} {"all>1.5":>8s}')
    wf_summary = []
    for rname in regimes:
        sub = wf_df[wf_df.regime == rname].sort_values('start')
        cals = sub.cal.tolist()
        if len(cals) == 4:
            min_cal = min(cals)
            all_pass = all(c >= 1.5 for c in cals)
            print(f'{rname:35s} {cals[0]:8.2f} {cals[1]:8.2f} {cals[2]:8.2f} {cals[3]:8.2f} {min_cal:8.2f} {"PASS" if all_pass else "FAIL":>8s}')
            wf_summary.append((rname, cals, min_cal, all_pass))

    # =============================================
    # 인접 안정성: ATK 팩터 ±5 이웃 (V, G, M 각각)
    # =============================================
    t1 = time.time()
    print(f'\n=== 인접 안정성 ({time.time()-t0:.0f}초) ===')

    stability_tasks = []
    base_v, base_q, base_g, base_m = 20, 0, 45, 35
    neighbors = set()
    for dv in [-10, -5, 0, 5, 10]:
        for dg in [-10, -5, 0, 5, 10]:
            v = base_v + dv
            g = base_g + dg
            m = 100 - v - base_q - g
            if v < 0 or g < 0 or m < 10 or m > 60 or v > 40:
                continue
            neighbors.add((v, base_q, g, m))

    print(f'이웃 조합: {len(neighbors)}개 × {len(regimes)}개 지표 = {len(neighbors)*len(regimes)}개')
    for rname in regimes:
        for v, q, g, m in neighbors:
            stability_tasks.append((rname, regimes[rname], v, q, g, m))

    chunk_size = len(stability_tasks) // 3 + 1
    chunks = [stability_tasks[i:i+chunk_size] for i in range(0, len(stability_tasks), chunk_size)]

    stab_results = []
    with ProcessPoolExecutor(max_workers=3) as exe:
        futs = {exe.submit(run_stability_worker, chunk): i for i, chunk in enumerate(chunks)}
        for fut in as_completed(futs):
            stab_results.extend(fut.result())
            print(f'  워커{futs[fut]}: ({time.time()-t0:.0f}초)', flush=True)

    stab_df = pd.DataFrame(stab_results, columns=['regime','v','q','g','m','cal','cagr','mdd'])

    # 안정성 요약: 이웃 중 Cal >= 2.0 비율
    print(f'\n{"regime":35s} {"이웃수":>6s} {"Cal>=2":>8s} {"비율":>8s} {"min":>8s} {"mean":>8s}')
    stab_summary = []
    for rname in regimes:
        sub = stab_df[stab_df.regime == rname]
        n_total = len(sub)
        n_pass = len(sub[sub.cal >= 2.0])
        ratio = n_pass / n_total if n_total > 0 else 0
        min_cal = sub.cal.min()
        mean_cal = sub.cal.mean()
        print(f'{rname:35s} {n_total:6d} {n_pass:8d} {ratio:8.1%} {min_cal:8.2f} {mean_cal:8.2f}')
        stab_summary.append((rname, n_total, n_pass, ratio, min_cal, mean_cal))

    # =============================================
    # 종합 순위
    # =============================================
    print(f'\n{"="*80}')
    print('종합 평가')
    print(f'{"="*80}')

    # Phase 3 Cal 로드
    main_df = pd.read_csv(RESULT_DIR / 'v78_phase3_regime.csv')
    supp_df = pd.read_csv(RESULT_DIR / 'v78_phase3_supplement.csv')
    p3_df = pd.concat([main_df, supp_df]).drop_duplicates(subset=['regime','atk','def'])

    final_rows = []
    for rname in regimes:
        # Phase 3 Cal
        p3_row = p3_df[(p3_df.regime == rname) & (p3_df.atk == 'V20Q0G45M35')]
        p3_cal = p3_row.cal.max() if len(p3_row) > 0 else 0
        p3_cagr = p3_row[p3_row.cal == p3_cal].cagr.iloc[0] if len(p3_row) > 0 else 0
        p3_mdd = p3_row[p3_row.cal == p3_cal].mdd.iloc[0] if len(p3_row) > 0 else 0
        p3_sw = int(p3_row[p3_row.cal == p3_cal].switches.iloc[0]) if len(p3_row) > 0 else 0

        # WF
        wf_match = [s for s in wf_summary if s[0] == rname]
        wf_min = wf_match[0][2] if wf_match else 0
        wf_pass = wf_match[0][3] if wf_match else False
        wf_cals = wf_match[0][1] if wf_match else [0,0,0,0]

        # 안정성
        stab_match = [s for s in stab_summary if s[0] == rname]
        stab_ratio = stab_match[0][3] if stab_match else 0
        stab_min = stab_match[0][4] if stab_match else 0
        stab_mean = stab_match[0][5] if stab_match else 0

        # 종합 점수 = Cal×0.3 + WF_min×0.3 + 안정성비율×Cal×0.2 + (전환<30 보너스)×0.2
        sw_bonus = 1.0 if p3_sw <= 30 else (0.7 if p3_sw <= 50 else 0.3)
        total = p3_cal*0.3 + wf_min*0.3 + stab_ratio*p3_cal*0.2 + sw_bonus*0.2

        final_rows.append((rname, p3_cal, p3_cagr, p3_mdd, p3_sw,
                          wf_cals, wf_min, wf_pass,
                          stab_ratio, stab_min, stab_mean, total))

    final_rows.sort(key=lambda x: -x[11])

    print(f'\n{"순위":>4s} {"regime":35s} {"Cal":>6s} {"CAGR":>7s} {"MDD":>7s} {"sw":>4s} {"WF_min":>7s} {"WF":>5s} {"안정%":>6s} {"종합":>6s}')
    for i, (rname, cal, cagr, mdd, sw, wfc, wfm, wfp, sr, sm, smn, total) in enumerate(final_rows):
        wf_str = 'PASS' if wfp else 'FAIL'
        print(f'{i+1:4d} {rname:35s} {cal:6.2f} {cagr:6.1f}% {mdd:6.1f}% {sw:4d} {wfm:7.2f} {wf_str:>5s} {sr:5.0%} {total:6.2f}')
        print(f'     WF: P1={wfc[0]:.2f} P2={wfc[1]:.2f} P3={wfc[2]:.2f} P4={wfc[3]:.2f}')

    # CSV 저장
    with open(RESULT_DIR / 'v78_phase45_final.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['rank','regime','cal','cagr','mdd','switches','wf_p1','wf_p2','wf_p3','wf_p4','wf_min','wf_pass','stab_ratio','stab_min','stab_mean','total'])
        for i, (rname, cal, cagr, mdd, sw, wfc, wfm, wfp, sr, sm, smn, total) in enumerate(final_rows):
            w.writerow([i+1, rname, cal, cagr, mdd, sw, wfc[0], wfc[1], wfc[2], wfc[3], wfm, wfp, sr, sm, smn, total])

    print(f'\n전체: {time.time()-t0:.0f}초 ({(time.time()-t0)/60:.1f}분)')
    print(f'저장: {RESULT_DIR / "v78_phase45_final.csv"}')
