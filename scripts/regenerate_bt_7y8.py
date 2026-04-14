"""Phase 3: 2018-07-02 ~ 2026-04-14 전체 FG BT 재생성

- state/bt_7y8/ 디렉토리 (boost), state/bt_7y8/defense/ (defense)
- v77.1 params 적용 (필터 d', e 포함)
- boost + defense 병렬 subprocess
- 완료 시 개인봇 알림
"""
import os, sys, time, subprocess, requests
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent.parent
FG = PROJECT / 'backtest' / 'fast_generate_rankings_v2.py'
LOG_DIR = PROJECT / 'logs'
LOG_DIR.mkdir(exist_ok=True)

START, END = '20180702', '20260414'
OUT_BOOST = PROJECT / 'state' / 'bt_7y8'
OUT_DEFENSE = PROJECT / 'state' / 'bt_7y8' / 'defense'
OUT_BOOST.mkdir(parents=True, exist_ok=True)
OUT_DEFENSE.mkdir(parents=True, exist_ok=True)


def send_tg(msg):
    try:
        sys.path.insert(0, str(PROJECT))
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
        requests.post(url, data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=30)
    except Exception:
        pass


BOOST_ENV = {
    'FACTOR_V_W': '0.05', 'FACTOR_Q_W': '0.00', 'FACTOR_G_W': '0.65', 'FACTOR_M_W': '0.30',
    'G_REVENUE_WEIGHT': '0.0', 'MOM_PERIOD': '12m-1m',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_SUB3': 'gp_growth_z',
    'G_W1': '0.5', 'G_W2': '0.3', 'G_W3': '0.2',
}
DEFENSE_ENV = {
    'FACTOR_V_W': '0.30', 'FACTOR_Q_W': '0.05', 'FACTOR_G_W': '0.10', 'FACTOR_M_W': '0.55',
    'G_REVENUE_WEIGHT': '0.5', 'MOM_PERIOD': '6m-1m',
    'G_SUB1': 'rev_accel_z', 'G_SUB2': 'op_margin_z',
}

print(f'=== Phase 3 BT 재생성 시작: {START}~{END} ===')
send_tg(f'[Phase 3] BT 7.8년 재생성 시작 (약 32분)')
t0 = time.time()

base_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
boost_env = {**base_env, **BOOST_ENV}
def_env = {**base_env, **DEFENSE_ENV}
boost_cmd = [sys.executable, '-u', str(FG), START, END, f'--state-dir={OUT_BOOST}']
def_cmd = [sys.executable, '-u', str(FG), START, END, f'--state-dir={OUT_DEFENSE}']

with open(LOG_DIR / 'phase3_bt_boost.log', 'w', encoding='utf-8') as fb, \
     open(LOG_DIR / 'phase3_bt_defense.log', 'w', encoding='utf-8') as fd:
    pb = subprocess.Popen(boost_cmd, cwd=str(PROJECT), stdout=fb, stderr=subprocess.STDOUT,
                          env=boost_env, text=True, encoding='utf-8', errors='replace')
    pd = subprocess.Popen(def_cmd, cwd=str(PROJECT), stdout=fd, stderr=subprocess.STDOUT,
                          env=def_env, text=True, encoding='utf-8', errors='replace')
    rb = pb.wait()
    rd = pd.wait()

elapsed = (time.time() - t0) / 60
msg = f'[Phase 3] BT 재생성 완료 ({elapsed:.1f}분)\nboost: {rb}, defense: {rd}'
print(msg)
send_tg(msg)
sys.exit(0 if rb == 0 and rd == 0 else 1)
