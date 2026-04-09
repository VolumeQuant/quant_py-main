"""v76 확장 테스트 — 3가지 전략 (v76 소스 무변경)
1. 공격 모드 MA120 제거
2. 순위 연속 악화 이탈
3. MA 기울기(slope) 필터
"""
import sys, json, numpy as np, pandas as pd, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'c:/dev')
sys.path.insert(0, 'c:/dev/backtest')
from pathlib import Path
from turbo_simulator import TurboSimulator

t0 = time.time()

# 데이터 로드
ohlcv = pd.read_parquet('c:/dev/data_cache/all_ohlcv_20190603_20260406.parquet').replace(0, np.nan)
bench = pd.read_parquet('c:/dev/data_cache/kospi_yf.parquet')
kospi = pd.read_parquet('c:/dev/data_cache/kospi_yf.parquet').iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

# bt_test_A (MA120 적용)
bt_a = Path('c:/dev/backtest/bt_test_A')
dates = sorted([f.stem.replace('ranking_', '') for f in bt_a.glob('ranking_*.json')])
rk_a = {}
for d in dates:
    rk_a[d] = json.load(open(bt_a / f'ranking_{d}.json', 'r', encoding='utf-8')).get('rankings', [])

# 국면 규칙 (KP_MA200_5d)
mode = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d)
    kv = kospi.get(ts, None); mv = km200.get(ts, None)
    s = (kv > mv) if kv is not None and mv is not None else mode
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and mode != s: mode = s
    rd[d] = mode

# v76 가중치
op = {'v': 0.15, 'q': 0.05, 'g': 0.60, 'm': 0.20, 'g_rev': 0.6, 'entry': 5, 'exit': 8, 'slots': 3, 'mom': '12m-1m'}
dp = {'v': 0.15, 'q': 0.10, 'g': 0.25, 'm': 0.50, 'g_rev': 0.7, 'entry': 5, 'exit': 8, 'slots': 5, 'mom': '6m-1m'}

print(f'데이터 로드: {time.time()-t0:.0f}s', flush=True)

# ================================================================
# 기준: v76 현행
# ================================================================
print(f'\n{"="*70}', flush=True)
print('기준: v76 현행', flush=True)
print(f'{"="*70}', flush=True)

tsim_base = TurboSimulator(rk_a, dates, ohlcv, bench=bench)
r_base = tsim_base.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
    g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
print(f'CAGR={r_base["cagr"]:.1f}% MDD={r_base["mdd"]:.1f}% Cal={r_base["calmar"]:.2f} Sh={r_base["sharpe"]:.2f}', flush=True)

# ================================================================
# 테스트 1: 공격 모드에서 MA120 제거
# ================================================================
print(f'\n{"="*70}', flush=True)
print('테스트 1: 공격 모드에서 MA120 제거', flush=True)
print('  공격일: MA120 없는 bt 사용, 방어일: MA120 있는 bt 사용', flush=True)
print(f'{"="*70}', flush=True)

# MA120 없는 bt 생성 필요 — 이미 bt_v75에 있는지 확인, 없으면 생성
bt_no_ma = Path('c:/dev/backtest/bt_test_A_no_ma120')
if not bt_no_ma.exists() or len(list(bt_no_ma.glob('ranking_*.json'))) < len(dates):
    print('  bt_test_A_no_ma120 생성 중 (--no-ma120)...', flush=True)
    import subprocess, os
    bt_no_ma.mkdir(exist_ok=True)
    # 3분할 병렬
    procs = []
    splits = [('20210104', '20220630'), ('20220701', '20240630'), ('20240701', '20260403')]
    for s, e in splits:
        env = {**os.environ, 'FILTER_NO_CHRONIC': '1', 'FILTER_NO_ASSET_DIL': '1'}
        p = subprocess.Popen(
            [sys.executable, 'c:/dev/backtest/fast_generate_rankings_v2.py', s, e,
             f'--state-dir={bt_no_ma}', '--no-ma120'],
            env=env, cwd='c:/dev'
        )
        procs.append(p)
    for p in procs:
        p.wait()
    print(f'  생성 완료: {len(list(bt_no_ma.glob("ranking_*.json")))}일', flush=True)
else:
    print(f'  bt_test_A_no_ma120 캐시 사용: {len(list(bt_no_ma.glob("ranking_*.json")))}일', flush=True)

rk_no_ma = {}
for d in dates:
    f = bt_no_ma / f'ranking_{d}.json'
    if f.exists():
        rk_no_ma[d] = json.load(open(f, 'r', encoding='utf-8')).get('rankings', [])
    else:
        rk_no_ma[d] = rk_a.get(d, [])

# 공격일은 no_ma120, 방어일은 ma120
rk_hybrid = {}
for d in dates:
    if rd[d]:  # boost (공격)
        rk_hybrid[d] = rk_no_ma.get(d, [])
    else:  # defense (방어)
        rk_hybrid[d] = rk_a.get(d, [])

avg_atk = np.mean([len(rk_hybrid[d]) for d in dates if rd[d]])
avg_def = np.mean([len(rk_hybrid[d]) for d in dates if not rd[d]])
print(f'  공격 평균 {avg_atk:.0f}종목 (MA120 없음), 방어 평균 {avg_def:.0f}종목 (MA120 있음)', flush=True)

tsim1 = TurboSimulator(rk_hybrid, dates, ohlcv, bench=bench)
r1 = tsim1.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
    g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
print(f'결과: CAGR={r1["cagr"]:.1f}% MDD={r1["mdd"]:.1f}% Cal={r1["calmar"]:.2f} Sh={r1["sharpe"]:.2f}', flush=True)
print(f'vs 현행: CAGR {r1["cagr"]-r_base["cagr"]:+.1f}%p  MDD {r1["mdd"]-r_base["mdd"]:+.1f}%p  Cal {r1["calmar"]-r_base["calmar"]:+.2f}', flush=True)

# ================================================================
# 테스트 2: 순위 연속 악화 이탈
# ================================================================
print(f'\n{"="*70}', flush=True)
print('테스트 2: 순위 연속 악화 이탈', flush=True)
print('  WR이 3일 연속 악화 AND WR > threshold → 강제 이탈', flush=True)
print(f'{"="*70}', flush=True)

# TurboSim 내부를 수정할 수 없으니, ranking에서 시뮬레이션
# WR 악화 종목을 ranking에서 제거하면 TurboSim이 자연 이탈
# 3일 연속이라 T-0, T-1, T-2의 composite_rank 비교 필요

for wr_threshold in [4, 5, 6]:
    rk_streak = {}
    for i, d in enumerate(dates):
        if i < 2:
            rk_streak[d] = rk_a[d]
            continue
        d1, d2 = dates[i-1], dates[i-2]
        # 현재/어제/그저께 composite_rank
        cr0 = {x['ticker']: x.get('composite_rank', x['rank']) for x in rk_a.get(d, [])}
        cr1 = {x['ticker']: x.get('composite_rank', x['rank']) for x in rk_a.get(d1, [])}
        cr2 = {x['ticker']: x.get('composite_rank', x['rank']) for x in rk_a.get(d2, [])}

        # WR 계산
        bad_tickers = set()
        for tk in cr0:
            r0 = cr0.get(tk, 999)
            r1 = cr1.get(tk, 999)
            r2 = cr2.get(tk, 999)
            wr = r0 * 0.5 + r1 * 0.3 + r2 * 0.2
            # 3일 연속 악화: r0 > r1 > r2 (순위 숫자가 커짐 = 악화)
            if r0 > r1 > r2 and wr > wr_threshold:
                bad_tickers.add(tk)

        rk_streak[d] = [x for x in rk_a[d] if x['ticker'] not in bad_tickers]

    tsim2 = TurboSimulator(rk_streak, dates, ohlcv, bench=bench)
    r2 = tsim2.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
        g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
    avg = np.mean([len(v) for v in rk_streak.values()])
    print(f'  WR>{wr_threshold} 3일악화 제거 ({avg:.0f}종목): CAGR={r2["cagr"]:.1f}% MDD={r2["mdd"]:.1f}% Cal={r2["calmar"]:.2f} (vs현행 {r2["calmar"]-r_base["calmar"]:+.2f})', flush=True)

# ================================================================
# 테스트 3: MA 기울기(slope) 필터
# ================================================================
print(f'\n{"="*70}', flush=True)
print('테스트 3: MA 기울기(slope) 필터', flush=True)
print('  MA60 기울기 음수(하락 가속) 종목만 제거', flush=True)
print(f'{"="*70}', flush=True)

# MA60 사전계산
ma60 = ohlcv.rolling(60).mean()
ma60_20ago = ma60.shift(20)

for slope_thresh in [-0.05, -0.03, -0.01, 0.0]:
    rk_slope = {}
    for d in dates:
        ts = pd.Timestamp(d)
        kept = []
        for x in rk_a.get(d, []):
            tk = x['ticker']
            if tk in ma60.columns and ts in ma60.index:
                cur = ma60.at[ts, tk] if pd.notna(ma60.at[ts, tk]) else None
                prev = ma60_20ago.at[ts, tk] if ts in ma60_20ago.index and pd.notna(ma60_20ago.at[ts, tk]) else None
                if cur is not None and prev is not None and prev > 0:
                    slope = (cur - prev) / prev
                    if slope < slope_thresh:
                        continue  # 하락 가속 → 제거
            kept.append(x)
        rk_slope[d] = kept

    tsim3 = TurboSimulator(rk_slope, dates, ohlcv, bench=bench)
    r3 = tsim3.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
        g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
    avg = np.mean([len(v) for v in rk_slope.values()])
    pct = slope_thresh * 100
    print(f'  MA60기울기<{pct:.0f}% 제거 ({avg:.0f}종목): CAGR={r3["cagr"]:.1f}% MDD={r3["mdd"]:.1f}% Cal={r3["calmar"]:.2f} (vs현행 {r3["calmar"]-r_base["calmar"]:+.2f})', flush=True)

# ================================================================
# 요약
# ================================================================
print(f'\n{"="*70}', flush=True)
print('요약', flush=True)
print(f'{"="*70}', flush=True)
print(f'현행 v76:  CAGR={r_base["cagr"]:.1f}%  MDD={r_base["mdd"]:.1f}%  Cal={r_base["calmar"]:.2f}', flush=True)
print(f'\n총 소요: {time.time()-t0:.0f}s', flush=True)
