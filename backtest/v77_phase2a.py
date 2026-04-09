"""v77 Phase 2a — 공격/방어 각각 가중치 그리드서치

유니버스 변경(ROE DART 폴백 + 우선주 필터) 후 재최적화.
bt_test_A에서 날짜를 국면별로 분리 → 각각 TurboSim run_fast.
E5/X8 고정 (v76 Phase 2b에서 E5/X8 지배적 확인됨).
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator, TurboRunner

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
RESULT_DIR.mkdir(exist_ok=True)
t0 = time.time()

# ── 데이터 로드 ──
ohlcv_files = sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))
ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

# ── 국면 분리 (KP_MA200_5d) ──
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
print(f'전체: {len(dates)}일, 공격: {len(boost_dates)}일, 방어: {len(defense_dates)}일', flush=True)

# ── 가중치 그리드 ──
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
# G서브 서치 결과에서 상위 5쌍 로드 (쌍별 최고 Calmar 기준)
gsub_atk_file = RESULT_DIR / 'v77_gsub_attack_summary.csv'
gsub_def_file = RESULT_DIR / 'v77_gsub_defense_summary.csv'

if gsub_atk_file.exists() and gsub_def_file.exists():
    gsub_atk_all = pd.read_csv(gsub_atk_file).sort_values('avg_cal', ascending=False)
    gsub_def_all = pd.read_csv(gsub_def_file).sort_values('avg_cal', ascending=False)
    # 쌍별 최고 → 상위 5쌍+비율
    atk_top5 = gsub_atk_all.drop_duplicates(subset=['gs1', 'gs2'], keep='first').head(5)
    def_top5 = gsub_def_all.drop_duplicates(subset=['gs1', 'gs2'], keep='first').head(5)
    print(f'G서브 서치 결과 로드 — 상위 5쌍:')
    print(f'  공격:')
    for _, r in atk_top5.iterrows():
        print(f'    {r["gs1"]} + {r["gs2"]} gr={r["gr"]} avg_cal={r["avg_cal"]:.2f}')
    print(f'  방어:')
    for _, r in def_top5.iterrows():
        print(f'    {r["gs1"]} + {r["gs2"]} gr={r["gr"]} avg_cal={r["avg_cal"]:.2f}')
else:
    print('G서브 서치 결과 없음 — 실행 불가')
    sys.exit(1)

g_revs = [round(x * 0.1, 1) for x in range(11)]  # 0.0~1.0 step 0.1
mom_types = ['6m', '6m-1m', '12m', '12m-1m']

print(f'\n가중치: {len(weights)}, G비율: {len(g_revs)}, 모멘텀: {len(mom_types)}')
wg_combos = [(v,q,g,m,gr) for v,q,g,m in weights for gr in g_revs]
total_per_mode = len(wg_combos) * len(mom_types)
print(f'조합: {len(wg_combos)} × {len(mom_types)}mom × 5gsub = {total_per_mode * 5}개/모드')

# ── 서치 함수 ──
def search_mode(mode_dates, mode_name, entry=5, exit_r=8, slots=3, gs1='rev_z', gs2='op_margin_z'):
    rk_mode = {d: rk[d] for d in mode_dates}
    tsim = TurboSimulator(rk_mode, mode_dates, ohlcv, bench=bench)

    results = []
    done = 0
    t1 = time.time()
    total = len(wg_combos)

    for v, q, g, m, gr in wg_combos:
        for mom in mom_types:
            r = tsim.run_fast(v/100, q/100, g/100, m/100, gr,
                             entry_param=entry, exit_param=exit_r, max_slots=slots,
                             mom_type=mom, stop_loss=-0.10, trailing_stop=-0.15,
                             g_sub1=gs1, g_sub2=gs2)
            results.append({
                'v': v, 'q': q, 'g': g, 'm': m, 'gr': gr, 'mom': mom,
                'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                'sh': r['sharpe'], 'sort': r.get('sortino', 0),
            })
        done += 1
        if done % 100 == 0:
            elapsed = time.time() - t1
            rate = done / elapsed if elapsed > 0 else 1
            remain = (total - done) / rate / 60
            print(f'  [{mode_name}] {done}/{total} ({elapsed/60:.0f}분, 남은 ~{remain:.0f}분)', flush=True)

    df = pd.DataFrame(results).sort_values('cal', ascending=False)
    return df

# ── 공격 모드 서치 (상위 5쌍 각각) ──
all_atk = []
for idx, (_, gsrow) in enumerate(atk_top5.iterrows()):
    gs1, gs2 = gsrow['gs1'], gsrow['gs2']
    print(f'\n{"="*60}', flush=True)
    print(f'Phase 2a 공격 [{idx+1}/5]: {gs1} + {gs2} (E5/X8/S3, {len(boost_dates)}일)', flush=True)
    print(f'{"="*60}', flush=True)
    df = search_mode(boost_dates, f'공격{idx+1}', entry=5, exit_r=8, slots=3, gs1=gs1, gs2=gs2)
    df['gs1'] = gs1
    df['gs2'] = gs2
    all_atk.append(df)
    print(f'  Top3: Cal={df.iloc[0]["cal"]:.2f}, {df.iloc[1]["cal"]:.2f}, {df.iloc[2]["cal"]:.2f}', flush=True)

atk_df = pd.concat(all_atk).sort_values('cal', ascending=False)
atk_df.to_csv(RESULT_DIR / 'v77_phase2a_attack.csv', index=False)
print(f'\n공격 전체 Top 10:', flush=True)
print(atk_df.head(10).to_string(index=False), flush=True)
print(f'공격 완료: {time.time()-t0:.0f}s', flush=True)

# ── 방어 모드 서치 (상위 5쌍 각각) ──
all_def = []
for idx, (_, gsrow) in enumerate(def_top5.iterrows()):
    gs1, gs2 = gsrow['gs1'], gsrow['gs2']
    print(f'\n{"="*60}', flush=True)
    print(f'Phase 2a 방어 [{idx+1}/5]: {gs1} + {gs2} (E5/X8/S5, {len(defense_dates)}일)', flush=True)
    print(f'{"="*60}', flush=True)
    df = search_mode(defense_dates, f'방어{idx+1}', entry=5, exit_r=8, slots=5, gs1=gs1, gs2=gs2)
    df['gs1'] = gs1
    df['gs2'] = gs2
    all_def.append(df)
    print(f'  Top3: Cal={df.iloc[0]["cal"]:.2f}, {df.iloc[1]["cal"]:.2f}, {df.iloc[2]["cal"]:.2f}', flush=True)

def_df = pd.concat(all_def).sort_values('cal', ascending=False)
def_df.to_csv(RESULT_DIR / 'v77_phase2a_defense.csv', index=False)
print(f'\n방어 전체 Top 10:', flush=True)
print(def_df.head(10).to_string(index=False), flush=True)

print(f'\n총 소요: {(time.time()-t0)/60:.0f}분', flush=True)

# 텔레그램 알림
try:
    import requests
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
    msg = f'[v77 Phase 2a 완료]\n공격 Top1: Cal={atk_df.iloc[0]["cal"]:.2f}\n방어 Top1: Cal={def_df.iloc[0]["cal"]:.2f}\n소요: {(time.time()-t0)/60:.0f}분'
    requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                  data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=10)
except Exception:
    pass
