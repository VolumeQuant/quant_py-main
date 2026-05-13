"""그리드 best 검증 — WF + 인접 안정성 + 양쪽 BT + 더 넓은 그리드"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, _calc_metrics
from compare_optf_bt import load_rankings
from fast_grid_all import calc_regime_param, fast_bt

PROJECT = Path(__file__).parent.parent

# 새 BEST 파라미터
BEST = {
    'ma_w': 170, 'cd': 10,
    'V_b': 0.20, 'Q_b': 0.00, 'G_b': 0.50, 'M_b': 0.30,
    'V_d': 0.30, 'Q_d': 0.15, 'G_d': 0.10, 'M_d': 0.45,
    'gs1_b': 'rev_z', 'gs2_b': 'oca_z',
    'gs1_d': 'rev_z', 'gs2_d': 'oca_z',
    'g_rev_b': 0.5, 'g_rev_d': 0.7,
    'mom_b': '12m', 'mom_d': '6m-1m',
    'eb': 3, 'xb': 6, 'sb': 2,
    'ed': 3, 'xd': 6, 'sd': 7,
    'sl': -0.20, 'ts': -0.15, 'ts_cd': 1,
}


def main():
    print('=== BEST 파라미터 검증 ===')
    print(f'  {BEST}\n')

    OHLCV = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()

    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates_all = sorted(set(boost) & set(defense))

    print('TSIM 초기화...', flush=True)
    t0 = time.time()
    tsim_b = TurboSimulator({d: boost[d]['rankings'] for d in dates_all}, dates_all, ohlcv)
    tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in dates_all}, dates_all, ohlcv)
    print(f'TSIM 완료: {time.time()-t0:.1f}초\n', flush=True)

    def run_period(dates_sub, label):
        reg = calc_regime_param(dates_sub, kospi, BEST['ma_w'], BEST['cd'])
        r = fast_bt(tsim_b, tsim_d, dates_sub, reg,
                    BEST['V_b'], BEST['Q_b'], BEST['G_b'], BEST['M_b'],
                    BEST['V_d'], BEST['Q_d'], BEST['G_d'], BEST['M_d'],
                    BEST['gs1_b'], BEST['gs2_b'], BEST['gs1_d'], BEST['gs2_d'],
                    BEST['g_rev_b'], BEST['g_rev_d'], BEST['mom_b'], BEST['mom_d'],
                    BEST['eb'], BEST['xb'], BEST['sb'],
                    BEST['ed'], BEST['xd'], BEST['sd'],
                    sl=BEST['sl'], ts=BEST['ts'], ts_cd=BEST['ts_cd'])
        return r

    # ═══ 1. WF 4구간 ═══
    print('=== 1. WF 4구간 (시기별 안정성) ===')
    WF = [
        ('2018H2-19', '20180702', '20191231'),
        ('2020-21',   '20200102', '20211230'),
        ('2022-23',   '20220103', '20231228'),
        ('2024-26',   '20240102', '20260512'),
    ]
    wf_cals = []
    for label, s, e in WF:
        d_sub = [d for d in dates_all if s <= d <= e]
        if len(d_sub) < 50: continue
        r = run_period(d_sub, label)
        wf_cals.append(r['calmar'])
        print(f'  {label} ({len(d_sub)}일): Cal {r["calmar"]:.3f}  CAGR {r["cagr"]:.1f}%  MDD {r["mdd"]:.1f}%')
    wf_min = min(wf_cals); wf_mean = np.mean(wf_cals); wf_cv = np.std(wf_cals) / wf_mean
    print(f'  → min={wf_min:.3f}, mean={wf_mean:.3f}, CV={wf_cv:.3f} (CV<0.3 통과)')

    # ═══ 2. 양쪽 BT (5.25y + 7.8y) ═══
    print('\n=== 2. 양쪽 BT (5.25y + 7.8y) ===')
    d_525 = [d for d in dates_all if '20210104' <= d <= '20260330']
    d_78 = [d for d in dates_all if '20180702' <= d <= '20260330']
    r_78 = run_period(d_78, '7.8y')
    r_525 = run_period(d_525, '5.25y')
    print(f'  7.8y  Cal {r_78["calmar"]:.3f}  CAGR {r_78["cagr"]:.1f}%  MDD {r_78["mdd"]:.1f}%')
    print(f'  5.25y Cal {r_525["calmar"]:.3f}  CAGR {r_525["cagr"]:.1f}%  MDD {r_525["mdd"]:.1f}%')
    geo_mean = (r_78['calmar'] * r_525['calmar']) ** 0.5
    print(f'  기하평균: {geo_mean:.3f}')

    # ═══ 3. 인접 안정성 (각 stage best ±1) ═══
    print('\n=== 3. 인접 안정성 ===')
    print('  국면 MA{170±} × 확인일수{10±1}')
    reg_results = []
    for ma_w in [150, 170, 200]:
        for cd in [8, 10, 12]:
            reg = calc_regime_param(dates_all, kospi, ma_w, cd)
            r = fast_bt(tsim_b, tsim_d, dates_all, reg,
                        BEST['V_b'], BEST['Q_b'], BEST['G_b'], BEST['M_b'],
                        BEST['V_d'], BEST['Q_d'], BEST['G_d'], BEST['M_d'],
                        BEST['gs1_b'], BEST['gs2_b'], BEST['gs1_d'], BEST['gs2_d'],
                        BEST['g_rev_b'], BEST['g_rev_d'], BEST['mom_b'], BEST['mom_d'],
                        BEST['eb'], BEST['xb'], BEST['sb'],
                        BEST['ed'], BEST['xd'], BEST['sd'],
                        sl=BEST['sl'], ts=BEST['ts'], ts_cd=BEST['ts_cd'])
            reg_results.append((ma_w, cd, r['calmar']))
    reg_cals = [c for _,_,c in reg_results]
    reg_cv = np.std(reg_cals) / np.mean(reg_cals)
    print(f'  9 조합 Cal {min(reg_cals):.3f} ~ {max(reg_cals):.3f}, CV={reg_cv:.3f}')

    # SL/TS 인접 (best SL-0.20 ±5%p, TS-0.15 ±5%p)
    print('\n  SL/TS 인접 (SL-0.20±5, TS-0.15±5)')
    sl_results = []
    for sl in [-0.15, -0.20, -0.25]:
        for ts_v in [-0.10, -0.15, -0.20]:
            reg = calc_regime_param(dates_all, kospi, BEST['ma_w'], BEST['cd'])
            r = fast_bt(tsim_b, tsim_d, dates_all, reg,
                        BEST['V_b'], BEST['Q_b'], BEST['G_b'], BEST['M_b'],
                        BEST['V_d'], BEST['Q_d'], BEST['G_d'], BEST['M_d'],
                        BEST['gs1_b'], BEST['gs2_b'], BEST['gs1_d'], BEST['gs2_d'],
                        BEST['g_rev_b'], BEST['g_rev_d'], BEST['mom_b'], BEST['mom_d'],
                        BEST['eb'], BEST['xb'], BEST['sb'],
                        BEST['ed'], BEST['xd'], BEST['sd'],
                        sl=sl, ts=ts_v, ts_cd=BEST['ts_cd'])
            sl_results.append((sl, ts_v, r['calmar']))
    sl_cals = [c for _,_,c in sl_results]
    sl_cv = np.std(sl_cals) / np.mean(sl_cals)
    print(f'  9 조합 Cal {min(sl_cals):.3f} ~ {max(sl_cals):.3f}, CV={sl_cv:.3f}')

    # ═══ 4. 더 넓은 그리드 — 핵심 영역 dense 탐색 ═══
    print('\n=== 4. 더 넓은 그리드 (핵심 영역 dense) ===')

    print('  4a. Boost VQGM 확장 (50조합+)')
    s2 = []
    reg = calc_regime_param(dates_all, kospi, BEST['ma_w'], BEST['cd'])
    for V in [10, 15, 20, 25, 30]:
        for Q in [0, 5, 10]:
            for G in [40, 45, 50, 55, 60]:
                for M in [20, 25, 30, 35]:
                    if V+Q+G+M != 100: continue
                    r = fast_bt(tsim_b, tsim_d, dates_all, reg,
                                V/100, Q/100, G/100, M/100,
                                BEST['V_d'], BEST['Q_d'], BEST['G_d'], BEST['M_d'],
                                BEST['gs1_b'], BEST['gs2_b'], BEST['gs1_d'], BEST['gs2_d'],
                                BEST['g_rev_b'], BEST['g_rev_d'], BEST['mom_b'], BEST['mom_d'],
                                BEST['eb'], BEST['xb'], BEST['sb'],
                                BEST['ed'], BEST['xd'], BEST['sd'],
                                sl=BEST['sl'], ts=BEST['ts'], ts_cd=BEST['ts_cd'])
                    s2.append({'V':V,'Q':Q,'G':G,'M':M,'cal':r['calmar'],'cagr':r['cagr'],'mdd':r['mdd']})
    s2.sort(key=lambda x: -x['cal'])
    print(f'  {len(s2)}조합. Top 5:')
    for r in s2[:5]:
        print(f'    V{r["V"]:>2} Q{r["Q"]:>2} G{r["G"]:>2} M{r["M"]:>2}: Cal {r["cal"]:.3f}  CAGR {r["cagr"]:.1f}%')
    pd.DataFrame(s2).to_csv(PROJECT/'backtest'/'verify_boost_wide.csv', index=False)

    print('\n  4b. Defense VQGM 확장')
    s3 = []
    for V in [20, 25, 30, 35, 40]:
        for Q in [10, 15, 20]:
            for G in [5, 10, 15, 20]:
                for M in [30, 40, 45, 50, 55]:
                    if V+Q+G+M != 100: continue
                    r = fast_bt(tsim_b, tsim_d, dates_all, reg,
                                BEST['V_b'], BEST['Q_b'], BEST['G_b'], BEST['M_b'],
                                V/100, Q/100, G/100, M/100,
                                BEST['gs1_b'], BEST['gs2_b'], BEST['gs1_d'], BEST['gs2_d'],
                                BEST['g_rev_b'], BEST['g_rev_d'], BEST['mom_b'], BEST['mom_d'],
                                BEST['eb'], BEST['xb'], BEST['sb'],
                                BEST['ed'], BEST['xd'], BEST['sd'],
                                sl=BEST['sl'], ts=BEST['ts'], ts_cd=BEST['ts_cd'])
                    s3.append({'V':V,'Q':Q,'G':G,'M':M,'cal':r['calmar'],'cagr':r['cagr'],'mdd':r['mdd']})
    s3.sort(key=lambda x: -x['cal'])
    print(f'  {len(s3)}조합. Top 5:')
    for r in s3[:5]:
        print(f'    V{r["V"]:>2} Q{r["Q"]:>2} G{r["G"]:>2} M{r["M"]:>2}: Cal {r["cal"]:.3f}  CAGR {r["cagr"]:.1f}%')
    pd.DataFrame(s3).to_csv(PROJECT/'backtest'/'verify_def_wide.csv', index=False)

    # 종합
    print(f'\n{"="*60}')
    print(f'종합 검증 결과')
    print(f'{"="*60}')
    print(f'  WF 4구간: min={wf_min:.3f}, mean={wf_mean:.3f}, CV={wf_cv:.3f} → {"PASS" if wf_cv<0.3 else "WARN"}')
    print(f'  양쪽 BT: 7.8y {r_78["calmar"]:.3f}, 5.25y {r_525["calmar"]:.3f}, 기하평균 {geo_mean:.3f}')
    print(f'  국면 인접: CV {reg_cv:.3f} → {"PASS" if reg_cv<0.2 else "WARN"}')
    print(f'  SL/TS 인접: CV {sl_cv:.3f} → {"PASS" if sl_cv<0.3 else "WARN"}')
    print(f'  Boost wide best: V{s2[0]["V"]} Q{s2[0]["Q"]} G{s2[0]["G"]} M{s2[0]["M"]} Cal {s2[0]["cal"]:.3f}')
    print(f'  Defense wide best: V{s3[0]["V"]} Q{s3[0]["Q"]} G{s3[0]["G"]} M{s3[0]["M"]} Cal {s3[0]["cal"]:.3f}')


if __name__ == '__main__':
    main()
