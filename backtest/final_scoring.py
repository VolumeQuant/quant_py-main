"""다중 지표 + 다중 조건 종합 점수 — 진짜 best 찾기

조건 (모두 통과해야):
  1. 7.8y Cal >= baseline (1.854)
  2. 7.8y MDD <= baseline + 5%p (45%)
  3. wf_min > 0.3 (모든 시기 의미 있는 양수)
  4. WF CV < 0.4 (시기별 안정)

종합 점수 (조건 통과 후):
  = 7.8y Cal * 0.4 + 7.8y Sortino * 0.2 + wf_min * 0.3 + (1 - wf_cv) * 0.1
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator
from compare_optf_bt import load_rankings
from fast_grid_all import calc_regime_param, fast_bt

PROJECT = Path(__file__).parent.parent

WF = [
    ('2018H2-19', '20180702', '20191231'),
    ('2020-21',   '20200102', '20211230'),
    ('2022-23',   '20220103', '20231228'),
    ('2024-26',   '20240102', '20260512'),
]


def main():
    print('=== 다중 지표 + 다중 조건 종합 평가 ===\n')
    OHLCV = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()

    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates_all = sorted(set(boost) & set(defense))
    d_78 = [d for d in dates_all if '20180702' <= d <= '20260512']

    WF_DATES = []
    for label, s, e in WF:
        d_sub = [d for d in dates_all if s <= d <= e]
        if len(d_sub) >= 50:
            WF_DATES.append((label, d_sub))

    print('  TSIM 초기화...', flush=True)
    t0 = time.time()
    tsim_b = TurboSimulator({d: boost[d]['rankings'] for d in dates_all}, dates_all, ohlcv)
    tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in dates_all}, dates_all, ohlcv)
    print(f'  완료: {time.time()-t0:.1f}초\n')

    def measure(params):
        # 7.8y 전체
        reg_78 = calc_regime_param(d_78, kospi, params['ma_w'], params['cd'])
        r78 = fast_bt(tsim_b, tsim_d, d_78, reg_78,
                      params['V_b'], params['Q_b'], params['G_b'], params['M_b'],
                      params['V_d'], params['Q_d'], params['G_d'], params['M_d'],
                      params['gs1_b'], params['gs2_b'], params['gs1_d'], params['gs2_d'],
                      params['g_rev_b'], params['g_rev_d'], params['mom_b'], params['mom_d'],
                      params['eb'], params['xb'], params['sb'],
                      params['ed'], params['xd'], params['sd'],
                      sl=params['sl'], ts=params['ts'], ts_cd=params['ts_cd'])
        # WF
        wf_cals = []
        for label, d_sub in WF_DATES:
            reg = calc_regime_param(d_sub, kospi, params['ma_w'], params['cd'])
            rr = fast_bt(tsim_b, tsim_d, d_sub, reg,
                         params['V_b'], params['Q_b'], params['G_b'], params['M_b'],
                         params['V_d'], params['Q_d'], params['G_d'], params['M_d'],
                         params['gs1_b'], params['gs2_b'], params['gs1_d'], params['gs2_d'],
                         params['g_rev_b'], params['g_rev_d'], params['mom_b'], params['mom_d'],
                         params['eb'], params['xb'], params['sb'],
                         params['ed'], params['xd'], params['sd'],
                         sl=params['sl'], ts=params['ts'], ts_cd=params['ts_cd'])
            wf_cals.append(rr['calmar'])
        wf_min = min(wf_cals); wf_mean = np.mean(wf_cals)
        wf_cv = np.std(wf_cals) / wf_mean if wf_mean > 0 else 99
        return {
            'cal_78': r78['calmar'], 'cagr_78': r78['cagr'], 'mdd_78': r78['mdd'],
            'sharpe_78': r78['sharpe'], 'sortino_78': r78['sortino'], 'total_78': r78['total'],
            'wf_min': wf_min, 'wf_mean': wf_mean, 'wf_cv': wf_cv,
            'wf_2018': wf_cals[0], 'wf_2020': wf_cals[1],
            'wf_2022': wf_cals[2], 'wf_2024': wf_cals[3],
        }

    BASE_PARAMS = {
        'ma_w': 170, 'cd': 8,
        'V_b': 0.15, 'Q_b': 0, 'G_b': 0.55, 'M_b': 0.30,
        'V_d': 0.30, 'Q_d': 0.15, 'G_d': 0.15, 'M_d': 0.40,
        'gs1_b': 'rev_z', 'gs2_b': 'oca_z', 'gs1_d': 'rev_z', 'gs2_d': 'oca_z',
        'g_rev_b': 0.6, 'g_rev_d': 0.7, 'mom_b': '12m', 'mom_d': '6m-1m',
        'eb': 3, 'xb': 6, 'sb': 3, 'ed': 3, 'xd': 6, 'sd': 5,
        'sl': -0.10, 'ts': -0.15, 'ts_cd': 2,
    }

    base = measure(BASE_PARAMS)
    BASE_CAL = base['cal_78']
    BASE_MDD = base['mdd_78']
    print(f'baseline: 7.8y Cal {base["cal_78"]:.3f} CAGR {base["cagr_78"]:.1f}% MDD {base["mdd_78"]:.1f}% Sharpe {base["sharpe_78"]:.2f} Sortino {base["sortino_78"]:.2f}')
    print(f'  WF: 2018:{base["wf_2018"]:.2f} 2020:{base["wf_2020"]:.2f} 2022:{base["wf_2022"]:.2f} 2024:{base["wf_2024"]:.2f} | min {base["wf_min"]:.3f} CV {base["wf_cv"]:.3f}\n')

    # 통과 조건
    GATE_CAL = BASE_CAL  # 7.8y Cal >= baseline
    GATE_MDD = BASE_MDD + 5  # MDD <= baseline + 5%p
    GATE_WF_MIN = 0.3
    GATE_WF_CV = 0.4

    # 모든 stage CSV에서 후보 추출 (각 stage Top 20)
    print('각 stage CSV에서 Top 20 후보 추출...')
    candidates = []
    csv_files = ['multi_stage1_regime.csv', 'multi_stage2_boost.csv', 'multi_stage3_def.csv',
                 'multi_stage4_gsub.csv', 'multi_stage5_entry.csv', 'multi_stage6_sl.csv']
    seen = set()
    for csv in csv_files:
        fp = PROJECT/'backtest'/csv
        if not fp.exists(): continue
        df = pd.read_csv(fp)
        # Top 20 by score
        if 'score' in df.columns:
            df = df.sort_values('score', ascending=False).head(20)
        for _, r in df.iterrows():
            p = {**BASE_PARAMS}
            for k in BASE_PARAMS:
                if k in r and pd.notna(r[k]):
                    p[k] = r[k]
            key = tuple(sorted(p.items()))
            if key not in seen:
                seen.add(key)
                candidates.append(p)
    print(f'  총 {len(candidates)} 후보')

    # 각 후보 측정
    print(f'\n측정 중 ({len(candidates)} × 5 BT)...', flush=True)
    t0 = time.time()
    results = []
    for i, p in enumerate(candidates):
        m = measure(p)
        results.append({**p, **m})
        if (i+1) % 20 == 0:
            print(f'  {i+1}/{len(candidates)} ({(time.time()-t0)/60:.1f}분)')

    # 통과 후보 필터링
    passed = [r for r in results
              if r['cal_78'] >= GATE_CAL and r['mdd_78'] <= GATE_MDD
              and r['wf_min'] >= GATE_WF_MIN and r['wf_cv'] <= GATE_WF_CV]
    print(f'\n통과 (7.8y Cal>={GATE_CAL:.2f}, MDD<={GATE_MDD:.0f}%, wf_min>={GATE_WF_MIN}, CV<={GATE_WF_CV}): {len(passed)}')

    # 종합 점수
    for r in passed:
        r['final_score'] = (r['cal_78'] * 0.4 + r['sortino_78'] * 0.2 +
                            r['wf_min'] * 0.3 + (1 - r['wf_cv']) * 0.1)

    passed.sort(key=lambda x: -x['final_score'])

    print('\n=== 통과 후보 Top 10 ===')
    for r in passed[:10]:
        print(f'  Cal {r["cal_78"]:.2f} CAGR {r["cagr_78"]:.0f}% MDD {r["mdd_78"]:.0f}% Sortino {r["sortino_78"]:.2f} | wf_min {r["wf_min"]:.2f} CV {r["wf_cv"]:.2f} | score {r["final_score"]:.3f}')
        print(f'    국면 MA{r["ma_w"]} {r["cd"]}d | B V{int(r["V_b"]*100)}Q{int(r["Q_b"]*100)}G{int(r["G_b"]*100)}M{int(r["M_b"]*100)} | D V{int(r["V_d"]*100)}Q{int(r["Q_d"]*100)}G{int(r["G_d"]*100)}M{int(r["M_d"]*100)}')
        print(f'    gs_b {r["gs1_b"]}/{r["gs2_b"]} mom_b {r["mom_b"]} g_rev_b {r["g_rev_b"]:.1f} | sb{r["sb"]} sd{r["sd"]} | SL{r["sl"]:+.2f} TS{r["ts"]:+.2f} cd{r["ts_cd"]}')

    # CSV 저장
    pd.DataFrame(results).to_csv(PROJECT/'backtest'/'final_all_candidates.csv', index=False)
    pd.DataFrame(passed).to_csv(PROJECT/'backtest'/'final_passed.csv', index=False)
    print(f'\n저장: final_all_candidates.csv ({len(results)}), final_passed.csv ({len(passed)})')

    if passed:
        print(f'\n🏆 최종 BEST 파라미터:')
        b = passed[0]
        for k in ['ma_w','cd','V_b','Q_b','G_b','M_b','V_d','Q_d','G_d','M_d',
                  'gs1_b','gs2_b','g_rev_b','mom_b','eb','xb','sb','ed','xd','sd','sl','ts','ts_cd']:
            print(f'  {k}: {b[k]}')


if __name__ == '__main__':
    main()
