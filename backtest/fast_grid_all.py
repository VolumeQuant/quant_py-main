"""모든 stage 통합 그리드 — TSIM 1회 생성 + cache 재사용 (옛 v80_master_search 패턴)

목표: 5ms/run 달성 (TurboSimulator 캐시 활용)
"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, _calc_metrics, _run_regime_inner
from compare_optf_bt import load_rankings

PROJECT = Path(__file__).parent.parent
DISP_MAX = 1.5  # 이격도 안전망


def calc_regime_param(target_dates, kospi, ma_window, confirm_days):
    ma = kospi.rolling(ma_window).mean()
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = ma.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm_days and md != s: md = s
        reg[d] = md
    return reg


# 단일 BT (TSIM 캐시 활용 + 이격도)
def fast_bt(tsim_b, tsim_d, dates, regime,
            V_b, Q_b, G_b, M_b, V_d, Q_d, G_d, M_d,
            gs1_b='rev_z', gs2_b='oca_z', gs1_d='rev_z', gs2_d='oca_z',
            g_rev_b=0.6, g_rev_d=0.7, mom_b='12m', mom_d='6m-1m',
            entry_b=3, exit_b=6, slots_b=3,
            entry_d=3, exit_d=6, slots_d=5,
            sl=-0.10, ts=-0.15, ts_cd=2, disparity_max=DISP_MAX):
    tsim_b._ensure_cache(V_b, Q_b, G_b, M_b, g_rev_b, 20, mom_b, gs1_b, gs2_b)
    boost_flat = list(tsim_b._cached_flat)
    tsim_d._ensure_cache(V_d, Q_d, G_d, M_d, g_rev_d, 20, mom_d, gs1_d, gs2_d)
    defense_flat = list(tsim_d._cached_flat)
    price_arr = tsim_b._price_arr
    date_rows = tsim_b._date_row_indices
    n_dates = len(dates)
    portfolio = {}; peak_prices = {}; cooldown = {}
    daily_rets = [0.0] * n_dates; bench_rets = [0.0] * n_dates; holdings_count = [0] * n_dates
    prev_regime = None
    for i in range(2, n_dates):
        d = dates[i]; cr = regime.get(d, False)
        if prev_regime is not None and cr != prev_regime:
            portfolio.clear(); peak_prices.clear(); cooldown.clear()
        prev_regime = cr
        if cr:
            pipe = boost_flat[i] if i < len(boost_flat) else None
            entry_p, exit_p, max_slots = entry_b, exit_b, slots_b
        else:
            pipe = defense_flat[i] if i < len(defense_flat) else None
            entry_p, exit_p, max_slots = entry_d, exit_d, slots_d
        if pipe is None:
            holdings_count[i] = len(portfolio); continue
        wrank_arr, cand_cols, cand_prices, cand_wranks = pipe
        cur_row = date_rows[i]
        if cur_row < 0: continue
        expired = []
        for col in cooldown:
            cooldown[col] -= 1
            if cooldown[col] <= 0: expired.append(col)
        for col in expired: del cooldown[col]
        for col in portfolio:
            cur_p = price_arr[cur_row, col]
            if cur_p == cur_p and cur_p > 0:
                if col in peak_prices:
                    if cur_p > peak_prices[col]: peak_prices[col] = cur_p
                else: peak_prices[col] = cur_p
        to_remove = []
        for col, ep in portfolio.items():
            cur_p = price_arr[cur_row, col]
            if cur_p != cur_p or cur_p <= 0: continue
            reason = None
            if sl is not None and ep > 0 and (cur_p / ep - 1.0) <= sl: reason = 'sl'
            if reason is None and ts is not None:
                pk = peak_prices.get(col, ep)
                if pk > 0 and (cur_p / pk - 1.0) <= ts: reason = 'ts'
            if reason is None and wrank_arr[col] > exit_p: reason = 'rank'
            if reason: to_remove.append((col, reason))
        for col, reason in to_remove:
            del portfolio[col]
            if col in peak_prices: del peak_prices[col]
            if reason == 'ts' and ts_cd > 0: cooldown[col] = ts_cd
        slots_avail = max_slots - len(portfolio)
        if slots_avail > 0:
            for k in range(len(cand_cols)):
                if slots_avail <= 0: break
                if cand_wranks[k] <= entry_p:
                    c = cand_cols[k]
                    if c not in portfolio and c not in cooldown:
                        if disparity_max is not None:
                            ma20_start = max(0, cur_row - 19)
                            ma20_w = price_arr[ma20_start:cur_row+1, c]
                            ma20_w = ma20_w[ma20_w == ma20_w]
                            if len(ma20_w) >= 5:
                                ma20 = ma20_w.mean()
                                cur_p = price_arr[cur_row, c]
                                if ma20 > 0 and cur_p / ma20 > disparity_max: continue
                        portfolio[c] = cand_prices[k]
                        peak_prices[c] = cand_prices[k]
                        slots_avail -= 1
        n_hold = len(portfolio)
        holdings_count[i] = n_hold
        if i + 1 < n_dates and n_hold > 0:
            next_row = date_rows[i + 1]
            if next_row >= 0 and cur_row >= 0:
                total_ret = 0.0; count = 0
                for col in portfolio:
                    c_p = price_arr[next_row, col]
                    p_p = price_arr[cur_row, col]
                    if c_p == c_p and p_p == p_p and p_p > 0:
                        total_ret += c_p / p_p - 1.0; count += 1
                daily_rets[i] = total_ret / count if count > 0 else 0.0
    return _calc_metrics(daily_rets, bench_rets, holdings_count)


def main():
    print('=== Fast Grid (TSIM 1회 생성 + cache 재사용) ===')
    OHLCV = PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet'
    ohlcv = pd.read_parquet(OHLCV).replace(0, np.nan)
    kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
    kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()

    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
    dates = sorted(set(boost) & set(defense))
    print(f'  거래일: {len(dates)}')

    # TSIM 1회만 생성
    print(f'\n  TSIM 초기화...', flush=True)
    t0 = time.time()
    tsim_b = TurboSimulator({d: boost[d]['rankings'] for d in dates}, dates, ohlcv)
    tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in dates}, dates, ohlcv)
    print(f'  TSIM 완료: {time.time()-t0:.1f}초', flush=True)

    # 표본 시간 측정 (3 BT)
    print(f'\n  표본 BT 3회 (시간 측정)...', flush=True)
    t0 = time.time()
    reg_baseline = calc_regime_param(dates, kospi, 170, 8)
    for _ in range(3):
        r = fast_bt(tsim_b, tsim_d, dates, reg_baseline,
                    0.15, 0, 0.55, 0.30, 0.30, 0.15, 0.15, 0.40)
    elapsed = (time.time() - t0) / 3
    print(f'  표본 평균: {elapsed*1000:.0f}ms/조합', flush=True)
    print(f'  baseline Cal={r["calmar"]:.3f}, CAGR={r["cagr"]:.1f}%, MDD={r["mdd"]:.1f}%', flush=True)

    all_results = {'baseline': {**r, 'config': 'V15Q0G55M30 + V30Q15G15M40 + MA170/8d'}}

    # ═══ Stage 1: 국면 (MA × 확인일수) ═══
    print(f'\n=== Stage 1: 국면 (MA × 확인일수) ===', flush=True)
    s1 = []
    t0 = time.time()
    for ma_w in [120, 150, 170, 200, 250]:
        for cd in [3, 5, 7, 8, 10, 15]:
            reg = calc_regime_param(dates, kospi, ma_w, cd)
            r = fast_bt(tsim_b, tsim_d, dates, reg,
                        0.15, 0, 0.55, 0.30, 0.30, 0.15, 0.15, 0.40)
            s1.append({'MA': ma_w, 'days': cd, **r})
    print(f'  {len(s1)}조합 ({(time.time()-t0)/60:.1f}분)')
    s1.sort(key=lambda x: -x['calmar'])
    for r in s1[:5]:
        print(f'    MA{r["MA"]:>3} {r["days"]:>2}d: Cal {r["calmar"]:.3f}  CAGR {r["cagr"]:.1f}%  MDD {r["mdd"]:.1f}%')
    pd.DataFrame(s1).to_csv(PROJECT/'backtest'/'fast_stage1_regime.csv', index=False)
    best_regime = s1[0]
    reg_best = calc_regime_param(dates, kospi, best_regime['MA'], best_regime['days'])

    # ═══ Stage 2: Boost VQGM ═══
    print(f'\n=== Stage 2: Boost VQGM (best regime 사용) ===', flush=True)
    s2 = []
    t0 = time.time()
    for V in [0, 5, 10, 15, 20, 25]:
        for Q in [0, 5, 10]:
            for G in [40, 50, 55, 60, 70]:
                M = 100 - V - Q - G
                if M < 10 or M > 40: continue
                r = fast_bt(tsim_b, tsim_d, dates, reg_best,
                            V/100, Q/100, G/100, M/100, 0.30, 0.15, 0.15, 0.40)
                s2.append({'V':V,'Q':Q,'G':G,'M':M, **r})
    print(f'  {len(s2)}조합 ({(time.time()-t0)/60:.1f}분)')
    s2.sort(key=lambda x: -x['calmar'])
    for r in s2[:5]:
        print(f'    V{r["V"]:>2} Q{r["Q"]:>2} G{r["G"]:>2} M{r["M"]:>2}: Cal {r["calmar"]:.3f}')
    pd.DataFrame(s2).to_csv(PROJECT/'backtest'/'fast_stage2_boost.csv', index=False)
    best_b = s2[0]

    # ═══ Stage 3: Defense VQGM (Boost = best) ═══
    print(f'\n=== Stage 3: Defense VQGM ===', flush=True)
    s3 = []
    t0 = time.time()
    for V in [15, 20, 25, 30, 35, 40]:
        for Q in [5, 10, 15, 20]:
            for G in [10, 15, 20, 25]:
                M = 100 - V - Q - G
                if M < 25 or M > 55: continue
                r = fast_bt(tsim_b, tsim_d, dates, reg_best,
                            best_b['V']/100, best_b['Q']/100, best_b['G']/100, best_b['M']/100,
                            V/100, Q/100, G/100, M/100)
                s3.append({'V':V,'Q':Q,'G':G,'M':M, **r})
    print(f'  {len(s3)}조합 ({(time.time()-t0)/60:.1f}분)')
    s3.sort(key=lambda x: -x['calmar'])
    for r in s3[:5]:
        print(f'    V{r["V"]:>2} Q{r["Q"]:>2} G{r["G"]:>2} M{r["M"]:>2}: Cal {r["calmar"]:.3f}')
    pd.DataFrame(s3).to_csv(PROJECT/'backtest'/'fast_stage3_def.csv', index=False)
    best_d = s3[0]

    # ═══ Stage 4: G_SUB + MOM ═══
    print(f'\n=== Stage 4: G_SUB + MOM (boost) ===', flush=True)
    G_SUBS = [
        ('rev_z','oca_z'), ('rev_z','gp_growth_z'), ('rev_z','rev_accel_z'),
        ('oca_z','gp_growth_z'), ('rev_accel_z','oca_z'), ('gp_growth_z','op_margin_z'),
    ]
    MOMS = ['6m','6m-1m','12m','12m-1m']
    s4 = []
    t0 = time.time()
    for gs1, gs2 in G_SUBS:
        for mom in MOMS:
            for g_rev in [0.5, 0.6, 0.7, 0.8]:
                r = fast_bt(tsim_b, tsim_d, dates, reg_best,
                            best_b['V']/100, best_b['Q']/100, best_b['G']/100, best_b['M']/100,
                            best_d['V']/100, best_d['Q']/100, best_d['G']/100, best_d['M']/100,
                            gs1, gs2, 'rev_z', 'oca_z',
                            g_rev, 0.7, mom, '6m-1m')
                s4.append({'gs1':gs1,'gs2':gs2,'mom':mom,'g_rev':g_rev, **r})
    print(f'  {len(s4)}조합 ({(time.time()-t0)/60:.1f}분)')
    s4.sort(key=lambda x: -x['calmar'])
    for r in s4[:5]:
        print(f'    {r["gs1"][:8]}/{r["gs2"][:8]} {r["mom"]:>7} g_rev{r["g_rev"]:.1f}: Cal {r["calmar"]:.3f}')
    pd.DataFrame(s4).to_csv(PROJECT/'backtest'/'fast_stage4_gsub.csv', index=False)
    best_gs = s4[0]

    # ═══ Stage 5: 진입/이탈/슬롯 ═══
    print(f'\n=== Stage 5: 진입/이탈/슬롯 ===', flush=True)
    s5 = []
    t0 = time.time()
    for entry_b in [2, 3, 5]:
        for exit_b in [5, 6, 8]:
            for slots_b in [2, 3, 5]:
                for entry_d in [2, 3, 5]:
                    for exit_d in [5, 6, 8]:
                        for slots_d in [3, 5, 7]:
                            r = fast_bt(tsim_b, tsim_d, dates, reg_best,
                                        best_b['V']/100, best_b['Q']/100, best_b['G']/100, best_b['M']/100,
                                        best_d['V']/100, best_d['Q']/100, best_d['G']/100, best_d['M']/100,
                                        best_gs['gs1'], best_gs['gs2'], 'rev_z', 'oca_z',
                                        best_gs['g_rev'], 0.7, best_gs['mom'], '6m-1m',
                                        entry_b, exit_b, slots_b, entry_d, exit_d, slots_d)
                            s5.append({'eb':entry_b,'xb':exit_b,'sb':slots_b,
                                       'ed':entry_d,'xd':exit_d,'sd':slots_d, **r})
    print(f'  {len(s5)}조합 ({(time.time()-t0)/60:.1f}분)')
    s5.sort(key=lambda x: -x['calmar'])
    for r in s5[:5]:
        print(f'    eb{r["eb"]} xb{r["xb"]} sb{r["sb"]} | ed{r["ed"]} xd{r["xd"]} sd{r["sd"]}: Cal {r["calmar"]:.3f}')
    pd.DataFrame(s5).to_csv(PROJECT/'backtest'/'fast_stage5_entry.csv', index=False)
    best_e = s5[0]

    # ═══ Stage 6: SL/TS/쿨다운 ═══
    print(f'\n=== Stage 6: SL/TS/쿨다운 ===', flush=True)
    s6 = []
    t0 = time.time()
    for sl in [-0.05, -0.07, -0.10, -0.15, -0.20]:
        for ts_v in [-0.10, -0.15, -0.20, -0.25]:
            for cd in [0, 1, 2, 3, 5]:
                r = fast_bt(tsim_b, tsim_d, dates, reg_best,
                            best_b['V']/100, best_b['Q']/100, best_b['G']/100, best_b['M']/100,
                            best_d['V']/100, best_d['Q']/100, best_d['G']/100, best_d['M']/100,
                            best_gs['gs1'], best_gs['gs2'], 'rev_z', 'oca_z',
                            best_gs['g_rev'], 0.7, best_gs['mom'], '6m-1m',
                            best_e['eb'], best_e['xb'], best_e['sb'],
                            best_e['ed'], best_e['xd'], best_e['sd'],
                            sl=sl, ts=ts_v, ts_cd=cd)
                s6.append({'sl':sl,'ts':ts_v,'cd':cd, **r})
    print(f'  {len(s6)}조합 ({(time.time()-t0)/60:.1f}분)')
    s6.sort(key=lambda x: -x['calmar'])
    for r in s6[:5]:
        print(f'    SL{r["sl"]:+.2f} TS{r["ts"]:+.2f} cd{r["cd"]}: Cal {r["calmar"]:.3f}')
    pd.DataFrame(s6).to_csv(PROJECT/'backtest'/'fast_stage6_sl.csv', index=False)

    # 종합 best
    print(f'\n{"="*60}')
    print(f'🏆 종합 BEST 파라미터')
    print(f'{"="*60}')
    print(f'  국면     : MA{best_regime["MA"]} {best_regime["days"]}d (Cal {best_regime["calmar"]:.3f})')
    print(f'  Boost    : V{best_b["V"]} Q{best_b["Q"]} G{best_b["G"]} M{best_b["M"]} (Cal {best_b["calmar"]:.3f})')
    print(f'  Defense  : V{best_d["V"]} Q{best_d["Q"]} G{best_d["G"]} M{best_d["M"]} (Cal {best_d["calmar"]:.3f})')
    print(f'  G_SUB    : {best_gs["gs1"]}/{best_gs["gs2"]} mom {best_gs["mom"]} g_rev {best_gs["g_rev"]} (Cal {best_gs["calmar"]:.3f})')
    print(f'  진입     : eb{best_e["eb"]} xb{best_e["xb"]} sb{best_e["sb"]} | ed{best_e["ed"]} xd{best_e["xd"]} sd{best_e["sd"]} (Cal {best_e["calmar"]:.3f})')
    print(f'  SL/TS    : SL{s6[0]["sl"]:+.2f} TS{s6[0]["ts"]:+.2f} cd{s6[0]["cd"]} (Cal {s6[0]["calmar"]:.3f})')


if __name__ == '__main__':
    main()
