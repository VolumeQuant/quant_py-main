"""다중 제약 그리드 — 7.8y 단일 + WF 4구간 안정성

종합 점수 = min(WF cal) (모든 시기 통과 원칙)
필터 = 7.8y >= baseline AND WF CV < 0.4 AND WF min > 0
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
    print('=== 다중 제약 그리드 (7.8y + WF 4구간) ===\n')
    OHLCV = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()

    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates_all = sorted(set(boost) & set(defense))
    d_78 = [d for d in dates_all if '20180702' <= d <= '20260512']

    # WF 구간 dates
    WF_DATES = []
    for label, s, e in WF:
        d_sub = [d for d in dates_all if s <= d <= e]
        if len(d_sub) >= 50:
            WF_DATES.append((label, d_sub))

    print(f'  거래일: 7.8y {len(d_78)}, WF {len(WF_DATES)}구간')
    print(f'\n  TSIM 초기화...', flush=True)
    t0 = time.time()
    tsim_b = TurboSimulator({d: boost[d]['rankings'] for d in dates_all}, dates_all, ohlcv)
    tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in dates_all}, dates_all, ohlcv)
    print(f'  완료: {time.time()-t0:.1f}초\n', flush=True)

    def score_combo(params):
        """7.8y 측정 + WF 4구간 측정 → 종합 점수"""
        # 7.8y
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
        # 종합 점수: min(7.8y, wf_min×2) — 양쪽 통과
        # 또는 wf_min 만 (가장 약한 시기)
        score = wf_min  # 가장 약한 시기 Cal이 곧 시스템 약점
        return {'cal_78':r78['calmar'], 'cagr_78':r78['cagr'], 'mdd_78':r78['mdd'],
                'wf_min':wf_min, 'wf_mean':wf_mean, 'wf_cv':wf_cv,
                'wf_2018':wf_cals[0] if len(wf_cals)>0 else 0,
                'wf_2020':wf_cals[1] if len(wf_cals)>1 else 0,
                'wf_2022':wf_cals[2] if len(wf_cals)>2 else 0,
                'wf_2024':wf_cals[3] if len(wf_cals)>3 else 0,
                'score':score}

    BASE_PARAMS = {
        'ma_w': 170, 'cd': 8,
        'V_b': 0.15, 'Q_b': 0, 'G_b': 0.55, 'M_b': 0.30,
        'V_d': 0.30, 'Q_d': 0.15, 'G_d': 0.15, 'M_d': 0.40,
        'gs1_b': 'rev_z', 'gs2_b': 'oca_z', 'gs1_d': 'rev_z', 'gs2_d': 'oca_z',
        'g_rev_b': 0.6, 'g_rev_d': 0.7, 'mom_b': '12m', 'mom_d': '6m-1m',
        'eb': 3, 'xb': 6, 'sb': 3, 'ed': 3, 'xd': 6, 'sd': 5,
        'sl': -0.10, 'ts': -0.15, 'ts_cd': 2,
    }

    print('baseline 측정...', flush=True)
    t0 = time.time()
    base_r = score_combo(BASE_PARAMS)
    print(f'  baseline 측정 시간: {time.time()-t0:.1f}초')
    print(f'  baseline 7.8y {base_r["cal_78"]:.3f} | wf_min {base_r["wf_min"]:.3f} | wf_cv {base_r["wf_cv"]:.3f}')
    print(f'  WF: 2018H2-19 {base_r["wf_2018"]:.2f} | 2020-21 {base_r["wf_2020"]:.2f} | 2022-23 {base_r["wf_2022"]:.2f} | 2024-26 {base_r["wf_2024"]:.2f}\n')

    BASE_78 = base_r['cal_78']

    def show_top(arr, label, top=5):
        arr.sort(key=lambda x: -x['score'])
        print(f'  Top {top} (score = wf_min):')
        for r in arr[:top]:
            gate78 = '✓' if r['cal_78'] >= BASE_78 else '✗'
            cv_ok = '✓' if r['wf_cv'] < 0.4 else '✗'
            print(f'    78y{gate78} CV{cv_ok}({r["wf_cv"]:.2f}) | 7.8y {r["cal_78"]:.2f} | wf_min {r["wf_min"]:.2f} | 2018:{r["wf_2018"]:.2f} 2020:{r["wf_2020"]:.2f} 2022:{r["wf_2022"]:.2f} 2024:{r["wf_2024"]:.2f}')

    # ═══ Stage 1: 국면 ═══
    print('=== Stage 1: 국면 ===', flush=True)
    s1 = []; t0 = time.time()
    for ma_w in [120, 150, 170, 200, 250]:
        for cd in [3, 5, 7, 8, 10, 15]:
            p = {**BASE_PARAMS, 'ma_w':ma_w, 'cd':cd}
            r = score_combo(p)
            s1.append({**p, **r})
    print(f'  {len(s1)}조합 ({(time.time()-t0)/60:.1f}분)')
    show_top(s1, 'Stage 1')
    pd.DataFrame(s1).to_csv(PROJECT/'backtest'/'multi_stage1_regime.csv', index=False)
    BEST = {**BASE_PARAMS, 'ma_w':s1[0]['ma_w'], 'cd':s1[0]['cd']}

    # ═══ Stage 2: Boost ═══
    print('\n=== Stage 2: Boost VQGM ===', flush=True)
    s2 = []; t0 = time.time()
    for V in [0, 5, 10, 15, 20, 25]:
        for Q in [0, 5, 10]:
            for G in [40, 50, 55, 60, 70]:
                M = 100 - V - Q - G
                if M < 10 or M > 40: continue
                p = {**BEST, 'V_b':V/100,'Q_b':Q/100,'G_b':G/100,'M_b':M/100}
                r = score_combo(p)
                s2.append({**p, **r, 'V':V,'Q':Q,'G':G,'M':M})
    print(f'  {len(s2)}조합 ({(time.time()-t0)/60:.1f}분)')
    show_top(s2, 'Stage 2')
    pd.DataFrame(s2).to_csv(PROJECT/'backtest'/'multi_stage2_boost.csv', index=False)
    BEST = {**BEST, 'V_b':s2[0]['V_b'],'Q_b':s2[0]['Q_b'],'G_b':s2[0]['G_b'],'M_b':s2[0]['M_b']}

    # ═══ Stage 3: Defense ═══
    print('\n=== Stage 3: Defense VQGM ===', flush=True)
    s3 = []; t0 = time.time()
    for V in [15, 20, 25, 30, 35, 40]:
        for Q in [5, 10, 15, 20]:
            for G in [10, 15, 20, 25]:
                M = 100 - V - Q - G
                if M < 25 or M > 55: continue
                p = {**BEST, 'V_d':V/100,'Q_d':Q/100,'G_d':G/100,'M_d':M/100}
                r = score_combo(p)
                s3.append({**p, **r, 'V':V,'Q':Q,'G':G,'M':M})
    print(f'  {len(s3)}조합 ({(time.time()-t0)/60:.1f}분)')
    show_top(s3, 'Stage 3')
    pd.DataFrame(s3).to_csv(PROJECT/'backtest'/'multi_stage3_def.csv', index=False)
    BEST = {**BEST, 'V_d':s3[0]['V_d'],'Q_d':s3[0]['Q_d'],'G_d':s3[0]['G_d'],'M_d':s3[0]['M_d']}

    # ═══ Stage 4: G_SUB ═══
    print('\n=== Stage 4: G_SUB + MOM ===', flush=True)
    G_SUBS = [('rev_z','oca_z'),('rev_z','gp_growth_z'),('rev_z','rev_accel_z'),
              ('oca_z','gp_growth_z'),('rev_accel_z','oca_z'),('gp_growth_z','op_margin_z')]
    MOMS = ['6m','6m-1m','12m','12m-1m']
    s4 = []; t0 = time.time()
    for gs1, gs2 in G_SUBS:
        for mom in MOMS:
            for g_rev in [0.5, 0.6, 0.7, 0.8]:
                p = {**BEST, 'gs1_b':gs1,'gs2_b':gs2,'g_rev_b':g_rev,'mom_b':mom}
                r = score_combo(p)
                s4.append({**p, **r, 'g_rev':g_rev,'gs1':gs1,'gs2':gs2,'mom':mom})
    print(f'  {len(s4)}조합 ({(time.time()-t0)/60:.1f}분)')
    show_top(s4, 'Stage 4')
    pd.DataFrame(s4).to_csv(PROJECT/'backtest'/'multi_stage4_gsub.csv', index=False)
    BEST = {**BEST, 'gs1_b':s4[0]['gs1_b'],'gs2_b':s4[0]['gs2_b'],'g_rev_b':s4[0]['g_rev_b'],'mom_b':s4[0]['mom_b']}

    # ═══ Stage 5: 진입/슬롯 ═══
    print('\n=== Stage 5: 진입/이탈/슬롯 ===', flush=True)
    s5 = []; t0 = time.time()
    for eb in [2,3,5]:
        for xb in [5,6,8]:
            for sb in [2,3,5]:
                for ed in [2,3,5]:
                    for xd in [5,6,8]:
                        for sd in [3,5,7]:
                            p = {**BEST, 'eb':eb,'xb':xb,'sb':sb,'ed':ed,'xd':xd,'sd':sd}
                            r = score_combo(p)
                            s5.append({**p, **r})
    print(f'  {len(s5)}조합 ({(time.time()-t0)/60:.1f}분)')
    show_top(s5, 'Stage 5')
    pd.DataFrame(s5).to_csv(PROJECT/'backtest'/'multi_stage5_entry.csv', index=False)
    BEST = {**BEST, 'eb':s5[0]['eb'],'xb':s5[0]['xb'],'sb':s5[0]['sb'],'ed':s5[0]['ed'],'xd':s5[0]['xd'],'sd':s5[0]['sd']}

    # ═══ Stage 6: SL/TS ═══
    print('\n=== Stage 6: SL/TS/cd ===', flush=True)
    s6 = []; t0 = time.time()
    for sl in [-0.05,-0.07,-0.10,-0.15,-0.20]:
        for ts_v in [-0.10,-0.15,-0.20,-0.25]:
            for cd in [0,1,2,3,5]:
                p = {**BEST, 'sl':sl,'ts':ts_v,'ts_cd':cd}
                r = score_combo(p)
                s6.append({**p, **r})
    print(f'  {len(s6)}조합 ({(time.time()-t0)/60:.1f}분)')
    show_top(s6, 'Stage 6')
    pd.DataFrame(s6).to_csv(PROJECT/'backtest'/'multi_stage6_sl.csv', index=False)
    BEST_FINAL = {**BEST, 'sl':s6[0]['sl'],'ts':s6[0]['ts'],'ts_cd':s6[0]['ts_cd']}

    print(f'\n{"="*60}')
    print(f'🏆 최종 BEST (다중 제약: 7.8y + WF 시기별 안정성)')
    print(f'{"="*60}')
    final = score_combo(BEST_FINAL)
    print(f'  7.8y Cal {final["cal_78"]:.3f} (baseline {BASE_78:.3f})')
    print(f'  WF: 2018:{final["wf_2018"]:.2f} | 2020:{final["wf_2020"]:.2f} | 2022:{final["wf_2022"]:.2f} | 2024:{final["wf_2024"]:.2f}')
    print(f'  WF min {final["wf_min"]:.3f}, mean {final["wf_mean"]:.3f}, CV {final["wf_cv"]:.3f}')
    print()
    for k, v in BEST_FINAL.items():
        if k not in ['gs1_d','gs2_d','g_rev_d','mom_d']:
            print(f'  {k}: {v}')


if __name__ == '__main__':
    main()
