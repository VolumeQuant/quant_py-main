"""v77 전체 최적화 파이프라인 — G서브 → Phase 2a → Phase 2b → 국면서치 → 안정성/WF

각 단계 완료 시 텔레그램 개인봇으로 결과 전송.
실행 원칙: 표본 테스트 → 벤치마크 → 전체 실행 (G서브 이미 병렬 진행 중이므로 합산부터)
"""
import sys, json, numpy as np, pandas as pd, time, os, glob
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from itertools import combinations
from turbo_simulator import TurboSimulator

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
RESULT_DIR.mkdir(exist_ok=True)

def send_tg(msg):
    try:
        import requests
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                      data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=30)
    except Exception as e:
        print(f'텔레그램 전송 실패: {e}')

t_pipeline = time.time()

# ============================================================
# Step 0: 데이터 로드 (공통)
# ============================================================
print('Step 0: 데이터 로드', flush=True)
ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

# 국면 분리 (KP_MA200_5d — 예비)
mode = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d)
    kv = kospi.get(ts, None); mv = km200.get(ts, None)
    s = (kv > mv) if kv is not None and mv is not None else mode
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and mode != s: mode = s
    rd[d] = mode

boost_dates = [d for d in dates if rd[d]]
defense_dates = [d for d in dates if not rd[d]]
print(f'  {len(dates)}일 (공격 {len(boost_dates)}, 방어 {len(defense_dates)})', flush=True)

# ============================================================
# Step 1: G서브 결과 합산 (이미 병렬 워커로 생성됨)
# ============================================================
print('\nStep 1: G서브 결과 합산', flush=True)

def merge_gsub_results(mode_name):
    pattern = str(RESULT_DIR / f'v77_gsub_{mode_name}_*.csv')
    files = sorted(glob.glob(pattern))
    if not files:
        print(f'  {mode_name}: 결과 파일 없음!')
        return None, None
    df = pd.concat([pd.read_csv(f) for f in files])
    print(f'  {mode_name}: {len(files)}파일, {len(df)}행', flush=True)

    summary = df.groupby(['gs1', 'gs2', 'gr']).agg(
        avg_cal=('cal', 'mean'), max_cal=('cal', 'max'),
        avg_cagr=('cagr', 'mean'),
    ).reset_index().sort_values('avg_cal', ascending=False)

    pair_best = df.groupby(['gs1', 'gs2']).agg(
        best_cal=('cal', 'max'), avg_cal=('cal', 'mean'),
    ).reset_index().sort_values('avg_cal', ascending=False)

    summary.to_csv(RESULT_DIR / f'v77_gsub_{mode_name}_summary.csv', index=False)
    return summary, pair_best

atk_summary, atk_pairs = merge_gsub_results('attack')
def_summary, def_pairs = merge_gsub_results('defense')

if atk_summary is None or def_summary is None:
    send_tg('[v77] G서브 결과 파일 부족 — 워커 완료 대기 필요')
    print('G서브 결과 부족. 워커 완료 후 재실행.', flush=True)
    sys.exit(1)

# 상위 5쌍
atk_top5 = atk_summary.drop_duplicates(subset=['gs1', 'gs2'], keep='first').head(5)
def_top5 = def_summary.drop_duplicates(subset=['gs1', 'gs2'], keep='first').head(5)

msg = '[v77 Step 1: G서브 결과]\n\n공격 Top5 쌍:\n'
for _, r in atk_top5.iterrows():
    msg += f'  {r["gs1"]}+{r["gs2"]} gr={r["gr"]} cal={r["avg_cal"]:.2f}\n'
msg += '\n방어 Top5 쌍:\n'
for _, r in def_top5.iterrows():
    msg += f'  {r["gs1"]}+{r["gs2"]} gr={r["gr"]} cal={r["avg_cal"]:.2f}\n'
send_tg(msg)
print(msg, flush=True)


# ============================================================
# Step 2: Phase 2a — 가중치 그리드서치 (상위 5쌍 각각)
# ============================================================
print('\nStep 2: Phase 2a 가중치 그리드서치', flush=True)

def weight_grid():
    combos = []
    for v in range(0, 45, 5):
        for q in range(0, 45, 5):
            for g in range(10, 75, 5):
                m = 100 - v - q - g
                if 10 <= m <= 60:
                    combos.append((v, q, g, m))
    return combos

weights = weight_grid()
g_revs = [round(x * 0.1, 1) for x in range(11)]
mom_types = ['6m', '6m-1m', '12m', '12m-1m']
wg_combos = [(v,q,g,m,gr) for v,q,g,m in weights for gr in g_revs]

def phase2a_mode(mode_dates, mode_name, entry, exit_r, slots, top5_gsub):
    rk_mode = {d: rk[d] for d in mode_dates}
    tsim = TurboSimulator(rk_mode, mode_dates, ohlcv, bench=bench)

    all_results = []
    for idx, (_, gsrow) in enumerate(top5_gsub.iterrows()):
        gs1, gs2 = gsrow['gs1'], gsrow['gs2']
        print(f'  [{mode_name} {idx+1}/5] {gs1}+{gs2}', flush=True)
        t1 = time.time()
        results = []
        done = 0
        for v, q, g, m, gr in wg_combos:
            for mom in mom_types:
                r = tsim.run_fast(v/100, q/100, g/100, m/100, gr,
                                 entry_param=entry, exit_param=exit_r, max_slots=slots,
                                 mom_type=mom, stop_loss=-0.10, trailing_stop=-0.15,
                                 g_sub1=gs1, g_sub2=gs2)
                results.append({
                    'v': v, 'q': q, 'g': g, 'm': m, 'gr': gr,
                    'gs1': gs1, 'gs2': gs2, 'mom': mom,
                    'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                    'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                })
            done += 1
            if done % 500 == 0:
                elapsed = time.time() - t1
                rate = done / elapsed if elapsed > 0 else 1
                remain = (len(wg_combos) - done) / rate / 60
                print(f'    {done}/{len(wg_combos)} ({elapsed/60:.0f}분, ~{remain:.0f}분)', flush=True)
        all_results.extend(results)
        print(f'    완료 ({time.time()-t1:.0f}s)', flush=True)

    return pd.DataFrame(all_results).sort_values('cal', ascending=False)

t2a = time.time()
atk_df = phase2a_mode(boost_dates, '공격', 5, 8, 3, atk_top5)
atk_df.to_csv(RESULT_DIR / 'v77_phase2a_attack.csv', index=False)

def_df = phase2a_mode(defense_dates, '방어', 5, 8, 5, def_top5)
def_df.to_csv(RESULT_DIR / 'v77_phase2a_defense.csv', index=False)

msg = f'[v77 Step 2: Phase 2a 완료]\n소요: {(time.time()-t2a)/60:.0f}분\n\n'
msg += f'공격 Top5:\n'
for _, r in atk_df.head(5).iterrows():
    msg += f'  V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]} gr={r["gr"]} {r["gs1"]}+{r["gs2"]} {r["mom"]} Cal={r["cal"]:.2f}\n'
msg += f'\n방어 Top5:\n'
for _, r in def_df.head(5).iterrows():
    msg += f'  V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]} gr={r["gr"]} {r["gs1"]}+{r["gs2"]} {r["mom"]} Cal={r["cal"]:.2f}\n'
send_tg(msg)
print(msg, flush=True)


# ============================================================
# Step 3: Phase 2b — E/X/S 서치 (공격Top5 × 방어Top5)
# ============================================================
print('\nStep 3: Phase 2b E/X/S 서치', flush=True)
t2b = time.time()

entry_list = [3, 5, 7]
exit_list = [5, 7, 8, 10, 12, 15]
slots_list = [3, 5, 7]
stop_list = [-0.08, -0.10, -0.12, -0.15]
trailing_list = [-0.10, -0.12, -0.15, -0.20]

tsim_full = TurboSimulator(rk, dates, ohlcv, bench=bench)

exs_results = []
atk_top5_rows = atk_df.head(5)
def_top5_rows = def_df.head(5)
total_exs = 5 * 5 * len(entry_list) * len(exit_list) * len(slots_list) * len(stop_list) * len(trailing_list)
# 너무 많으면 축소
if total_exs > 50000:
    stop_list = [-0.10]
    trailing_list = [-0.15]
    total_exs = 5 * 5 * len(entry_list) * len(exit_list) * len(slots_list)
    print(f'  EXS 조합 축소 (손절/트레일링 고정): {total_exs}개', flush=True)
else:
    print(f'  EXS 조합: {total_exs}개', flush=True)

count = 0
for _, a in atk_top5_rows.iterrows():
    op = {'v': a['v']/100, 'q': a['q']/100, 'g': a['g']/100, 'm': a['m']/100,
          'g_rev': a['gr'], 'mom': a['mom']}
    for _, d in def_top5_rows.iterrows():
        dp = {'v': d['v']/100, 'q': d['q']/100, 'g': d['g']/100, 'm': d['m']/100,
              'g_rev': d['gr'], 'mom': d['mom']}
        for entry in entry_list:
            for exit_r in exit_list:
                if exit_r <= entry:
                    continue
                for slots in slots_list:
                    for sl in stop_list:
                        for ts in trailing_list:
                            op_full = {**op, 'entry': entry, 'exit': exit_r, 'slots': slots}
                            dp_full = {**dp, 'entry': entry, 'exit': exit_r, 'slots': max(slots, 5)}
                            r = tsim_full.run_regime(dp_full, op_full, rd,
                                stop_loss=sl, trailing_stop=ts,
                                g_sub1_d=d['gs1'], g_sub2_d=d['gs2'],
                                g_sub1_o=a['gs1'], g_sub2_o=a['gs2'])
                            exs_results.append({
                                'atk': f"V{int(a['v'])}Q{int(a['q'])}G{int(a['g'])}M{int(a['m'])}",
                                'def': f"V{int(d['v'])}Q{int(d['q'])}G{int(d['g'])}M{int(d['m'])}",
                                'atk_gs': f"{a['gs1']}+{a['gs2']}", 'def_gs': f"{d['gs1']}+{d['gs2']}",
                                'atk_gr': a['gr'], 'def_gr': d['gr'],
                                'atk_mom': a['mom'], 'def_mom': d['mom'],
                                'entry': entry, 'exit': exit_r, 'slots': slots,
                                'sl': sl, 'ts': ts,
                                'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                                'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                            })
                            count += 1
        if count % 500 == 0:
            print(f'  {count}/{total_exs}', flush=True)

exs_df = pd.DataFrame(exs_results).sort_values('cal', ascending=False)
exs_df.to_csv(RESULT_DIR / 'v77_phase2b_exs.csv', index=False)

msg = f'[v77 Step 3: Phase 2b EXS 완료]\n소요: {(time.time()-t2b)/60:.0f}분\n{len(exs_results)}조합\n\n'
msg += 'Top 5:\n'
for _, r in exs_df.head(5).iterrows():
    msg += f'  E{r["entry"]}X{r["exit"]}S{r["slots"]} SL={r["sl"]} TS={r["ts"]} Cal={r["cal"]:.2f} CAGR={r["cagr"]:.1f}%\n'
send_tg(msg)
print(msg, flush=True)


# ============================================================
# Step 4: 국면 서치 (다양한 규칙 × 공격Top5 × 방어Top5)
# ============================================================
print('\nStep 4: 국면 서치', flush=True)
t_regime = time.time()

# 국면 규칙 빌드
mc = pd.read_parquet(sorted(DATA_DIR.glob('market_cap_ALL_*.parquet'))[-1])
big = set(mc[mc['시가총액'] >= 1e11].index)
cols = [c for c in ohlcv.columns if c in big]
br = (ohlcv[cols] > ohlcv[cols].rolling(120).mean()).sum(axis=1) / ohlcv[cols].notna().sum(axis=1)

kospi_ma = {n: kospi.rolling(n).mean() for n in [60, 120, 150, 200, 250]}

kosdaq_f = DATA_DIR / 'kosdaq_yf.parquet'
kosdaq = pd.read_parquet(kosdaq_f).iloc[:,0].dropna() if kosdaq_f.exists() else None
kosdaq_ma = {}
if kosdaq is not None:
    for n in [60, 120]:
        kosdaq_ma[n] = kosdaq.rolling(n).mean()

def build_regime(dates, rule_fn, confirm):
    md = False; stk = 0; prev_s = False; result = {}
    for d in dates:
        ts = pd.Timestamp(d)
        try:
            s = rule_fn(ts)
        except:
            s = md
        if s == prev_s: stk += 1
        else: stk = 1; prev_s = s
        if stk >= confirm and md != s: md = s
        result[d] = md
    return result

regime_rules = {}
for thresh in [0.30, 0.35, 0.40, 0.45, 0.50]:
    for confirm in [2, 3, 4, 5]:
        name = f'B126_{int(thresh*100)}_{confirm}d'
        regime_rules[name] = build_regime(dates, lambda ts, t=thresh: br.get(ts, 0.5) >= t, confirm)

for ma_n in [60, 120, 150, 200, 250]:
    ma = kospi_ma[ma_n]
    for confirm in [2, 3, 4, 5]:
        name = f'KP_MA{ma_n}_{confirm}d'
        regime_rules[name] = build_regime(dates,
            lambda ts, m=ma: kospi.get(ts, 0) > m.get(ts, 0) if ts in kospi.index else True, confirm)

if kosdaq is not None:
    for ma_n in [60, 120]:
        kp_ma = kospi_ma[ma_n]
        kd_ma = kosdaq_ma[ma_n]
        for confirm in [3, 4, 5]:
            name = f'KK_MA{ma_n}_{confirm}d'
            regime_rules[name] = build_regime(dates,
                lambda ts, km=kp_ma, dm=kd_ma: (kospi.get(ts,0) > km.get(ts,0) and kosdaq.get(ts,0) > dm.get(ts,0)) if ts in kospi.index else True,
                confirm)

print(f'  국면 규칙: {len(regime_rules)}개', flush=True)

# EXS Top에서 최적 E/X/S/SL/TS 추출
best_exs = exs_df.iloc[0]
best_entry = int(best_exs['entry'])
best_exit = int(best_exs['exit'])
best_slots = int(best_exs['slots'])
best_sl = float(best_exs['sl'])
best_ts_val = float(best_exs['ts'])

# 공격Top5 × 방어Top5 × 규칙
regime_results = []
total_regime = 5 * 5 * len(regime_rules)
count = 0

for _, a in atk_df.head(5).iterrows():
    op = {'v': a['v']/100, 'q': a['q']/100, 'g': a['g']/100, 'm': a['m']/100,
          'g_rev': a['gr'], 'entry': best_entry, 'exit': best_exit, 'slots': best_slots, 'mom': a['mom']}
    for _, d in def_df.head(5).iterrows():
        dp = {'v': d['v']/100, 'q': d['q']/100, 'g': d['g']/100, 'm': d['m']/100,
              'g_rev': d['gr'], 'entry': best_entry, 'exit': best_exit,
              'slots': max(best_slots, 5), 'mom': d['mom']}
        for rule_name, regime_d in regime_rules.items():
            r = tsim_full.run_regime(dp, op, regime_d,
                stop_loss=best_sl, trailing_stop=best_ts_val,
                g_sub1_d=d['gs1'], g_sub2_d=d['gs2'],
                g_sub1_o=a['gs1'], g_sub2_o=a['gs2'])
            sw = sum(1 for i in range(1, len(dates)) if regime_d[dates[i]] != regime_d[dates[i-1]])
            boost_pct = sum(1 for v in regime_d.values() if v) / len(regime_d) * 100
            regime_results.append({
                'atk': f"V{int(a['v'])}Q{int(a['q'])}G{int(a['g'])}M{int(a['m'])}g{a['gr']:.1f}{a['mom']}",
                'def': f"V{int(d['v'])}Q{int(d['q'])}G{int(d['g'])}M{int(d['m'])}g{d['gr']:.1f}{d['mom']}",
                'atk_gs': f"{a['gs1']}+{a['gs2']}", 'def_gs': f"{d['gs1']}+{d['gs2']}",
                'rule': rule_name,
                'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                'sw': sw, 'boost': boost_pct,
            })
            count += 1
        if count % 200 == 0:
            print(f'  {count}/{total_regime}', flush=True)

regime_df = pd.DataFrame(regime_results).sort_values('cal', ascending=False)
regime_df.to_csv(RESULT_DIR / 'v77_regime_search.csv', index=False)

msg = f'[v77 Step 4: 국면서치 완료]\n소요: {(time.time()-t_regime)/60:.0f}분\n{len(regime_results)}조합\n\n'
msg += 'Top 5:\n'
for _, r in regime_df.head(5).iterrows():
    msg += f'  {r["rule"]} {r["atk"]} / {r["def"]} Cal={r["cal"]:.2f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}%\n'
msg += f'\n규칙별 Top1:\n'
for rule in regime_df.groupby('rule')['cal'].max().sort_values(ascending=False).head(5).index:
    row = regime_df[regime_df['rule']==rule].sort_values('cal', ascending=False).iloc[0]
    msg += f'  {rule}: Cal={row["cal"]:.2f} CAGR={row["cagr"]:.1f}%\n'
send_tg(msg)
print(msg, flush=True)


# ============================================================
# Step 5: 인접 안정성 + WF 검증
# ============================================================
print('\nStep 5: 인접 안정성 + WF 검증', flush=True)
t_stab = time.time()

best = regime_df.iloc[0]
print(f'  최적: {best["rule"]} {best["atk"]} / {best["def"]} Cal={best["cal"]:.2f}', flush=True)

# 인접 안정성: 최적 가중치 ±5%p 이웃
# 최적 공격/방어 파라미터 추출
best_atk_row = atk_df.head(1).iloc[0]
best_def_row = def_df.head(1).iloc[0]
best_rule = best['rule']
best_regime = regime_rules[best_rule]

neighbors = []
bv, bq, bg, bm = int(best_atk_row['v']), int(best_atk_row['q']), int(best_atk_row['g']), int(best_atk_row['m'])
for dv in [-5, 0, 5]:
    for dq in [-5, 0, 5]:
        for dg in [-5, 0, 5]:
            nv, nq, ng = bv + dv, bq + dq, bg + dg
            nm = 100 - nv - nq - ng
            if nv < 0 or nq < 0 or ng < 10 or nm < 10 or nm > 60:
                continue
            if (nv, nq, ng, nm) == (bv, bq, bg, bm):
                continue
            op = {'v': nv/100, 'q': nq/100, 'g': ng/100, 'm': nm/100,
                  'g_rev': best_atk_row['gr'], 'entry': best_entry, 'exit': best_exit,
                  'slots': best_slots, 'mom': best_atk_row['mom']}
            dp = {'v': best_def_row['v']/100, 'q': best_def_row['q']/100,
                  'g': best_def_row['g']/100, 'm': best_def_row['m']/100,
                  'g_rev': best_def_row['gr'], 'entry': best_entry, 'exit': best_exit,
                  'slots': max(best_slots, 5), 'mom': best_def_row['mom']}
            r = tsim_full.run_regime(dp, op, best_regime,
                stop_loss=best_sl, trailing_stop=best_ts_val,
                g_sub1_d=best_def_row['gs1'], g_sub2_d=best_def_row['gs2'],
                g_sub1_o=best_atk_row['gs1'], g_sub2_o=best_atk_row['gs2'])
            neighbors.append({
                'v': nv, 'q': nq, 'g': ng, 'm': nm,
                'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'],
            })

stable_count = sum(1 for n in neighbors if n['cal'] >= 3.0)
stability = stable_count / len(neighbors) * 100 if neighbors else 0
print(f'  인접 안정성: {stable_count}/{len(neighbors)} ({stability:.0f}%) Cal≥3.0', flush=True)

# WF 3기간
wf_periods = [
    (['2021', '2022', '2023'], ['2024']),
    (['2022', '2023', '2024'], ['2025']),
    (['2021', '2022', '2023', '2024'], ['2025', '2026']),
]

wf_results = []
for train_years, test_years in wf_periods:
    train_dates_wf = [d for d in dates if d[:4] in train_years]
    test_dates_wf = [d for d in dates if d[:4] in test_years]
    if not train_dates_wf or not test_dates_wf:
        continue

    for label, mode_dates in [('train', train_dates_wf), ('test', test_dates_wf)]:
        rd_wf = {d: best_regime[d] for d in mode_dates if d in best_regime}
        rk_wf = {d: rk[d] for d in mode_dates}
        tsim_wf = TurboSimulator(rk_wf, mode_dates, ohlcv, bench=bench)

        op = {'v': best_atk_row['v']/100, 'q': best_atk_row['q']/100,
              'g': best_atk_row['g']/100, 'm': best_atk_row['m']/100,
              'g_rev': best_atk_row['gr'], 'entry': best_entry, 'exit': best_exit,
              'slots': best_slots, 'mom': best_atk_row['mom']}
        dp = {'v': best_def_row['v']/100, 'q': best_def_row['q']/100,
              'g': best_def_row['g']/100, 'm': best_def_row['m']/100,
              'g_rev': best_def_row['gr'], 'entry': best_entry, 'exit': best_exit,
              'slots': max(best_slots, 5), 'mom': best_def_row['mom']}

        r = tsim_wf.run_regime(dp, op, rd_wf,
            stop_loss=best_sl, trailing_stop=best_ts_val,
            g_sub1_d=best_def_row['gs1'], g_sub2_d=best_def_row['gs2'],
            g_sub1_o=best_atk_row['gs1'], g_sub2_o=best_atk_row['gs2'])
        period = f'{train_years[0]}~{train_years[-1]}' if label == 'train' else f'{test_years[0]}~{test_years[-1]}'
        wf_results.append({'period': period, 'type': label, 'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']})

wf_df = pd.DataFrame(wf_results)

msg = f'[v77 Step 5: 안정성+WF 완료]\n소요: {(time.time()-t_stab)/60:.0f}분\n\n'
msg += f'인접 안정성: {stable_count}/{len(neighbors)} ({stability:.0f}%) Cal≥3.0\n\n'
msg += 'WF 검증:\n'
for _, r in wf_df.iterrows():
    msg += f'  {r["type"]} {r["period"]}: Cal={r["cal"]:.2f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}%\n'
send_tg(msg)
print(msg, flush=True)


# ============================================================
# 최종 요약
# ============================================================
total_time = (time.time() - t_pipeline) / 60

final_msg = f"""[v77 전체 최적화 완료]
소요: {total_time:.0f}분

최적 전략:
  공격: V{int(best_atk_row['v'])}Q{int(best_atk_row['q'])}G{int(best_atk_row['g'])}M{int(best_atk_row['m'])} gr={best_atk_row['gr']} {best_atk_row['gs1']}+{best_atk_row['gs2']} {best_atk_row['mom']}
  방어: V{int(best_def_row['v'])}Q{int(best_def_row['q'])}G{int(best_def_row['g'])}M{int(best_def_row['m'])} gr={best_def_row['gr']} {best_def_row['gs1']}+{best_def_row['gs2']} {best_def_row['mom']}
  규칙: {best_rule}
  E{best_entry}/X{best_exit}/S{best_slots} SL={best_sl} TS={best_ts_val}

성과: Cal={best['cal']:.2f} CAGR={best['cagr']:.1f}% MDD={best['mdd']:.1f}%
안정성: {stability:.0f}% ({stable_count}/{len(neighbors)})

WF:
"""
for _, r in wf_df.iterrows():
    final_msg += f'  {r["type"]} {r["period"]}: Cal={r["cal"]:.2f}\n'

send_tg(final_msg)
print(final_msg, flush=True)

# 결과 저장
final_result = {
    'attack': {'v': int(best_atk_row['v']), 'q': int(best_atk_row['q']),
               'g': int(best_atk_row['g']), 'm': int(best_atk_row['m']),
               'gr': float(best_atk_row['gr']), 'gs1': best_atk_row['gs1'],
               'gs2': best_atk_row['gs2'], 'mom': best_atk_row['mom']},
    'defense': {'v': int(best_def_row['v']), 'q': int(best_def_row['q']),
                'g': int(best_def_row['g']), 'm': int(best_def_row['m']),
                'gr': float(best_def_row['gr']), 'gs1': best_def_row['gs1'],
                'gs2': best_def_row['gs2'], 'mom': best_def_row['mom']},
    'rule': best_rule,
    'entry': best_entry, 'exit': best_exit, 'slots': best_slots,
    'stop_loss': best_sl, 'trailing_stop': best_ts_val,
    'calmar': float(best['cal']), 'cagr': float(best['cagr']), 'mdd': float(best['mdd']),
    'stability': stability,
}
with open(RESULT_DIR / 'v77_final_strategy.json', 'w') as f:
    json.dump(final_result, f, indent=2)
print(f'\n저장: v77_final_strategy.json', flush=True)
