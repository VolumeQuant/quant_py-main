# -*- coding: utf-8 -*-
"""KR EPS 데이터 누락 모니터링 (5/14 PoC 17일 멈춤 사고 재발 방지)

5/14 사고: PoC 시작 후 Task Scheduler 등록 누락 → 17일 데이터 0건 → 누구도 모름.
해결: GHA cron으로 자동화 + 이 monitor로 누락 감지.

실행:
  python kr_eps_momentum/research/data_monitor.py [--days 5]

흐름:
1. DB에서 최근 N일 데이터 존재 확인
2. 거래일 기준 누락 감지
3. 누락 시 개인봇 알림
"""
import argparse, sqlite3, sys, os, requests
from pathlib import Path
from datetime import date, timedelta
sys.stdout.reconfigure(encoding='utf-8')

DB = Path(__file__).resolve().parent.parent / 'eps_momentum_data_kr.db'


def kr_business_days(d, n_back):
    """d로부터 n_back 거래일 (주말/공휴일 skip)"""
    try:
        import holidays
        kr = holidays.country_holidays('KR', years=[d.year, d.year - 1])
    except ImportError:
        kr = set()
    days = []
    cur = d
    while len(days) < n_back:
        if cur.weekday() < 5 and cur not in kr:
            days.append(cur)
        cur -= timedelta(days=1)
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=5, help='검사 일수 (기본 5거래일)')
    ap.add_argument('--alert', action='store_true', help='누락 시 개인봇 알림')
    args = ap.parse_args()
    if not DB.exists():
        msg = f'⚠️ KR EPS DB 자체 없음: {DB}'
        print(msg)
        if args.alert:
            _send(msg)
        return 1
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        db_dates = set(r[0] for r in c.execute(
            'SELECT DISTINCT date FROM ntm_screening'
        ).fetchall())
    except sqlite3.OperationalError:
        msg = '⚠️ ntm_screening 테이블 없음 (DB 초기화 X)'
        print(msg)
        if args.alert: _send(msg)
        return 1
    expected = kr_business_days(date.today(), args.days)
    missing = [d.strftime('%Y-%m-%d') for d in expected if d.strftime('%Y-%m-%d') not in db_dates]
    print(f'=== KR EPS 데이터 누락 검사 ===')
    print(f'대상: 최근 {args.days} 거래일')
    print(f'DB 보유: {len(db_dates)} 일')
    print(f'누락: {len(missing)}/{args.days}')
    for m in missing: print(f'  - {m}')
    if missing:
        msg = f'⚠️ KR EPS 데이터 누락 {len(missing)}/{args.days}일\n누락일: {", ".join(missing)}'
        if args.alert:
            _send(msg)
        conn.close()
        return 1
    print('✓ 누락 없음')
    conn.close()
    return 0


def _send(msg):
    tok = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    pid = os.environ.get('TELEGRAM_PRIVATE_ID', '')
    if not tok or not pid:
        # local fallback
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
        try:
            from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
            tok, pid = TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        except Exception: pass
    if tok and pid:
        try:
            r = requests.post(f'https://api.telegram.org/bot{tok}/sendMessage',
                              data={'chat_id': pid, 'text': msg}, timeout=15)
            print(f'개인봇 알림: {r.status_code}')
        except Exception as e:
            print(f'알림 실패: {e}')


if __name__ == '__main__':
    sys.exit(main())
