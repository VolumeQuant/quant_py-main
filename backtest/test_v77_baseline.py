"""v77 bt 성과 검증 — ROE DART 폴백 + 우선주 필터 적용 후

bt_v77 (ROE 수정) vs bt_test_A (기존 v76) 비교
1. v76 파라미터로 양쪽 성과 비교
2. 유니버스 변화 통계
3. 주요 종목 확인
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

# v76 파라미터
op = {'v': 0.15, 'q': 0.05, 'g': 0.60, 'm': 0.20, 'g_rev': 0.6,
      'entry': 5, 'exit': 8, 'slots': 3, 'mom': '12m-1m'}
dp = {'v': 0.15, 'q': 0.10, 'g': 0.25, 'm': 0.50, 'g_rev': 0.7,
      'entry': 5, 'exit': 8, 'slots': 5, 'mom': '6m-1m'}

for label, bt_dir in [('v76 (기존 bt_test_A)', 'backtest/bt_test_A'),
                       ('v77 (ROE수정 bt_v77)', 'backtest/bt_v77')]:
    bt = Path(f'c:/dev/{bt_dir}')
    dates = sorted([f.stem.replace('ranking_', '') for f in bt.glob('ranking_*.json')])
    if not dates:
        print(f'{label}: 파일 없음 — 스킵')
        continue

    rk = {}
    for d in dates:
        with open(bt / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
            rk[d] = json.load(f).get('rankings', [])

    # 국면 규칙
    mode = False; streak = 0; ss = False; rd = {}
    for d in dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts, None); mv = km200.get(ts, None)
        s = (kv > mv) if kv is not None and mv is not None else mode
        if s == ss: streak += 1
        else: streak = 1; ss = s
        if streak >= 5 and mode != s: mode = s
        rd[d] = mode

    # 유니버스 통계
    avg_stocks = np.mean([len(rk[d]) for d in dates])

    print(f'\n{"="*70}')
    print(f'{label}')
    print(f'{"="*70}')
    print(f'  기간: {dates[0]} ~ {dates[-1]} ({len(dates)}일)')
    print(f'  평균 유니버스: {avg_stocks:.0f}종목')

    tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
    r = tsim.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
        g_sub1_d='rev_z', g_sub2_d='op_margin_z', g_sub1_o='oca_z', g_sub2_o='op_margin_z')
    print(f'  CAGR={r["cagr"]:.1f}%  MDD={r["mdd"]:.1f}%  Cal={r["calmar"]:.2f}  Sh={r["sharpe"]:.2f}  So={r["sortino"]:.2f}')

    # 주요 종목 확인 (최근 날짜)
    last = rk[dates[-1]]
    print(f'\n  최근({dates[-1]}) 상위 10:')
    for s in sorted(last, key=lambda x: x['rank'])[:10]:
        print(f'    {s["rank"]:>3}. {s.get("name","?"):<12} V={s.get("value_s",0):.2f} Q={s.get("quality_s",0):.2f}')

    # 브이엠/선익시스템
    for tk, nm in [('089970', '브이엠'), ('171090', '선익시스템')]:
        found = [s for s in last if s['ticker'] == tk]
        if found:
            print(f'  → {nm}: rank={found[0]["rank"]}')
        else:
            print(f'  → {nm}: 없음')

print(f'\n총 소요: {time.time()-t0:.0f}s')
