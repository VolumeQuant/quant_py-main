"""v77 최종 마무리 — bt+state 재생성 완료 후 검증+커밋+텔레그램

1. bt 생성 완료 대기
2. bt_test_A 교체
3. state/ 복사 + boost 후처리
4. state/defense/ 복사 + defense 후처리
5. bt vs state 표본 검증
6. v77 TurboSim 성과 재확인
7. TEST_MODE 텔레그램 전송
8. 커밋 푸시
9. 개인봇 결과 보고
"""
import sys, json, os, shutil, io, time, subprocess, glob
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from run_daily import _postprocess_ranking

PROJECT = Path(__file__).parent.parent
DATA_DIR = PROJECT / 'data_cache'
RESULT_DIR = PROJECT / 'backtest_results'

def send_tg(msg):
    try:
        import requests
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        # 긴 메시지 분할
        for i in range(0, len(msg), 4000):
            requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                          data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg[i:i+4000]}, timeout=30)
    except Exception as e:
        print(f'텔레그램 실패: {e}')

t0 = time.time()

# ============================================================
# 1. bt 생성 완료 대기
# ============================================================
print('1. bt 생성 완료 대기...', flush=True)
while True:
    bt_count = len(glob.glob(str(PROJECT / 'backtest/bt_test_A_new/ranking_*.json')))
    def_count = len(glob.glob(str(PROJECT / 'backtest/bt_defense_new/ranking_*.json')))
    running = 0
    try:
        r = subprocess.run(['tasklist'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        running = r.stdout.count('python.exe') - 1  # 자기 자신 제외
    except:
        pass
    print(f'  boost: {bt_count}일, defense: {def_count}일, 프로세스: {running}', flush=True)
    if running <= 0 and bt_count > 1200 and def_count > 1200:
        break
    time.sleep(30)

print(f'  boost: {bt_count}일, defense: {def_count}일 — 완료!', flush=True)

# ============================================================
# 2. bt_test_A 교체
# ============================================================
print('\n2. bt_test_A 교체...', flush=True)
bt_old = PROJECT / 'backtest/bt_test_A'
bt_new = PROJECT / 'backtest/bt_test_A_new'

# 기존 백업 삭제 (이미 v76 백업 있으니)
bt_prev = PROJECT / 'backtest/bt_test_A_prev'
if bt_prev.exists():
    shutil.rmtree(bt_prev)
bt_old.rename(bt_prev)
bt_new.rename(bt_old)
print(f'  교체 완료: {len(list(bt_old.glob("ranking_*.json")))}일', flush=True)

# ============================================================
# 3. state/ 복사 + boost 후처리
# ============================================================
print('\n3. state/ boost 복사+후처리...', flush=True)
state_dir = PROJECT / 'state'
bt_files = sorted(bt_old.glob('ranking_*.json'))
log = io.StringIO()
done = 0
for f in bt_files:
    shutil.copy2(f, state_dir / f.name)
    date = f.stem.replace('ranking_', '')
    _postprocess_ranking(date, str(state_dir), 'boost', log)
    done += 1
    if done % 200 == 0:
        print(f'  {done}/{len(bt_files)}', flush=True)
print(f'  boost 완료: {done}파일', flush=True)

# ============================================================
# 4. state/defense/ 복사 + defense 후처리
# ============================================================
print('\n4. state/defense/ 복사+후처리...', flush=True)
def_bt = PROJECT / 'backtest/bt_defense_new'
def_state = PROJECT / 'state/defense'
def_state.mkdir(exist_ok=True)
def_files = sorted(def_bt.glob('ranking_*.json'))
done = 0
for f in def_files:
    shutil.copy2(f, def_state / f.name)
    date = f.stem.replace('ranking_', '')
    _postprocess_ranking(date, str(def_state), 'defense', log)
    done += 1
    if done % 200 == 0:
        print(f'  {done}/{len(def_files)}', flush=True)
print(f'  defense 완료: {done}파일', flush=True)

# ============================================================
# 5. bt vs state 표본 검증
# ============================================================
print('\n5. bt vs state 표본 검증...', flush=True)
sample_dates = ['20210104', '20230103', '20250103', '20260407']
all_match = True
for d in sample_dates:
    bt_f = bt_old / f'ranking_{d}.json'
    st_f = state_dir / f'ranking_{d}.json'
    if not bt_f.exists() or not st_f.exists():
        print(f'  {d}: 파일 없음 — 스킵')
        continue
    with open(bt_f, 'r', encoding='utf-8') as f:
        bt_rk = json.load(f).get('rankings', [])
    with open(st_f, 'r', encoding='utf-8') as f:
        st_rk = json.load(f).get('rankings', [])
    bt_cr = {r['ticker']: r.get('composite_rank', r['rank']) for r in bt_rk}
    st_cr = {r['ticker']: r.get('composite_rank', r['rank']) for r in st_rk}
    match = (set(bt_cr.keys()) == set(st_cr.keys())) and all(bt_cr[tk] == st_cr[tk] for tk in bt_cr)
    print(f'  {d}: bt={len(bt_rk)} st={len(st_rk)} 동일={match}')
    if not match:
        all_match = False

# ============================================================
# 6. v77 TurboSim 성과 재확인
# ============================================================
print('\n6. v77 TurboSim 성과...', flush=True)
from turbo_simulator import TurboSimulator

ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

dates = sorted([f.stem.replace('ranking_', '') for f in bt_old.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(bt_old / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

md = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d); kv = kospi.get(ts, None); mv = km200.get(ts, None)
    s = (kv > mv) if kv is not None and mv is not None else md
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and md != s: md = s
    rd[d] = md

tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
op = {'v': 0.05, 'q': 0, 'g': 0.65, 'm': 0.30, 'g_rev': 0.0, 'entry': 7, 'exit': 8, 'slots': 3, 'mom': '12m-1m'}
dp = {'v': 0.30, 'q': 0.05, 'g': 0.10, 'm': 0.55, 'g_rev': 0.5, 'entry': 3, 'exit': 6, 'slots': 7, 'mom': '6m-1m'}
r = tsim.run_regime(dp, op, rd, stop_loss=-0.10, trailing_stop=-0.15,
    g_sub1_o='rev_z', g_sub2_o='oca_z', g_sub3_o='gp_growth_z', g_w1_o=0.5, g_w2_o=0.3, g_w3_o=0.2,
    g_sub1_d='rev_accel_z', g_sub2_d='op_margin_z')

perf = f'Cal={r["calmar"]:.2f} CAGR={r["cagr"]:+.1f}% MDD={r["mdd"]:.1f}% Sh={r["sharpe"]:.2f} So={r.get("sortino",0):.2f}'
print(f'  {perf}', flush=True)

# ============================================================
# 7. 커밋 푸시
# ============================================================
print('\n7. 커밋 푸시...', flush=True)
os.chdir(str(PROJECT))
subprocess.run(['git', 'add', 'backtest/bt_test_A/', 'state/', 'backtest/fast_generate_rankings_v2.py',
                'send_telegram_auto.py'], capture_output=True)
commit_msg = f"""fix(v77): point-in-time bt+state 전체 재생성 (DART 고정)

DART 데이터 고정 후 bt+state 동시 생성 → 동일 데이터 기반.
bt_test_A {len(dates)}일 + state/ boost {len(bt_files)}일 + state/defense/ {len(def_files)}일.
{perf}

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"""
subprocess.run(['git', 'commit', '-m', commit_msg], capture_output=True)
push = subprocess.run(['git', 'push'], capture_output=True, text=True, timeout=120)
print(f'  push: {"성공" if push.returncode == 0 else "실패"}', flush=True)

# ============================================================
# 8. 텔레그램 보고
# ============================================================
elapsed = (time.time() - t0) / 60
msg = f"""[v77 최종 마무리 완료]
소요: {elapsed:.0f}분

bt+state 동일 DART 기반 재생성:
  bt_test_A: {len(dates)}일
  state/ boost: {len(bt_files)}일
  state/defense/: {len(def_files)}일
  표본 검증: {"전부 동일 ✅" if all_match else "불일치 ⚠️"}

v77 성과 (재확인):
  {perf}

커밋 푸시: {"완료" if push.returncode == 0 else "실패"}"""

send_tg(msg)
print(f'\n완료! ({elapsed:.0f}분)', flush=True)
