# -*- coding: utf-8 -*-
"""표본검증: V_all 신호로 최근 구간 boost 재생성 → 디바이스 6/17 순위 확인.
FG 오버라이드(OHLCV_FILE) + CORPACTION_ADJ_DISABLE=1(이미 수정주가라 자작보정 OFF) 정상작동 확인."""
import sys, os, io, glob, subprocess, json, time
sys.path.insert(0, r'C:\dev'); os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from regime_indicator import get_regime_params
import run_daily as rd

PY = sys.executable; FG = 'backtest/fast_generate_rankings_v2.py'
VALL = sorted(glob.glob('C:/dev/data_cache/all_ohlcv_adj_*.parquet'))[-1]
LO, HI = '20260601', '20260617'
SD = '_sample_vall'
os.makedirs(SD, exist_ok=True)
e = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'OHLCV_FILE': VALL, 'CORPACTION_ADJ_DISABLE': '1'}
e.update(rd._build_mode_env(get_regime_params('boost')))
print(f"[표본] V_all={os.path.basename(VALL)} boost {LO}~{HI} 재생성...", flush=True)
t0 = time.time()
r = subprocess.run([PY, '-u', FG, LO, HI, f'--state-dir={SD}'], env=e,
                   stdout=open('_sample_vall.log', 'w', encoding='utf-8'), stderr=subprocess.STDOUT)
print(f"FG rc={r.returncode} {time.time()-t0:.0f}s", flush=True)

f = f'{SD}/ranking_20260617.json'
if not os.path.exists(f):
    print("[FAIL] 6/17 ranking 없음. 로그 확인:")
    print(open('_sample_vall.log', encoding='utf-8').read()[-2000:])
    sys.exit(1)
J = json.load(open(f, encoding='utf-8'))['rankings']
J = sorted(J, key=lambda x: x.get('composite_rank', 999))
print(f"\n=== V_all 6/17 boost 상위 10 (composite_rank) ===")
for x in J[:10]:
    tk = x['ticker']; nm = x.get('name', '')
    mark = ' ★디바이스' if tk == '187870' else ''
    print(f"  cr{x.get('composite_rank'):>3} {tk} {nm:<8} score={x.get('score'):.3f} mom_z={x.get('mom_z') or x.get('momentum_z') or 0:.2f}{mark}")
dv = [x for x in J if x['ticker'] == '187870']
if dv:
    d = dv[0]
    print(f"\n디바이스 cr={d.get('composite_rank')} score={d.get('score'):.3f}")
    print(f"  팩터: " + ", ".join(f"{k}={v:.3f}" for k, v in d.items() if isinstance(v, (int, float)) and k not in ('composite_rank',))[:400])
else:
    print("\n디바이스 6/17 랭킹에 없음 (필터 탈락?) — 로그 확인 필요")
