"""국면전환 종합 서��� — 2단계 (Quick Screen → Top N 정확 시뮬)"""
import sys, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
sys.path.insert(0, 'backtest')

import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator
from regime_search_v75 import apply_confirmation, calc_stats
from grid_search_v75 import load_bt_rankings, load_prices

CACHE_DIR = Path('data_cache')
t_start = time.time()

all_rankings, dates = load_bt_rankings(Path('backtest/bt_v75'))
prices = load_prices()
bench = pd.read_parquet(CACHE_DIR / 'bench_proxy.parquet')
tsim = TurboSimulator(all_rankings, dates, prices, bench)
ohlcv = prices

# ============================================================
# 1. 방어/공격 후보 확대
# ============================================================
phase2b = pd.read_csv('backtest_results/phase2b_rules.csv')

# 방어: MDD 낮은 순 (다양한 가중치) + 강제 포함
defense_pool = phase2b.nsmallest(200, 'mdd').drop_duplicates(
    subset=['v','q','g','m','g_rev','mom'], keep='first').head(15)
manual = phase2b[(phase2b.v==20)&(phase2b.q==15)&(phase2b.g==25)&(phase2b.m==40)].nlargest(1,'calmar')
defense_pool = pd.concat([defense_pool, manual]).drop_duplicates(subset=['v','q','g','m','g_rev','mom'])

# 공격: Calmar Top + CAGR Top (다양한 가중치)
off_cal = phase2b.nlargest(100, 'calmar').drop_duplicates(subset=['v','q','g','m','g_rev','mom'], keep='first').head(8)
off_cagr = phase2b.nlargest(100, 'cagr').drop_duplicates(subset=['v','q','g','m','g_rev','mom'], keep='first').head(8)
offense_pool = pd.concat([off_cal, off_cagr]).drop_duplicates(subset=['v','q','g','m','g_rev','mom'])

print(f'방��: {len(defense_pool)}개, 공격: {len(offense_pool)}개', flush=True)

# ============================================================
# 2. daily_rets 사전 생성 (27개 전략)
# ============================================================
print('\ndaily_rets 생성 중...', flush=True)
strat_rets = {}

for label, pool in [('D', defense_pool), ('O', offense_pool)]:
    for idx, (_, cfg) in enumerate(pool.iterrows()):
        sl = cfg.sl if pd.notna(cfg.sl) else None
        tr = cfg.trail if pd.notna(cfg.trail) else None
        ct = cfg.corr_th if 'corr_th' in cfg.index and pd.notna(cfg.corr_th) else None
        r = tsim.run_fast(cfg.v/100, cfg.q/100, cfg.g/100, cfg.m/100, cfg.g_rev,
                          entry_param=int(cfg.entry), exit_param=cfg['exit'],
                          max_slots=int(cfg.slots), stop_loss=sl,
                          corr_threshold=ct, trailing_stop=tr, mom_type=cfg.mom)
        key = f'{label}_{idx}'
        strat_rets[key] = r['_daily_rets']

print(f'  {len(strat_rets)}개 완료 ({time.time()-t_start:.1f}초)', flush=True)

# ============================================================
# 3. 전체 국면 규칙
# ============================================================
kospi = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet').iloc[:,0]
kosdaq = pd.read_parquet(CACHE_DIR / 'kosdaq_yf.parquet').iloc[:,0]
vix = pd.read_parquet(CACHE_DIR / 'vix_daily.parquet').iloc[:,0]
hy = pd.read_parquet(CACHE_DIR / 'hy_spread.parquet').iloc[:,0]

kp_ma60 = kospi.rolling(60).mean()
kq_ma60 = kosdaq.rolling(60).mean()
kp_ma120 = kospi.rolling(120).mean()
kq_ma120 = kosdaq.rolling(120).mean()

# B126 브레스
mcap_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
mcap_dict = {f.stem.split('_')[-1]: f for f in mcap_files}
breadth = {}
last_u = None
for d in dates:
    dt = pd.Timestamp(d)
    cands = [k for k in mcap_dict if k <= d]
    if cands:
        mc = pd.read_parquet(mcap_dict[max(cands)])
        u = set(mc[mc['시가총액']/1e8 >= 1000].index) & set(ohlcv.columns)
        last_u = u
    elif last_u:
        u = last_u
    else:
        continue
    vc = [t for t in u if t in ohlcv.columns]
    if not vc or dt not in ohlcv.index:
        continue
    sp = ohlcv.loc[:dt, vc]
    cnt = sp.notna().sum()
    h126 = cnt[cnt >= 126].index.tolist()
    if len(h126) < 10:
        continue
    s = sp[h126]
    if len(s) < 120:
        continue
    ma = s.iloc[-120:].mean()
    cur = s.iloc[-1]
    breadth[d] = (cur > ma).sum() / cur.notna().sum()

def prev_val(series, dt):
    prev = series[series.index < dt]
    if prev.empty:
        return None
    v = prev.iloc[-1]
    return v if pd.notna(v) else None

all_rules = {}

for thr in [0.30, 0.35, 0.40, 0.45, 0.50]:
    sig = {d: breadth.get(d, 0) >= thr for d in dates}
    for cd in [1, 3, 5, 7]:
        all_rules[f'B126_{int(thr*100)}_{cd}d'] = apply_confirmation(sig, dates, cd)

for name, idx_s, ma_s in [('KP60', kospi, kp_ma60), ('KQ60', kosdaq, kq_ma60),
                           ('KP120', kospi, kp_ma120), ('KQ120', kosdaq, kq_ma120)]:
    sig = {}
    for d in dates:
        dt = pd.Timestamp(d)
        k = prev_val(idx_s, dt)
        m = prev_val(ma_s, dt)
        sig[d] = bool(k is not None and m is not None and k > m)
    for cd in [1, 3, 5]:
        all_rules[f'{name}_{cd}d'] = apply_confirmation(sig, dates, cd)

for ma_n in ['60', '120']:
    for cd in [1, 3, 5]:
        kp_key, kq_key = f'KP{ma_n}_{cd}d', f'KQ{ma_n}_{cd}d'
        if kp_key in all_rules and kq_key in all_rules:
            all_rules[f'KK{ma_n}_{cd}d'] = {d: all_rules[kp_key].get(d,False) and all_rules[kq_key].get(d,False) for d in dates}

for thr in [20, 25, 30]:
    sig = {d: bool((v := prev_val(vix, pd.Timestamp(d))) is not None and v < thr) for d in dates}
    for cd in [1, 3]:
        all_rules[f'VIX{thr}_{cd}d'] = apply_confirmation(sig, dates, cd)

for thr in [4, 5, 6]:
    sig = {d: bool((h := prev_val(hy, pd.Timestamp(d))) is not None and h < thr) for d in dates}
    for cd in [1, 3]:
        all_rules[f'HY{thr}_{cd}d'] = apply_confirmation(sig, dates, cd)

for r1, r2 in [('KK60_3d','B126_40_1d'), ('KK60_3d','VIX25_1d'), ('KK120_3d','VIX25_1d'),
               ('B126_40_1d','VIX25_1d'), ('B126_40_1d','HY5_1d'), ('KK60_3d','HY5_1d'),
               ('KP120_3d','VIX25_1d'), ('KQ120_3d','B126_40_1d')]:
    if r1 in all_rules and r2 in all_rules:
        all_rules[f'{r1}+{r2}'] = {d: all_rules[r1].get(d,False) and all_rules[r2].get(d,False) for d in dates}

print(f'\n규칙: {len(all_rules)}개', flush=True)
total = len(defense_pool) * len(offense_pool) * len(all_rules)
print(f'총 조합: {total:,}건', flush=True)

# ============================================================
# 4. Stage 1: Quick Screen (daily_rets 조합)
# ============================================================
print(f'\nStage 1: Quick Screen ({total:,}건)...', flush=True)
t1 = time.time()

approx_results = []
d_indices = list(range(len(defense_pool)))
o_indices = list(range(len(offense_pool)))

for di in d_indices:
    d_rets = strat_rets[f'D_{di}']
    for oi in o_indices:
        o_rets = strat_rets[f'O_{oi}']
        for rule_name, regime in all_rules.items():
            combined = [o_rets[i] if regime.get(d, False) else d_rets[i] for i, d in enumerate(dates)]
            cagr, mdd, calmar, sharpe, sortino = calc_stats(combined)
            if calmar > 1.5:
                boost = sum(1 for v in regime.values() if v) / len(regime) * 100
                approx_results.append({
                    'di': di, 'oi': oi, 'rule': rule_name,
                    'calmar': calmar, 'cagr': cagr, 'mdd': mdd,
                    'sharpe': sharpe, 'sortino': sortino, 'boost': boost,
                })

approx_df = pd.DataFrame(approx_results).sort_values('calmar', ascending=False)
print(f'  {len(approx_df)}건 Cal>1.5 ({time.time()-t1:.1f}초)', flush=True)

# ============================================================
# 5. Stage 2: Top 200 정확 시뮬 (run_regime)
# ============================================================
N_VERIFY = min(200, len(approx_df))
print(f'\nStage 2: run_regime Top {N_VERIFY} (전환 시 청산+재진입)...', flush=True)
t2 = time.time()

d_list = list(defense_pool.iterrows())
o_list = list(offense_pool.iterrows())

exact_results = []
for rank, (_, row) in enumerate(approx_df.head(N_VERIFY).iterrows()):
    di, oi = int(row.di), int(row.oi)
    _, d_cfg = d_list[di]
    _, o_cfg = o_list[oi]

    d_p = {'v':d_cfg.v/100, 'q':d_cfg.q/100, 'g':d_cfg.g/100, 'm':d_cfg.m/100,
           'g_rev':d_cfg.g_rev, 'mom':d_cfg.mom,
           'entry':int(d_cfg.entry), 'exit':d_cfg['exit'], 'slots':int(d_cfg.slots)}
    o_p = {'v':o_cfg.v/100, 'q':o_cfg.q/100, 'g':o_cfg.g/100, 'm':o_cfg.m/100,
           'g_rev':o_cfg.g_rev, 'mom':o_cfg.mom,
           'entry':int(o_cfg.entry), 'exit':o_cfg['exit'], 'slots':int(o_cfg.slots)}

    d_sl = d_cfg.sl if pd.notna(d_cfg.sl) else None
    d_tr = d_cfg.trail if pd.notna(d_cfg.trail) else None

    regime = all_rules[row.rule]
    r = tsim.run_regime(d_p, o_p, regime, stop_loss=d_sl, trailing_stop=d_tr)

    d_label = f'V{int(d_cfg.v)}Q{int(d_cfg.q)}G{int(d_cfg.g)}M{int(d_cfg.m)} g{d_cfg.g_rev} {d_cfg.mom}'
    o_label = f'V{int(o_cfg.v)}Q{int(o_cfg.q)}G{int(o_cfg.g)}M{int(o_cfg.m)} g{o_cfg.g_rev} {o_cfg.mom}'

    exact_results.append({
        'defense': d_label, 'offense': o_label, 'rule': row.rule,
        'approx_cal': row.calmar, 'calmar': r['calmar'],
        'cagr': r['cagr'], 'mdd': r['mdd'],
        'sharpe': r['sharpe'], 'sortino': r['sortino'], 'boost': row.boost,
    })
    if (rank+1) % 50 == 0:
        print(f'  [{rank+1}/{N_VERIFY}] {time.time()-t2:.0f}초', flush=True)

exact_df = pd.DataFrame(exact_results).sort_values('calmar', ascending=False)
exact_df.to_csv('backtest_results/v75_regime_comprehensive.csv', index=False)
print(f'  완료 ({time.time()-t2:.0f}초)', flush=True)

# ============================================================
# 6. 결과 출력
# ============================================================
diff = (exact_df['calmar'] - exact_df['approx_cal']).abs()
print(f'\n근사치 vs 정확값: 평균|차이|={diff.mean():.3f}, 최대={diff.max():.3f}', flush=True)

print(f'\n{"="*120}', flush=True)
print(f'규칙 유형별 Top 1', flush=True)
print(f'{"="*120}', flush=True)
seen = set()
for _, r in exact_df.iterrows():
    rt = r['rule'].split('_')[0]
    if '+' in r['rule']:
        rt = r['rule']
    if rt in seen:
        continue
    seen.add(rt)
    print(f'  {r["defense"]:>30} {r["offense"]:>30} {r["rule"]:>25}'
          f' Cal={r.calmar:.2f}(~{r.approx_cal:.2f}) CAGR={r.cagr:.1f}% MDD={r.mdd:.1f}% Bst={r.boost:.0f}%', flush=True)

print(f'\n{"="*120}', flush=True)
print(f'전체 Top 25 (정확값)', flush=True)
print(f'{"="*120}', flush=True)
for i, (_, r) in enumerate(exact_df.head(25).iterrows(), 1):
    print(f'{i:2d}. {r["defense"]:>30} {r["offense"]:>30} {r["rule"]:>25}'
          f' Cal={r.calmar:.2f} CAGR={r.cagr:.1f}% MDD={r.mdd:.1f}%'
          f' Sh={r.sharpe:.2f} So={r.sortino:.2f}', flush=True)

print(f'\n총 소요: {(time.time()-t_start)/60:.1f}분', flush=True)
