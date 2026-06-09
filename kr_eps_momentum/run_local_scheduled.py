# -*- coding: utf-8 -*-
"""KR EPS 로컬 스케줄 러너 — GitHub Actions cron 대체(GA 3.5~5.5h 지연 문제).
production QuanT_DailyPipeline처럼 로컬 Task Scheduler 16:30 KST 호출.

개인봇 전용 보장 (3중):
  ① TELEGRAM_PRIVATE_ID만 env로 넘김 → daily_runner가 chat_id=private로 라우팅
  ② TELEGRAM_CHAT_ID env 미설정 → channel_id='' → 채널 전송 안 함
  ③ GITHUB_ACTIONS env 미설정 → is_github_actions=False → send_to_channel 구조적 불가
토큰은 config.py(gitignore)에서 env로만 전달 → config_kr.json(추적파일) 안 건드림(유출 0).
"""
import os, sys, glob, time, shutil, subprocess
from datetime import datetime, timezone, timedelta

ROOT = r'C:\dev'
KRD = os.path.join(ROOT, 'kr_eps_momentum')
DB = os.path.join(KRD, 'eps_momentum_data_kr.db')
PY = sys.executable


def log(m):
    print(f'[kr-eps-local {datetime.now():%H:%M:%S}] {m}', flush=True)


def main():
    # 1. 휴장일/주말 skip (KST)
    today = (datetime.now(timezone.utc) + timedelta(hours=9)).date()
    try:
        import holidays
        if today.weekday() >= 5 or today in holidays.country_holidays('KR', years=[today.year]):
            log(f'SKIP 휴장일/주말: {today}'); return
    except ImportError:
        if today.weekday() >= 5:
            log(f'SKIP 주말: {today}'); return
    log(f'영업일(KST): {today}')

    # 2. 토큰을 env로만 전달 (config_kr.json 안 건드림). 채널 관련 env는 명시적 제거.
    sys.path.insert(0, ROOT)
    import config as C
    env = dict(os.environ)
    env['TELEGRAM_BOT_TOKEN'] = getattr(C, 'TELEGRAM_BOT_TOKEN', '') or ''
    env['TELEGRAM_PRIVATE_ID'] = getattr(C, 'TELEGRAM_PRIVATE_ID', '') or ''
    env['GEMINI_API_KEY'] = getattr(C, 'GEMINI_API_KEY', '') or ''
    env.pop('TELEGRAM_CHAT_ID', None)   # 채널 전송 방지
    env.pop('GITHUB_ACTIONS', None)     # is_github_actions=False
    env['PYTHONIOENCODING'] = 'utf-8'
    log('env 설정: 개인봇 전용 (TELEGRAM_CHAT_ID/GITHUB_ACTIONS 미설정)')

    # 3. DB 백업
    if os.path.exists(DB):
        shutil.copy2(DB, f'{DB}.bak_{today:%Y%m%d}')
        log(f'DB 백업: bak_{today:%Y%m%d}')

    # 4. 실행
    r = subprocess.run([PY, 'daily_runner.py'], cwd=KRD, env=env)
    log(f'daily_runner.py 종료코드 {r.returncode}')

    # 5. 7일+ 백업 삭제
    for f in glob.glob(f'{DB}.bak_*'):
        if os.path.getmtime(f) < time.time() - 7 * 86400:
            try:
                os.remove(f)
            except OSError:
                pass

    # 6. commit + push (config_kr.json 제외 = 토큰 안 올라감)
    subprocess.run(['git', '-C', ROOT, 'add',
                    'kr_eps_momentum/eps_momentum_data_kr.db',
                    'yf_eps_workspace/data_cache_yf/',
                    'kr_eps_momentum/ticker_info_cache.json'])
    subprocess.run('git -C "{}" add kr_eps_momentum/eps_momentum_data_kr.db.bak_*'.format(ROOT), shell=True)
    if subprocess.run(['git', '-C', ROOT, 'diff', '--staged', '--quiet']).returncode != 0:
        subprocess.run(['git', '-C', ROOT, 'commit', '-m', f'KR EPS daily {today:%Y-%m-%d} (+backup, local)'])
        subprocess.run(['git', '-C', ROOT, 'pull', '--no-rebase', '-X', 'ours', 'origin', 'main'])
        p = subprocess.run(['git', '-C', ROOT, 'push'])
        log(f'commit+push {"성공" if p.returncode == 0 else "실패(다음날 재시도)"}')
    else:
        log('변경 없음 — commit 스킵')


if __name__ == '__main__':
    main()
