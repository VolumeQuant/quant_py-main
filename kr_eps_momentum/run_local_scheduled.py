# -*- coding: utf-8 -*-
"""KR EPS 로컬 스케줄 러너 — GitHub Actions cron 대체 (GA가 3.5~5.5h 지연 → 저녁 실행 문제).
production QuanT_DailyPipeline(16:00)처럼 로컬 Task Scheduler에서 16:30 KST 호출(production push 후 stagger).

GA(kr_eps_daily.yml) 동작 그대로 미러:
  휴장일/주말 skip → config.py(gitignore)에서 토큰 주입 → DB 백업 → daily_runner.py 실행
  → config_kr.json 복원(토큰 커밋 방지) → DB/캐시 commit + push.
텔레그램은 개인봇(private)만 — GA와 동일(채널 전송 안 함, 참고용).
"""
import json, os, sys, glob, time, shutil, subprocess
from datetime import datetime, timezone, timedelta

ROOT = r'C:\dev'
KRD = os.path.join(ROOT, 'kr_eps_momentum')
CFG = os.path.join(KRD, 'config_kr.json')
DB = os.path.join(KRD, 'eps_momentum_data_kr.db')
PY = sys.executable


def log(m):
    print(f'[kr-eps-local {datetime.now():%H:%M:%S}] {m}', flush=True)


def main():
    # 1. 휴장일/주말 skip (KST 기준)
    today = (datetime.now(timezone.utc) + timedelta(hours=9)).date()
    try:
        import holidays
        kr = holidays.country_holidays('KR', years=[today.year])
        if today.weekday() >= 5 or today in kr:
            log(f'SKIP 휴장일/주말: {today} (weekday={today.weekday()}, holiday={today in kr})')
            return
    except ImportError:
        if today.weekday() >= 5:
            log(f'SKIP 주말: {today}')
            return
    log(f'영업일(KST): {today}')

    # 2. config.py(gitignore)에서 토큰 → config_kr.json 주입 (GA secret 주입과 동일)
    sys.path.insert(0, ROOT)
    import config as C
    cfg = json.load(open(CFG, encoding='utf-8'))
    cfg['telegram_enabled'] = True
    cfg['telegram_bot_token'] = getattr(C, 'TELEGRAM_BOT_TOKEN', '') or ''
    cfg['telegram_private_id'] = getattr(C, 'TELEGRAM_PRIVATE_ID', '') or ''
    cfg['telegram_chat_id'] = ''       # 채널/그룹 전송 안 함 (참고용 개인봇만 — GA와 동일)
    cfg['telegram_channel_id'] = ''
    cfg['gemini_api_key'] = getattr(C, 'GEMINI_API_KEY', '') or ''
    cfg['git_enabled'] = False         # git은 이 스크립트가 직접 처리
    json.dump(cfg, open(CFG, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    log('config_kr.json 토큰 주입 (개인봇 전용)')

    # 3. DB 백업
    if os.path.exists(DB):
        shutil.copy2(DB, f'{DB}.bak_{today:%Y%m%d}')
        log(f'DB 백업: eps_momentum_data_kr.db.bak_{today:%Y%m%d}')

    # 4. 실행 (+ 끝나면 config_kr.json 복원해 토큰 제거)
    try:
        r = subprocess.run([PY, 'daily_runner.py'], cwd=KRD)
        log(f'daily_runner.py 종료코드 {r.returncode}')
    finally:
        subprocess.run(['git', '-C', ROOT, 'checkout', '--', 'kr_eps_momentum/config_kr.json'])
        log('config_kr.json 복원(토큰 제거)')

    # 5. 7일 이상 백업 삭제
    for f in glob.glob(f'{DB}.bak_*'):
        if os.path.getmtime(f) < time.time() - 7 * 86400:
            try:
                os.remove(f)
            except OSError:
                pass

    # 6. commit + push (DB + 백업 + 캐시 — config_kr.json은 제외=토큰 안 올라감)
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
