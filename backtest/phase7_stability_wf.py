"""Phase 7: 인접 안정성 + Walk-Forward 검증
Phase 6c Top 3 대상 — 파라미터 섭동 견고성 + 기간별 독립 성과

인접 안정성 (Adjacent Stability):
  V/Q/G/M ±5%, E/X/S ±1, 국면 confirm ±2일 → 주변 20~30개 조합 성과 분포
  Cal 표준편차 / 평균 < 0.3 이면 안정

Walk-Forward (4 구간):
  2018-07~2019-12 (1.5y) / 2020-01~2021-12 (2y) / 2022-01~2023-12 (2y) / 2024-01~2026-04 (2.3y)
  각 구간 Cal, CAGR, MDD 독립 평가 — 특정 구간 폭망 여부 확인

병렬: 4워커 × ProcessPoolExecutor (grid_search_final.py 패턴)
"""
import sys, os, time, json, glob
from pathlib import Path
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, 'C:/dev/backtest')
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np


def load_rankings(dirs):
    data = {}
    for d in dirs:
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            if len(fp.stem.replace('ranking_','')) != 8: continue
            k = fp.stem.replace('ranking_','')
            if k not in data:
                data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


STATE = Path('C:/dev/state')
STATE_D = STATE / 'defense'
BT_EXT = Path('C:/dev/backtest/bt_extended')
BT_EXT_D = Path('C:/dev/backtest/bt_extended_defense')

# Walk-Forward 구간
WF_PERIODS = [
    ('2018H2-2019', '20180702', '20191231'),
    ('2020-2021',   '20200102', '20211230'),
    ('2022-2023',   '20220103', '20231228'),
    ('2024-2026',   '20240102', '20260414'),
]

# === 병렬 워커 ===
_W_DATA = None  # dict: {'dates':..., 'sub_dates':..., 'boost_rk':..., 'ohlcv':..., 'kospi':..., 'ma200':...}
_W_TSIMS = None  # dict: period_name -> TurboSimulator


def _init_worker():
    """워커당 1회 데이터 로드 + WF 구간별 TSIM 생성"""
    global _W_DATA, _W_TSIMS
    from turbo_simulator import TurboSimulator

    boost_rd = load_rankings([BT_EXT, STATE])
    defense_rd = load_rankings([BT_EXT_D, STATE_D])
    dates = sorted(set(boost_rd) & set(defense_rd))
    boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
    ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

    kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
    kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
    ma200 = kospi.rolling(200).mean()

    _W_DATA = {
        'dates': dates, 'boost_rk': boost_rk, 'ohlcv': ohlcv,
        'kospi': kospi, 'ma200': ma200,
    }

    # TSIM: full(7.8y), 5.25y, + 4 WF 구간
    _W_TSIMS = {}
    _W_TSIMS['full'] = TurboSimulator(boost_rk, dates, ohlcv)
    sub = [d for d in dates if '20210104' <= d <= '20260414']
    _W_TSIMS['5.25y'] = TurboSimulator({d: boost_rk[d] for d in sub}, sub, ohlcv)
    for name, s, e in WF_PERIODS:
        wd = [d for d in dates if s <= d <= e]
        if len(wd) < 50: continue
        _W_TSIMS[name] = TurboSimulator({d: boost_rk[d] for d in wd}, wd, ohlcv)


def _calc_regime(target_dates, kospi, ma200, confirm):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma200.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg


def _eval_one(args):
    """워커: (cfg_id, variant_label, confirm, offense, defense, gso, gsd, period_name) → 결과"""
    global _W_DATA, _W_TSIMS
    cfg_id, variant, confirm, ofs, dfs, gso, gsd, period = args
    tsim = _W_TSIMS.get(period)
    if tsim is None: return None
    # target dates for regime calc = tsim의 dates
    target_dates = sorted(tsim.rankings.keys()) if hasattr(tsim, 'rankings') else _W_DATA['dates']
    # tsim 내부 dates 추출
    try:
        target_dates = tsim.dates
    except AttributeError:
        pass
    reg = _calc_regime(target_dates, _W_DATA['kospi'], _W_DATA['ma200'], confirm)
    try:
        r = tsim.run_regime(
            defense_params=dfs, offense_params=ofs, regime_dict=reg, trailing_stop=-0.15,
            g_sub1_o=gso[0],g_sub2_o=gso[1],g_sub3_o=gso[2],g_w1_o=gso[3],g_w2_o=gso[4],g_w3_o=gso[5],
            g_sub1_d=gsd[0],g_sub2_d=gsd[1],g_sub3_d=gsd[2],g_w1_d=gsd[3],g_w2_d=gsd[4],g_w3_d=gsd[5],
        )
        return {
            'cfg': cfg_id, 'variant': variant, 'period': period, 'confirm': confirm,
            'oV':ofs['v']*100,'oQ':ofs['q']*100,'oG':ofs['g']*100,'oM':ofs['m']*100,
            'oE':ofs['entry'],'oX':ofs['exit'],'oS':ofs['slots'],'o_mom':ofs['mom'],
            'dV':dfs['v']*100,'dQ':dfs['q']*100,'dG':dfs['g']*100,'dM':dfs['m']*100,
            'dE':dfs['entry'],'dX':dfs['exit'],'dS':dfs['slots'],'d_mom':dfs['mom'],
            'cal':r['calmar'],'cagr':r['cagr'],'mdd':r['mdd'],'total':r.get('total',0),
        }
    except Exception as ee:
        return {'cfg': cfg_id, 'variant': variant, 'period': period, 'err': str(ee)[:60]}


def gs_o(label):
    if label == '3f_rev_oca_gp': return ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
    if label == '3f_rev_oca_opm': return ('rev_z','oca_z','op_margin_z',0.5,0.3,0.2)
    return ('rev_z','oca_z',None,None,None,None)


def gs_d(label):
    if label == '2f_rev_oca_0.7': return ('rev_z','oca_z',None,None,None,None)
    if label == '2f_rev_accel_opm_0.5': return ('rev_accel_z','op_margin_z',None,None,None,None)
    return ('rev_z','oca_z',None,None,None,None)


def build_variants(cfg_id, row):
    """Top cfg 주변 인접 조합 생성 (V/Q/G/M ±5%, E/X/S ±1, confirm ±2)"""
    oV,oQ,oG,oM = int(row['oV']),int(row['oQ']),int(row['oG']),int(row['oM'])
    dV,dQ,dG,dM = int(row['dV']),int(row['dQ']),int(row['dG']),int(row['dM'])
    oE,oX,oS = int(row['oE']),int(row['oX']),int(row['oS'])
    dE,dX,dS = int(row['dE']),int(row['dX']),int(row['dS'])
    o_mom, d_mom = row['o_mom'], row['d_mom']
    o_gs, d_gs = row['o_gs'], row['d_gs']
    regime = row.get('regime', 'MA200_7d')
    confirm_base = int(str(regime).replace('MA200_','').replace('d','')) if 'MA200' in str(regime) else 7

    g_rev_o = 0.5 if '3f' in o_gs else 0.7
    g_rev_d = 0.7 if 'rev_oca' in d_gs else 0.5
    gso = gs_o(o_gs)
    gsd = gs_d(d_gs)

    base_ofs = {'v':oV/100,'q':oQ/100,'g':oG/100,'m':oM/100,'g_rev':g_rev_o,
                'entry':oE,'exit':oX,'slots':oS,'mom':o_mom}
    base_dfs = {'v':dV/100,'q':dQ/100,'g':dG/100,'m':dM/100,'g_rev':g_rev_d,
                'entry':dE,'exit':dX,'slots':dS,'mom':d_mom}

    variants = []
    # base
    variants.append(('base', confirm_base, base_ofs, base_dfs))

    # 공격 V±5 / G∓5 (총합 유지)
    for dv in [-5, 5]:
        nV, nG = oV+dv, oG-dv
        if nV < 0 or nG < 0: continue
        ofs = {**base_ofs, 'v':nV/100, 'g':nG/100}
        variants.append((f'oV{dv:+d}', confirm_base, ofs, base_dfs))

    # 공격 G±5 / M∓5
    for dg in [-5, 5]:
        nG, nM = oG+dg, oM-dg
        if nG < 0 or nM < 0: continue
        ofs = {**base_ofs, 'g':nG/100, 'm':nM/100}
        variants.append((f'oG{dg:+d}', confirm_base, ofs, base_dfs))

    # 방어 V±5 / M∓5
    for dv in [-5, 5]:
        nV, nM = dV+dv, dM-dv
        if nV < 0 or nM < 0: continue
        dfs = {**base_dfs, 'v':nV/100, 'm':nM/100}
        variants.append((f'dV{dv:+d}', confirm_base, base_ofs, dfs))

    # 방어 G±5 / M∓5
    for dg in [-5, 5]:
        nG, nM = dG+dg, dM-dg
        if nG < 0 or nM < 0: continue
        dfs = {**base_dfs, 'g':nG/100, 'm':nM/100}
        variants.append((f'dG{dg:+d}', confirm_base, base_ofs, dfs))

    # 공격 E±1
    for de in [-1, 1]:
        nE = max(1, oE+de)
        ofs = {**base_ofs, 'entry':nE}
        variants.append((f'oE{de:+d}', confirm_base, ofs, base_dfs))

    # 방어 E±1
    for de in [-1, 1]:
        nE = max(1, dE+de)
        dfs = {**base_dfs, 'entry':nE}
        variants.append((f'dE{de:+d}', confirm_base, base_ofs, dfs))

    # confirm ±2
    for dc in [-2, 2]:
        nc = max(3, confirm_base+dc)
        variants.append((f'conf{dc:+d}', nc, base_ofs, base_dfs))

    return [(cfg_id, v, c, ofs, dfs, gso, gsd) for v, c, ofs, dfs in variants]


def main():
    # Phase 6c Top 3 로드 (unique dedup)
    df6c = pd.read_csv('C:/dev/backtest/phase6c_combo.csv')
    dedup_cols = ['oV','oQ','oG','oM','o_mom','o_gs','oE','oX','oS',
                  'dV','dQ','dG','dM','d_mom','d_gs','dE','dX','dS']
    df6c_u = df6c.drop_duplicates(subset=dedup_cols).reset_index(drop=True)
    top3 = df6c_u.head(3).to_dict('records')
    print(f'Top 3 대상:', flush=True)
    for i, r in enumerate(top3):
        print(f"  [{i}] o:V{r['oV']}G{r['oG']} {r['o_mom']} {r['o_gs']} E{r['oE']}X{r['oX']}S{r['oS']} "
              f"d:V{r['dV']}G{r['dG']} {r['d_mom']} {r['d_gs']} E{r['dE']}X{r['dX']}S{r['dS']} "
              f"score={r['score']:.2f}", flush=True)

    # 작업 생성: 각 cfg × (base + adjacent variants) × (full, 5.25y, WF4)
    all_tasks = []
    for cfg_id, row in enumerate(top3):
        variants = build_variants(cfg_id, row)
        for vt in variants:
            cfg, variant, confirm, ofs, dfs, gso, gsd = vt
            for period in ['full', '5.25y'] + [p[0] for p in WF_PERIODS]:
                all_tasks.append((cfg, variant, confirm, ofs, dfs, gso, gsd, period))
    print(f'총 작업: {len(all_tasks)} = {len(top3)}cfg × ~{len(variants)}variant × {2+len(WF_PERIODS)}period', flush=True)

    t0 = time.time()
    N_WORKERS = 4
    results = []
    done = 0
    with ProcessPoolExecutor(max_workers=N_WORKERS, initializer=_init_worker) as ex:
        futures = {ex.submit(_eval_one, t): t for t in all_tasks}
        for fut in as_completed(futures):
            r = fut.result()
            if r is not None:
                results.append(r)
            done += 1
            if done % 50 == 0 or done == len(all_tasks):
                el = time.time() - t0
                rate = done / el if el > 0 else 1
                rem = (len(all_tasks) - done) / rate if rate > 0 else 0
                print(f'  [{done}/{len(all_tasks)}] {el:.0f}s elapsed, ETA {rem:.0f}s', flush=True)

    df = pd.DataFrame(results)
    df.to_csv('C:/dev/backtest/phase7_stability_wf_raw.csv', index=False, encoding='utf-8-sig')

    # === 집계 ===
    # 인접 안정성: full + 5.25y 성과만으로 Cal 분포
    print(f'\n=== 인접 안정성 (full + 5.25y 평균 Cal) ===')
    stab = df[df['period'].isin(['full', '5.25y']) & df['cal'].notna()].copy()
    stab['cal_avg'] = stab.groupby(['cfg', 'variant'])['cal'].transform('mean')
    agg = (stab.groupby('cfg')['cal_avg']
             .agg(['mean', 'std', 'min', 'max', 'count']).reset_index())
    agg['cv'] = agg['std'] / agg['mean']
    print(agg.to_string(index=False))

    # Walk-Forward
    print(f'\n=== Walk-Forward (base variant만) ===')
    wf = df[(df['variant'] == 'base') & df['period'].isin([p[0] for p in WF_PERIODS])].copy()
    if not wf.empty:
        wf_piv = wf.pivot_table(index='cfg', columns='period', values='cal', aggfunc='first')
        print(wf_piv.to_string())
        # 최소 Cal (worst period)
        wf_piv['min_cal'] = wf_piv.min(axis=1)
        wf_piv['mean_cal'] = wf_piv.mean(axis=1)
        print('\nWF 요약:')
        print(wf_piv[['min_cal', 'mean_cal']].to_string())

    # 종합 저장
    if not agg.empty:
        agg.to_csv('C:/dev/backtest/phase7_stability.csv', index=False, encoding='utf-8-sig')
    if not wf.empty:
        wf_piv.to_csv('C:/dev/backtest/phase7_walkforward.csv', encoding='utf-8-sig')

    print(f'\n총 소요: {(time.time()-t0)/60:.1f}분')


if __name__ == '__main__':
    main()
