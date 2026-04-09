"""FWD_PER 보너스 정식 테스트 — 실제 FnGuide forward_per 데이터 사용

수집된 데이터:
  - data_cache/consensus_forward_per.parquet (FnGuide 컨센서스)
  - data_cache/fundamental_batch_ALL_*.parquet (pykrx PER)

방법:
  1. forward_per < current PER인 종목 = EPS 개선 기대 (실제 FWD_BONUS 조건)
  2. 해당 종목의 멀티팩터 점수에 score_std × ALPHA 가산
  3. TurboSim으로 v76 국면전환 시뮬레이션
  4. 기준(보너스 없음)과 비교

제한사항:
  - 현재 시점 forward_per만 가용 (역사적 컨센서스 없음)
  - 과거 날짜에 현재 forward_per 적용 = look-ahead bias 있음
  - TurboSim 레벨 테스트 (z-score는 FG 원본 유지, 보너스는 score에 반영)

프로덕션 코드 수정 없음. 테스트 전용.
"""
import sys, json, numpy as np, pandas as pd, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'c:/dev')
sys.path.insert(0, 'c:/dev/backtest')
from pathlib import Path
from turbo_simulator import TurboSimulator

t0 = time.time()

# ── 데이터 로드 ──
ohlcv_files = sorted(Path('c:/dev/data_cache').glob('all_ohlcv_20190603_*.parquet'))
ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
bench = pd.read_parquet('c:/dev/data_cache/kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

bt = Path('c:/dev/backtest/bt_test_A')
dates = sorted([f.stem.replace('ranking_', '') for f in bt.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(bt / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

# ── forward_per 데이터 로드 ──
consensus = pd.read_parquet('c:/dev/data_cache/consensus_forward_per.parquet')
fund_files = sorted(Path('c:/dev/data_cache').glob('fundamental_batch_ALL_*.parquet'))
fund = pd.read_parquet(fund_files[-1])

# forward_per < PER 조건 (실제 FWD_BONUS 적용 대상)
merged = consensus.merge(fund[['PER']], left_on='ticker', right_index=True, how='left')
qualifying_strict = set(
    merged[(merged['forward_per'] > 0) & (merged['PER'] > 0) & (merged['forward_per'] < merged['PER'])]['ticker']
)
# 컨센서스 커버 전체 (forward_per 존재)
qualifying_coverage = set(
    consensus[consensus['has_consensus'] == True]['ticker']
)

print(f'forward_per < PER (EPS 개선): {len(qualifying_strict)}종목', flush=True)
print(f'컨센서스 커버 전체: {len(qualifying_coverage)}종목', flush=True)

# ── 국면 규칙 ──
mode = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d)
    kv = kospi.get(ts, None); mv = km200.get(ts, None)
    s = (kv > mv) if kv is not None and mv is not None else mode
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and mode != s: mode = s
    rd[d] = mode

# ── v76 파라미터 ──
op = {'v': 0.15, 'q': 0.05, 'g': 0.60, 'm': 0.20, 'g_rev': 0.6,
      'entry': 5, 'exit': 8, 'slots': 3, 'mom': '12m-1m'}
dp = {'v': 0.15, 'q': 0.10, 'g': 0.25, 'm': 0.50, 'g_rev': 0.7,
      'entry': 5, 'exit': 8, 'slots': 5, 'mom': '6m-1m'}

print(f'데이터 로드: {time.time()-t0:.0f}s ({len(dates)}일)', flush=True)

# ── 기준: FWD 보너스 없음 ──
print(f'\n{"="*70}', flush=True)
print('기준: 현행 v76 (FWD_PER 보너스 없음)', flush=True)
print(f'{"="*70}', flush=True)

tsim_base = TurboSimulator(rk, dates, ohlcv, bench=bench)
r_base = tsim_base.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
    g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
print(f'CAGR={r_base["cagr"]:.1f}%  MDD={r_base["mdd"]:.1f}%  Cal={r_base["calmar"]:.2f}  Sh={r_base["sharpe"]:.2f}', flush=True)


def apply_fwd_bonus(rk_orig, qualifying_set, alpha, v_w=0.15):
    """FWD_BONUS를 적용한 ranking 생성.

    보너스 방법: score += score_std × ALPHA
    TurboSim이 z-score에서 score를 재계산하므로,
    value_s에 (score_std × ALPHA / v_w)를 가산하여 동일 효과.
    """
    rk_fwd = {}
    for d, items in rk_orig.items():
        if not items:
            rk_fwd[d] = items
            continue

        # 당일 score_std 추정
        scores = []
        for s in items:
            v = s.get('value_s', 0) or 0
            q = s.get('quality_s', 0) or 0
            g = s.get('growth_s', 0) or 0
            m = s.get('mom_12m1m_s', 0) or s.get('momentum_s', 0) or 0
            scores.append(0.15*v + 0.05*q + 0.60*g + 0.20*m)
        score_std = np.std(scores) if scores else 0.3

        bonus_v = (score_std * alpha) / v_w

        new_items = []
        for s in items:
            if s['ticker'] in qualifying_set:
                ns = dict(s)
                ns['value_s'] = (ns.get('value_s', 0) or 0) + bonus_v
                new_items.append(ns)
            else:
                new_items.append(s)
        rk_fwd[d] = new_items
    return rk_fwd


def run_test(label, rk_data):
    tsim = TurboSimulator(rk_data, dates, ohlcv, bench=bench)
    r = tsim.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
        g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
    d_cagr = r['cagr'] - r_base['cagr']
    d_cal = r['calmar'] - r_base['calmar']
    print(f'  {label:<45} CAGR={r["cagr"]:>6.1f}%  MDD={r["mdd"]:>5.1f}%  Cal={r["calmar"]:>5.2f}  Sh={r["sharpe"]:>5.2f}  (vs현행 CAGR{d_cagr:>+6.1f}%p Cal{d_cal:>+5.2f})', flush=True)
    return r


# ── 테스트 1: forward_per < PER (실제 FWD_BONUS 조건, 123종목) ──
print(f'\n{"="*70}', flush=True)
print(f'테스트 1: forward_per < PER (EPS 개선, {len(qualifying_strict)}종목)', flush=True)
print(f'{"="*70}', flush=True)

for alpha in [0.05, 0.10, 0.15, 0.20, 0.30]:
    rk_fwd = apply_fwd_bonus(rk, qualifying_strict, alpha)
    run_test(f'ALPHA={alpha*100:.0f}% (fwd_per<PER, {len(qualifying_strict)}종목)', rk_fwd)


# ── 테스트 2: 컨센서스 커버 전체 (164종목) ──
print(f'\n{"="*70}', flush=True)
print(f'테스트 2: 컨센서스 커버 전체 ({len(qualifying_coverage)}종목)', flush=True)
print(f'{"="*70}', flush=True)

for alpha in [0.05, 0.10, 0.15, 0.20, 0.30]:
    rk_fwd = apply_fwd_bonus(rk, qualifying_coverage, alpha)
    run_test(f'ALPHA={alpha*100:.0f}% (커버 전체, {len(qualifying_coverage)}종목)', rk_fwd)


# ── 테스트 3: forward_per < PER × 0.8 (보수적 — 20% 이상 EPS 개선) ──
print(f'\n{"="*70}', flush=True)
qualifying_conservative = set(
    merged[(merged['forward_per'] > 0) & (merged['PER'] > 0) &
           (merged['forward_per'] < merged['PER'] * 0.8)]['ticker']
)
print(f'테스트 3: forward_per < PER×0.8 (보수적, {len(qualifying_conservative)}종목)', flush=True)
print(f'{"="*70}', flush=True)

for alpha in [0.05, 0.10, 0.15, 0.20, 0.30]:
    rk_fwd = apply_fwd_bonus(rk, qualifying_conservative, alpha)
    run_test(f'ALPHA={alpha*100:.0f}% (보수적, {len(qualifying_conservative)}종목)', rk_fwd)


# ── 요약 ──
print(f'\n{"="*70}', flush=True)
print('요약', flush=True)
print(f'{"="*70}', flush=True)
print(f'현행 v76 (FWD 없음):  CAGR={r_base["cagr"]:.1f}%  MDD={r_base["mdd"]:.1f}%  Cal={r_base["calmar"]:.2f}', flush=True)
print(f'\n수집 데이터:', flush=True)
print(f'  FnGuide 컨센서스: 311종목 중 {len(qualifying_coverage)}종목 커버 ({len(qualifying_coverage)/311*100:.0f}%)', flush=True)
print(f'  forward_per < PER: {len(qualifying_strict)}종목', flush=True)
print(f'  forward_per < PER×0.8: {len(qualifying_conservative)}종목', flush=True)
print(f'\n제한사항:', flush=True)
print(f'  - 현재 시점 forward_per 사용 (역사적 컨센서스 데이터 없음 → look-ahead bias)', flush=True)
print(f'  - TurboSim 레벨 테스트 (z-score 불변 가정)', flush=True)
print(f'\n총 소요: {time.time()-t0:.0f}s', flush=True)
