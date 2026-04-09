"""FWD_PER 보너스 도입 vs 미도입 성과 비교 (테스트 전용)

FWD_BONUS 로직 (삭제된 원본):
  - forward_per < current PER인 종목 (EPS 개선 기대)에 score_std * ALPHA 가산
  - 원래 ALPHA = 0.10 (10%)

역사적 forward_per 데이터 없으므로 프록시 사용:
  - oca_z > 0 (영업이익변화 양수) = EPS 개선 기대 종목 대리변수
  - 보너스: value_s에 (score_std * ALPHA / v_w) 가산 → 총 점수에 score_std * ALPHA 효과

프로덕션 코드 수정 없음. 테스트 전용.
"""
import sys, json, numpy as np, pandas as pd, time, copy
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'c:/dev')
sys.path.insert(0, 'c:/dev/backtest')
from pathlib import Path
from turbo_simulator import TurboSimulator

t0 = time.time()

# ── 데이터 로드 ──
ohlcv_files = sorted(Path('c:/dev/data_cache').glob('all_ohlcv_20190603_*.parquet'))
ohlcv_path = ohlcv_files[-1] if ohlcv_files else None
print(f'OHLCV: {ohlcv_path.name}', flush=True)
ohlcv = pd.read_parquet(ohlcv_path).replace(0, np.nan)
bench = pd.read_parquet('c:/dev/data_cache/kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

bt = Path('c:/dev/backtest/bt_test_A')
dates = sorted([f.stem.replace('ranking_', '') for f in bt.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(bt / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

# ── 국면 규칙 (KP_MA200_5d) ──
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

# ── 기준: FWD 보너스 없음 (현행 v76) ──
print(f'\n{"="*70}', flush=True)
print('기준: 현행 v76 (FWD_PER 보너스 없음)', flush=True)
print(f'{"="*70}', flush=True)

tsim_base = TurboSimulator(rk, dates, ohlcv, bench=bench)
r_base = tsim_base.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
    g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
print(f'CAGR={r_base["cagr"]:.1f}%  MDD={r_base["mdd"]:.1f}%  Cal={r_base["calmar"]:.2f}  Sh={r_base["sharpe"]:.2f}', flush=True)

# ── FWD_PER 보너스 시뮬레이션 ──
print(f'\n{"="*70}', flush=True)
print('FWD_PER 보너스 시뮬레이션', flush=True)
print('  프록시: oca_z > 0 (영업이익 개선 종목) = forward_per < PER 대리', flush=True)
print('  보너스: score += score_std × ALPHA', flush=True)
print(f'{"="*70}', flush=True)

# 적용 비율 통계
total_stocks = sum(len(rk.get(d, [])) for d in dates)
qualifying = sum(1 for d in dates for s in rk.get(d, []) if (s.get('oca_z', 0) or 0) > 0)
print(f'  전체: {total_stocks}건, 적용 대상(oca_z>0): {qualifying}건 ({qualifying/total_stocks*100:.0f}%)', flush=True)

for ALPHA in [0.05, 0.10, 0.15, 0.20, 0.30]:
    rk_fwd = {}
    for d in dates:
        items = rk[d]
        if not items:
            rk_fwd[d] = items
            continue

        # 당일 score_std 추정 (v76 boost 가중치 기준)
        scores = []
        for s in items:
            v = s.get('value_s', 0) or 0
            q = s.get('quality_s', 0) or 0
            g = s.get('growth_s', 0) or 0
            m = s.get('mom_12m1m_s', 0) or s.get('momentum_s', 0) or 0
            scores.append(0.15*v + 0.05*q + 0.60*g + 0.20*m)
        score_std = np.std(scores) if scores else 0.3

        bonus_per_value_s = (score_std * ALPHA) / 0.15  # value_s 경유 보너스

        new_items = []
        for s in items:
            oca = s.get('oca_z', 0) or 0
            if oca > 0:
                ns = dict(s)
                ns['value_s'] = (ns.get('value_s', 0) or 0) + bonus_per_value_s
                new_items.append(ns)
            else:
                new_items.append(s)
        rk_fwd[d] = new_items

    tsim_fwd = TurboSimulator(rk_fwd, dates, ohlcv, bench=bench)
    r_fwd = tsim_fwd.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
        g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')

    d_cagr = r_fwd['cagr'] - r_base['cagr']
    d_cal = r_fwd['calmar'] - r_base['calmar']
    print(f'  ALPHA={ALPHA*100:>3.0f}%: CAGR={r_fwd["cagr"]:>6.1f}%  MDD={r_fwd["mdd"]:>5.1f}%  Cal={r_fwd["calmar"]:>5.2f}  Sh={r_fwd["sharpe"]:>5.2f}  (vs현행 CAGR{d_cagr:>+6.1f}%p Cal{d_cal:>+5.2f})', flush=True)

# ── 다른 프록시도 테스트 ──
print(f'\n{"="*70}', flush=True)
print('프록시 비교 (ALPHA=10% 고정)', flush=True)
print(f'{"="*70}', flush=True)

ALPHA = 0.10
proxies = {
    'oca_z > 0': lambda s: (s.get('oca_z', 0) or 0) > 0,
    'rev_z > 0': lambda s: (s.get('rev_z', 0) or 0) > 0,
    'oca_z > 0 AND rev_z > 0': lambda s: (s.get('oca_z', 0) or 0) > 0 and (s.get('rev_z', 0) or 0) > 0,
    'op_margin_z > 0': lambda s: (s.get('op_margin_z', 0) or 0) > 0,
    'value_s > 0 (저평가+개선)': lambda s: (s.get('value_s', 0) or 0) > 0 and (s.get('oca_z', 0) or 0) > 0,
}

for name, proxy_fn in proxies.items():
    rk_fwd = {}
    q_count = 0
    for d in dates:
        items = rk[d]
        if not items:
            rk_fwd[d] = items
            continue

        scores = []
        for s in items:
            v = s.get('value_s', 0) or 0
            q = s.get('quality_s', 0) or 0
            g = s.get('growth_s', 0) or 0
            m = s.get('mom_12m1m_s', 0) or s.get('momentum_s', 0) or 0
            scores.append(0.15*v + 0.05*q + 0.60*g + 0.20*m)
        score_std = np.std(scores) if scores else 0.3
        bonus_per_value_s = (score_std * ALPHA) / 0.15

        new_items = []
        for s in items:
            if proxy_fn(s):
                ns = dict(s)
                ns['value_s'] = (ns.get('value_s', 0) or 0) + bonus_per_value_s
                new_items.append(ns)
                q_count += 1
            else:
                new_items.append(s)
        rk_fwd[d] = new_items

    pct = q_count / total_stocks * 100
    tsim_fwd = TurboSimulator(rk_fwd, dates, ohlcv, bench=bench)
    r_fwd = tsim_fwd.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
        g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
    d_cal = r_fwd['calmar'] - r_base['calmar']
    print(f'  {name:<30} ({pct:>3.0f}%): CAGR={r_fwd["cagr"]:>6.1f}%  MDD={r_fwd["mdd"]:>5.1f}%  Cal={r_fwd["calmar"]:>5.2f} ({d_cal:>+5.2f})', flush=True)

# ── 요약 ──
print(f'\n{"="*70}', flush=True)
print('요약', flush=True)
print(f'{"="*70}', flush=True)
print(f'현행 v76 (FWD 없음):  CAGR={r_base["cagr"]:.1f}%  MDD={r_base["mdd"]:.1f}%  Cal={r_base["calmar"]:.2f}', flush=True)
print(f'\n주의: 역사적 forward_per 데이터 없어 oca_z 프록시 사용.', flush=True)
print(f'      TurboSim 레벨 테스트라 z-score 불변 가정 (FG 재생성 시 결과 다를 수 있음).', flush=True)
print(f'\n총 소요: {time.time()-t0:.0f}s', flush=True)
