# -*- coding: utf-8 -*-
"""자율주행: 7.4년 regen 모니터 → 슬롯 비면 큐 청크 투입(메모리 가드) →
10분마다 개인봇 보고 → 완료 시 _sp_final.py 자동실행 → 결과 봇 전송. 청크 실패 시 자가복구."""
import subprocess, time, glob, os, sys
sys.path.insert(0, r'C:\dev')
import psutil, requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
PY = "C:/Users/user/miniconda3/python.exe"
BENV = dict(FACTOR_V_W='0.15', FACTOR_Q_W='0.0', FACTOR_G_W='0.55', FACTOR_M_W='0.3',
    G_REVENUE_WEIGHT='0.5', MOM_PERIOD='12m', G_SUB1='rev_z', G_SUB2='oca_z', G_SUB3='gp_growth_z',
    G_W1='0.4', G_W2='0.4', G_W3='0.2', FACTOR_MOM_10_W='0.05', FACTOR_VOL_LOW_W='0.06',
    FACTOR_OVERHEAT_W='0.2', G_QOQ_PENALTY='D6', G_QOQ_PENALTY_THRESHOLD='20',
    G_QOQ_PENALTY_MULTIPLIER='0.7', G_QOQ_SG6_THRESH='0.06')
def send(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
    except Exception: pass
def launch(sp, sr, lo, hi, folder):
    env = dict(os.environ, **BENV, USE_SELF_PER=sp, USE_SELF_ROE=sr)
    return subprocess.Popen([PY, 'backtest/fast_generate_rankings_v2.py', lo, hi, '--state-dir', folder],
        cwd=r'C:\dev', env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def fg_count():
    n = 0
    for p in psutil.process_iter(['name', 'memory_info']):
        try:
            if p.info['name'] == 'python.exe' and p.info['memory_info'].rss > 1.5e9: n += 1
        except Exception: pass
    return n
def cnt(f): return len(glob.glob(rf'C:\dev\{f}\ranking_*.json'))
def freegb(): return psutil.virtual_memory().available / 1e9

queue = [('0', '0', '20190102', '20221231', '_sp0')]  # 4번째(큐): _sp0 2019-2022
t0 = time.time(); last_report = 0
last_counts = (0, 0); stable_since = None; relaunch = 0; seen_full = False
send('🤖 자율주행 시작 — 7.4년 regen 3스트림+큐1. 10분마다 보고, 완료 시 _sp_final 자동실행.')
while True:
    fg = fg_count(); s0, s2 = cnt('_sp0'), cnt('_sp2'); fr = freegb()
    if fg >= 3: seen_full = True   # 3개 다 프리로드 완료 확인 후에만 큐 투입 (조기투입 OOM 방지)
    # 큐 투입 (3개 떠서 1개 끝난 뒤 + 메모리 3GB+ 여유)
    if queue and seen_full and fg < 3 and fr > 3.0:
        sp, sr, lo, hi, fol = queue.pop(0)
        launch(sp, sr, lo, hi, fol)
        send(f'➕ 슬롯 비어 큐 투입: {fol} {lo}~{hi} (FG {fg}→{fg+1})')
        time.sleep(15); continue
    # 10분 보고
    if time.time() - last_report >= 600:
        send(f'⏳ {int((time.time()-t0)/60)}분 경과 | _sp0 {s0} / _sp2 {s2} | FG {fg}개 | 메모리 {fr:.1f}GB여유 | 큐 {len(queue)}')
        last_report = time.time()
    # 안정성 추적 (생성 멈춤 감지)
    if (s0, s2) == last_counts:
        if stable_since is None: stable_since = time.time()
    else:
        stable_since = None; last_counts = (s0, s2)
    # 완료/자가복구 판정 (FG 0 + 큐 빔 + 60초 카운트 불변)
    if not queue and fg == 0 and stable_since and time.time() - stable_since > 60:
        if abs(s0 - s2) < 25 and s0 > 1500:
            send(f'✅ regen 완료 _sp0 {s0} _sp2 {s2} → _sp_final.py 실행 (~10-20분)')
            try:
                out = subprocess.run([PY, 'backtest/_sp_final.py'], cwd=r'C:\dev',
                    capture_output=True, text=True, encoding='utf-8', timeout=3600)
                res = (out.stdout or '')[-3200:] + (('\n[STDERR]' + out.stderr[-500:]) if out.stderr else '')
                send(f'🏁 최종 판정 (7.4년):\n<pre>{res}</pre>')
            except Exception as e:
                send(f'🔴 _sp_final 실행 오류: {e}')
            break
        elif relaunch < 3:
            relaunch += 1
            send(f'⚠️ 갭 감지 (_sp0 {s0} _sp2 {s2}, 차이 {abs(s0-s2)}) → 풀범위 재실행 {relaunch}/3')
            launch('0', '0', '20190102', '20250531', '_sp0')
            launch('1', '1', '20190102', '20250531', '_sp2')
            stable_since = None; time.sleep(15)
        else:
            send(f'🔴 3회 재실행 후도 미완 (_sp0 {s0} _sp2 {s2}) — 수동 점검 필요'); break
    time.sleep(30)
send('🤖 자율주행 종료.')
