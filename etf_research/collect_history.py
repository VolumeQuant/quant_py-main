"""다국면 검증용 과거 수집 (krx_auth.login). OHLCV 2021~ (괴리율 다국면) + 분기 홀딩스 2023~ (consensus 다국면).
순차+1초, 체크포인트. 백그라운드.
실행: python etf_research/collect_history.py
"""
import sys, time, json
from pathlib import Path
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import krx_auth
if not krx_auth.login(): print('로그인 실패'); sys.exit(1)
import pykrx.stock as s
C = Path(__file__).parent / '_cache'
SLEEP = 1.0
uni = json.loads((C/'universe.json').read_text(encoding='utf-8'))
liquid = uni['liquid']; active = uni['active_equity']
BASE = s.get_nearest_business_day_in_a_week()

# === OHLCV 2021~ (liquid) → 괴리율 다국면 ===
OF = C / 'ohlcv_hist.parquet'
if not OF.exists():
    rows = []
    for i, t in enumerate(liquid):
        try:
            df = s.get_etf_ohlcv_by_date('20210101', BASE, t)
            if df is not None and len(df):
                vc = next((c for c in df.columns if '거래대금' in c), None)
                for d, r in df.iterrows():
                    rows.append({'date': d.strftime('%Y%m%d'), 'etf': t,
                                 'nav': float(r['NAV']) if 'NAV' in r else 0.0,
                                 'close': float(r['종가']), 'value': float(r[vc]) if vc else 0.0})
        except Exception: pass
        time.sleep(SLEEP)
        if i % 50 == 0: print(f'  ohlcv_hist {i}/{len(liquid)} rows {len(rows)}', flush=True)
    pd.DataFrame(rows).to_parquet(OF)
    print(f'[OHLCV_HIST] done rows {len(rows)}', flush=True)
else:
    print('[OHLCV_HIST] skip', flush=True)

# === 분기 홀딩스 2023~2026 (active) → consensus 다국면 ===
HF = C / 'holdings_hist.parquet'
SNAPS = ['20230102','20230403','20230703','20231002','20240102','20240401','20240701','20241001',
         '20250102','20250401','20250701','20251001','20260102','20260401']
done = set(); rows = []
if HF.exists():
    prev = pd.read_parquet(HF); done = set(zip(prev['snap'], prev['etf'])); rows = prev.to_dict('records')
snaps = []
for d in SNAPS:
    snaps.append(s.get_nearest_business_day_in_a_week(d)); time.sleep(SLEEP)
print(f'[HOLD_HIST] {len(snaps)} 분기 × active {len(active)} (done {len(done)})', flush=True)
cnt = 0
for sd in snaps:
    for t in active:
        if (sd, t) in done: continue
        try:
            p = s.get_etf_portfolio_deposit_file(t, sd)
            if p is not None and len(p):
                p.index = p.index.astype(str); p = p[~p.index.duplicated()]
                wcol = next((c for c in p.columns if '비중' in c), None)
                for stk in p.index:
                    if not stk.isdigit(): continue
                    rows.append({'snap': sd, 'etf': t, 'stock': stk,
                                 'weight': float(p.loc[stk, wcol]) if wcol else 0.0})
        except Exception: pass
        time.sleep(SLEEP); cnt += 1
        if cnt % 200 == 0:
            pd.DataFrame(rows).to_parquet(HF); print(f'  hold_hist {cnt} rows {len(rows)}', flush=True)
pd.DataFrame(rows).to_parquet(HF)
print(f'[HOLD_HIST] done rows {len(rows)}', flush=True)
print('=== 과거 수집 완료 ===', flush=True)
