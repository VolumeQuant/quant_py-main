# -*- coding: utf-8 -*-
"""표본: 수정주가(OHLCV_FILE) + 최근CA페널티(W0.3 K126) 6/17 boost 재생성.
디바이스(무상증자 4/28=최근)가 페널티로 밀리는지 + 페널티 발동 종목 확인."""
import sys, os, io, glob, subprocess, json, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd
PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
VALL = sorted(glob.glob('C:/dev/data_cache/all_ohlcv_adj_*.parquet'))[-1]
SD = '_sample_pen'; os.makedirs(SD, exist_ok=True)
e = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'OHLCV_FILE': VALL, 'CORPACTION_ADJ_DISABLE': '1',
     'CA_EVENTS_FILE': 'C:/dev/data_cache/ca_events.json', 'FACTOR_RECENT_CA_W': '0.3', 'FACTOR_RECENT_CA_K': '126'}
e.update(rd._build_mode_env(get_regime_params('boost')))
print(f"[표본] 수정주가+페널티(W0.3 K126) boost 20260601~20260617...", flush=True)
t0 = time.time()
r = subprocess.run([PY, '-u', FG, '20260601', '20260617', f'--state-dir={SD}'], env=e,
                   stdout=open('_sample_pen.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
print(f"FG rc={r.returncode} {time.time()-t0:.0f}s", flush=True)
J = json.load(open(f'{SD}/ranking_20260617.json', encoding='utf-8'))['rankings']
J = sorted(J, key=lambda x: x.get('composite_rank', 999))
print("\n=== 수정주가+페널티 6/17 boost 상위 12 ===")
for x in J[:12]:
    rc = ' 🚨최근CA감점' if x.get('recent_ca') else ''
    mk = ' ★디바이스' if x['ticker'] == '187870' else ''
    print(f"  cr{x.get('composite_rank'):>3} {x['ticker']} {x.get('name',''):<8} score={x.get('score'):.3f}{mk}{rc}")
dv = [x for x in J if x['ticker'] == '187870']
if dv:
    print(f"\n디바이스: cr={dv[0].get('composite_rank')} score={dv[0].get('score'):.3f} recent_ca={dv[0].get('recent_ca',0)}")
npen = sum(1 for x in J if x.get('recent_ca'))
print(f"페널티 발동 종목 수(6/17): {npen}")
print("페널티 발동 상위:", [f"{x['ticker']}({x.get('composite_rank')})" for x in J if x.get('recent_ca')][:10])
