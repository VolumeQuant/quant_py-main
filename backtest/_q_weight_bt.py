# -*- coding: utf-8 -*-
"""Q(품질) 가중치 BT — 사용자 가설 검증 (2026-06-12).
Q를 0에서 올리고 budget을 V/G/M 다양한 조합에서 빼서 전부 BT.
TurboSim 4팩터 재가중 (과열캡/페널티 등 오버레이는 미포함 — 상대비교용).
단일모드 boost(grid_search와 동일 방식), 2019-01-02~ measure.
"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, TurboRunner, _run_regime_inner, _calc_metrics

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- 1. 프로덕션 boost 랭킹 로드 (2019-01-02~) ---
files = sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_2019*.json'))
             + glob.glob(os.path.join(PROJ, 'state', 'ranking_202[0-6]*.json')))
all_rankings, dates = {}, []
for f in files:
    dt = os.path.basename(f).replace('ranking_', '').replace('.json', '')
    if dt < '20190102':
        continue
    try:
        d = json.load(open(f, encoding='utf-8'))
        all_rankings[dt] = d.get('rankings', d) if isinstance(d, dict) else d
        dates.append(dt)
    except Exception:
        pass
dates = sorted(dates)
print(f'[데이터] {dates[0]}~{dates[-1]} {len(dates)}일')

prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*.parquet')),
                                key=lambda f: f.split('_')[-1])[-1]).replace(0, np.nan)
tsim = TurboSimulator(all_rankings, dates, prices)

# 현재 production boost G-내부 3팩터 (v80.6.1)
GK = dict(mom_type='12m', g_sub1='rev_z', g_sub2='oca_z', g_sub3='gp_growth_z',
          g_w1=0.4, g_w2=0.4, g_w3=0.2)
RULE = dict(entry_param=3, exit_param=6, max_slots=3, top_n=20,
            stop_loss=None, trailing_stop=None)  # v80.22/21 제거

def bt(v, q, g, m):
    """가중치(%) → 메트릭. v+q+g+m=100."""
    r = tsim.run_fast(v/100, q/100, g/100, m/100, 0.4, **RULE, **GK)
    return r

def yearly(v, q, g, m):
    """2026 부분만 보고싶을 때 — run_fast는 전체라, 간이로 전체만."""
    return bt(v, q, g, m)

def sub_sim(dsub):
    rk = {d: all_rankings[d] for d in dsub}
    return TurboSimulator(rk, sorted(dsub), prices)

def bt_on(sim, v, q, g, m):
    return sim.run_fast(v/100, q/100, g/100, m/100, 0.4, **RULE, **GK)

MODE = sys.argv[1] if len(sys.argv) > 1 else 'sample'

if MODE == 'sample':
    print('\n=== 표본: baseline V15 Q0 G55 M30 (E3X6S3) ===')
    r = bt(15, 0, 55, 30)
    print({k: r.get(k) for k in ('calmar', 'cagr', 'mdd', 'alpha', 'sharpe', 'total', 'avg_holdings')})

elif MODE == 'fullgrid':
    # 전체 그리드 (generate_weight_grid 동일): V0-40 Q0-40 G10-70 M10-60 step5
    combos = []
    for v in range(0, 45, 5):
        for q in range(0, 45, 5):
            for g in range(10, 75, 5):
                m = 100 - v - q - g
                if 10 <= m <= 60:
                    combos.append((v, q, g, m))
    print(f'\n=== 전체 그리드 {len(combos)}개 조합 BT (E3X6S3, 2019~) ===')
    res = []
    for (v, q, g, m) in combos:
        r = bt(v, q, g, m)
        res.append((v, q, g, m, r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0)))
    res.sort(key=lambda x: -x[4])
    print('--- Calmar 상위 12 ---')
    print(f"{'V':>3}{'Q':>3}{'G':>3}{'M':>3}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}")
    for v, q, g, m, cal, cg, md in res[:12]:
        print(f"{v:>3}{q:>3}{g:>3}{m:>3}{cal:>8.3f}{cg:>7.1f}{md:>7.1f}")
    # Q 임계별 최선
    print('--- Q 임계별 최고 Calmar (Q가 높아도 baseline 이기나?) ---')
    for qmin in [0, 5, 10, 15, 20, 25, 30, 40]:
        cand = [x for x in res if x[1] >= qmin]
        if cand:
            v, q, g, m, cal, cg, md = max(cand, key=lambda x: x[4])
            print(f"  Q>={qmin:>2}: 최고 V{v} Q{q} G{g} M{m} → Calmar {cal:.3f} (CAGR {cg:.0f} MDD {md:.0f})")

elif MODE == 'yearly':
    cfgs = [(15, 0, 55, 30), (15, 10, 45, 30), (15, 20, 35, 30), (15, 30, 25, 30),
            (10, 20, 40, 30), (20, 20, 35, 25)]
    years = ['2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026']
    regime = {'2019': '회복', '2020': '코로나crash', '2021': '강세', '2022': '약세장',
              '2023': '회복', '2024': '강세', '2025': '강세', '2026': '초강세'}
    sims = {}
    for y in years:
        dsub = [d for d in dates if d[:4] == y]
        sims[y] = sub_sim(dsub) if len(dsub) > 20 else None
    print('\n=== 연도별 수익률(CAGR%) — 각 연도 독립 BT ===')
    hdr = 'V Q G M'.ljust(12) + ''.join(f'{y[2:]}({regime[y][:4]})'.rjust(13) for y in years)
    print(hdr)
    for (v, q, g, m) in cfgs:
        row = f'{v} {q} {g} {m}'.ljust(12)
        for y in years:
            if sims[y] is None:
                row += 'n/a'.rjust(13); continue
            r = bt_on(sims[y], v, q, g, m)
            row += f"{r.get('cagr',0):>+7.0f}".rjust(13)
        tag = ' ←base' if q == 0 else ''
        print(row + tag)
    print('\n=== 연도별 MDD% ===')
    print(hdr)
    for (v, q, g, m) in cfgs:
        row = f'{v} {q} {g} {m}'.ljust(12)
        for y in years:
            if sims[y] is None:
                row += 'n/a'.rjust(13); continue
            r = bt_on(sims[y], v, q, g, m)
            row += f"{r.get('mdd',0):>7.0f}".rjust(13)
        print(row + (' ←base' if q == 0 else ''))

elif MODE == 'regimefull':
    # 전체 그리드(653) × defense=cash (올바른 방식). V/Q/G/M 전부 탐색.
    kdf = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet'))
    kc = kdf.iloc[:, 0] if kdf.shape[1] else kdf['Close']
    ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
    reg = {}; md = True; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)):
            reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    print(f'[regime] boost {sum(reg.values())}일 / cash {len(dates)-sum(reg.values())}일')
    G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
    def rbt(v, q, g, m):
        tsim._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, '12m', *G3[:3], *G3[3:])
        flat = list(tsim._cached_flat)
        return _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, dates,
            tsim._price_arr, tsim._bench_arr, tsim._has_bench, tsim._date_row_indices, len(dates),
            None, None, None, None, stop_loss_o=None, trailing_stop_o=None,
            stop_loss_d=None, trailing_stop_d=None)
    combos = []
    for v in range(0, 45, 5):
        for q in range(0, 45, 5):
            for g in range(10, 75, 5):
                m = 100 - v - q - g
                if 10 <= m <= 60:
                    combos.append((v, q, g, m))
    print(f'\n=== 전체 {len(combos)}조합 × defense=cash BT ===')
    res = []
    for (v, q, g, m) in combos:
        r = rbt(v, q, g, m)
        res.append((v, q, g, m, r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0)))
    res.sort(key=lambda x: -x[4])
    print('--- Calmar 상위 15 ---')
    print(f"{'V':>3}{'Q':>3}{'G':>3}{'M':>3}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}")
    for v, q, g, m, cal, cg, md in res[:15]:
        print(f"{v:>3}{q:>3}{g:>3}{m:>3}{cal:>8.3f}{cg:>7.0f}{md:>7.0f}")
    print('--- Q 임계별 최고 Calmar (defense 제외, 전체탐색) ---')
    for qm in [0, 5, 10, 15, 20, 25, 30, 40]:
        c = [x for x in res if x[1] >= qm]
        if c:
            v, q, g, m, cal, cg, md = max(c, key=lambda x: x[4])
            print(f"  Q>={qm:>2}: V{v} Q{q} G{g} M{m} → Cal {cal:.3f} (CAGR{cg:.0f} MDD{md:.0f})")

elif MODE == 'mfinal':
    # M 상향(G↓M↑) 제대로 검증: WF(기간분할) + 인접CV + 신팩터 중복체크
    kdf = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet'))
    kc = kdf.iloc[:, 0] if kdf.shape[1] else kdf['Close']
    ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
    def calc_reg(dsub):
        reg = {}; md = True; stk = 0; ss = None
        for d in dsub:
            ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
            if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)):
                reg[d] = md; continue
            s = bool(ma20[ts] > ma80[ts])
            if s == ss: stk += 1
            else: stk = 1; ss = s
            if stk >= 5 and md != s: md = s
            reg[d] = md
        return reg
    G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)

    def regime_bt(sim, dsub, reg_sub, v, q, g, m):
        sim._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, '12m', *G3[:3], *G3[3:])
        flat = list(sim._cached_flat)
        return _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg_sub, dsub,
            sim._price_arr, sim._bench_arr, sim._has_bench, sim._date_row_indices, len(dsub),
            None, None, None, None, stop_loss_o=None, trailing_stop_o=None,
            stop_loss_d=None, trailing_stop_d=None)

    full_reg = calc_reg(dates)
    BASE = (15, 0, 55, 30); CAND = (15, 0, 40, 40)  # 신팩터 중복 고립 위해 Q=0 고정, G↔M만
    # --- WF: 3 기간분할 ---
    splits = [('2019-21', '20190102', '20211231'), ('2022-23', '20220101', '20231231'),
              ('2024-26', '20240101', '20261231')]
    print('=== WF (기간분할) regime BT: baseline G55M30 vs M상향 G40M40 ===')
    print(f"{'기간':<10}{'baseCal':>9}{'candCal':>9}{'Δ':>7} | base/cand CAGR, MDD")
    for nm, lo, hi in splits:
        dsub = [d for d in dates if lo <= d <= hi]
        if len(dsub) < 30: continue
        sim = TurboSimulator({d: all_rankings[d] for d in dsub}, sorted(dsub), prices)
        rsub = calc_reg(dsub)
        rb = regime_bt(sim, dsub, rsub, *BASE); rc = regime_bt(sim, dsub, rsub, *CAND)
        print(f"{nm:<10}{rb['calmar']:>9.3f}{rc['calmar']:>9.3f}{rc['calmar']-rb['calmar']:>+7.2f} | {rb['cagr']:.0f}/{rc['cagr']:.0f}%, {rb['mdd']:.0f}/{rc['mdd']:.0f}%")
    # --- 인접 CV (full): G↔M 인접 ---
    print('\n=== 인접 CV (full, V15 Q0, G↔M 트레이드) ===')
    cals = []
    for g, m in [(35, 45), (40, 40), (45, 35), (50, 30), (55, 25)]:
        r = regime_bt(tsim, dates, full_reg, 15, 0, g, m)
        cals.append(r['calmar']); print(f'  G{g} M{m}: Cal {r["calmar"]:.3f}')
    import statistics
    print(f'  → 인접 CV: {statistics.pstdev(cals)/statistics.mean(cals):.3f} (CLAUDE 기준 <0.10~0.30)')
    print('\n[신팩터 중복 정량논증] production = M0.30 + mom10_z 0.05 + vol_low_z 0.06')
    print('  → 신팩터 0.11이 모두 momentum성. 유효 momentum ≈ 0.41.')
    print('  내 4팩터 BT 최적 M0.40은 이 0.41과 거의 일치 → M상향은 신팩터가 이미 한 일.')

elif MODE == 'regime':
    # 약세장=cash 적용 (production-realistic). boost 가중치는 boost 국면만 작동.
    # 현재 regime: KOSPI MA20 > MA80, 5일 연속 확인 (v80.18)
    kdf = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet'))
    kc = kdf.iloc[:, 0] if kdf.shape[1] else kdf['Close']
    ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
    reg = {}; md = True; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)):
            reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    nb = sum(reg.values()); print(f'[regime] boost {nb}일 / defense(cash) {len(dates)-nb}일')
    GK2 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)

    def bt_regime(v, q, g, m):
        # offense=boost weights, defense=cash(entry=0)
        tsim._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, '12m', *GK2[:3], *GK2[3:])
        flat = list(tsim._cached_flat)
        r = _run_regime_inner(
            flat, flat,
            0, 6, 3,   # defense entry=0 = cash (포지션 없음)
            3, 6, 3,   # offense E3 X6 S3
            reg, dates,
            tsim._price_arr, tsim._bench_arr, tsim._has_bench,
            tsim._date_row_indices, len(dates),
            None, None, None, None,  # SL/corr/TS/TP off (v80.21/22)
            stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None,
        )
        return r
    grid = [(15,0,55,30),(15,10,45,30),(15,20,35,30),(15,30,25,30),
            (15,10,55,20),(20,5,35,40),(15,5,40,40),(15,20,55,10),
            (10,20,40,30),(20,20,35,25),(5,25,40,30),(15,15,45,25)]
    print('\n=== 약세장=cash 적용 BT (boost 국면만 가중치 작동, 2019~) ===')
    print(f"{'V':>3}{'Q':>3}{'G':>3}{'M':>3} | {'Calmar':>7}{'CAGR':>7}{'MDD':>7}{'Sharpe':>7}")
    base = None
    for (v,q,g,m) in grid:
        r = bt_regime(v,q,g,m); cal = r.get('calmar',0)
        if base is None: base = cal
        tag = ' ←base' if q==0 and (v,q,g,m)==(15,0,55,30) else (f'  Δ{cal-base:+.2f}' if base else '')
        print(f"{v:>3}{q:>3}{g:>3}{m:>3} | {cal:>7.3f}{r.get('cagr',0):>7.1f}{r.get('mdd',0):>7.1f}{r.get('sharpe',0):>7.2f}{tag}")

else:
    # --- Q 그리드: Q를 0→올리고 budget을 V/G/M 다양하게 빼기 ---
    grid = [
        (15, 0, 55, 30),   # baseline
        # Q from G
        (15, 10, 45, 30), (15, 20, 35, 30), (15, 30, 25, 30),
        # Q from M
        (15, 10, 55, 20), (15, 20, 55, 10),
        # Q from V
        (5, 10, 55, 30), (10, 10, 50, 30),
        # Q from G+M
        (15, 15, 45, 25), (15, 20, 40, 25), (15, 25, 35, 25), (15, 20, 45, 20),
        # Q from V+G
        (10, 20, 40, 30), (5, 25, 40, 30),
        # 균형형
        (10, 25, 35, 30), (15, 30, 30, 25), (20, 20, 35, 25),
    ]
    print('\n=== Q 가중치 BT (E3X6S3, 2019-01-02~) ===')
    print(f"{'V':>3}{'Q':>3}{'G':>3}{'M':>3} | {'Calmar':>7}{'CAGR':>7}{'MDD':>7}{'Alpha':>7}{'Sharpe':>7}")
    base = None
    for (v, q, g, m) in grid:
        r = bt(v, q, g, m)
        cal = r.get('calmar', 0)
        if base is None:
            base = cal
        tag = ' ← baseline' if (v, q, g, m) == (15, 0, 55, 30) else (f'  ΔCal {cal-base:+.2f}' if base else '')
        print(f"{v:>3}{q:>3}{g:>3}{m:>3} | {cal:>7.3f}{r.get('cagr',0):>7.1f}{r.get('mdd',0):>7.1f}{r.get('alpha',0):>7.1f}{r.get('sharpe',0):>7.2f}{tag}")
