"""장 마감 후 데이터 가용 시점 테스트
15:30 장 마감 후 몇 시부터 당일 데이터가 나오는지 확인

사용법: 장 마감 후 수동 실행
  python backtest/test_data_availability.py

또는 자동 반복 (15:30~17:00 사이 5분 간격):
  python backtest/test_data_availability.py --loop
"""
import sys, time
from datetime import datetime
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'c:/dev')

KST = ZoneInfo('Asia/Seoul')

def check_all():
    now = datetime.now(KST).strftime('%H:%M:%S')
    today = datetime.now(KST).strftime('%Y%m%d')
    print(f'\n[{now}] 데이터 가용성 체크 (기준일: {today})')
    print('-' * 50)

    import krx_auth
    krx_auth.login()
    from pykrx import stock
    import pandas as pd

    results = {}

    # 1. 삼성전자 OHLCV (당일)
    try:
        df = stock.get_market_ohlcv(today, today, '005930')
        if not df.empty:
            close = df.iloc[-1]['종가'] if '종가' in df.columns else df.iloc[-1, 3]
            results['OHLCV(삼성전자)'] = f'OK (종가: {int(close):,}원)'
        else:
            results['OHLCV(삼성전자)'] = 'EMPTY'
    except Exception as e:
        results['OHLCV(삼성전자)'] = f'ERROR: {e}'

    time.sleep(1)

    # 2. 전종목 시가총액 (당일)
    try:
        df = stock.get_market_cap(today, market='ALL')
        if not df.empty:
            results['시가총액(ALL)'] = f'OK ({len(df)}종목)'
        else:
            results['시가총액(ALL)'] = 'EMPTY'
    except Exception as e:
        results['시가총액(ALL)'] = f'ERROR: {e}'

    time.sleep(1)

    # 3. 전종목 PER/PBR (당일)
    try:
        df = stock.get_market_fundamental(today, market='ALL')
        if not df.empty:
            results['펀더멘털(ALL)'] = f'OK ({len(df)}종목)'
        else:
            results['펀더멘털(ALL)'] = 'EMPTY'
    except Exception as e:
        results['펀더멘털(ALL)'] = f'ERROR: {e}'

    time.sleep(1)

    # 4. 전종목 OHLCV (벌크)
    try:
        df = stock.get_market_ohlcv_by_ticker(today, market='ALL')
        if not df.empty:
            results['OHLCV벌크(ALL)'] = f'OK ({len(df)}종목)'
        else:
            results['OHLCV벌크(ALL)'] = 'EMPTY'
    except Exception as e:
        results['OHLCV벌크(ALL)'] = f'ERROR: {e}'

    time.sleep(1)

    # 5. KOSPI 인덱스
    try:
        df = stock.get_index_ohlcv(today, today, '1001')
        if not df.empty:
            close = df.iloc[-1, 3]
            results['KOSPI인덱스'] = f'OK (종가: {close:,.0f})'
        else:
            results['KOSPI인덱스'] = 'EMPTY'
    except Exception as e:
        results['KOSPI인덱스'] = f'ERROR: {e}'

    # 결과 출력
    all_ok = True
    for k, v in results.items():
        status = 'O' if v.startswith('OK') else 'X'
        if status == 'X':
            all_ok = False
        print(f'  [{status}] {k}: {v}')

    if all_ok:
        print(f'\n  >>> 모든 데이터 가용! 파이프라인 실행 가능 <<<')
        # 개인봇에만 알림
        try:
            sys.path.insert(0, 'c:/dev')
            import requests
            from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
            msg = f'[데이터 가용 확인] {now}\n모든 데이터 OK — 파이프라인 실행 가능\n\n'
            for k, v in results.items():
                msg += f'{k}: {v}\n'
            requests.post(
                f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=10)
        except Exception:
            pass
    return all_ok


if __name__ == '__main__':
    if '--loop' in sys.argv:
        print('자동 반복 모드 (5분 간격, Ctrl+C로 중단)')
        attempt = 0
        while True:
            attempt += 1
            done = check_all()
            if done:
                print('\n데이터 가용 확인 완료!')
                break
            # 매 체크마다 개인봇에 진행 알림 (첫 번째와 이후 3회마다)
            if attempt == 1 or attempt % 3 == 0:
                try:
                    now = datetime.now(KST).strftime('%H:%M')
                    import requests
                    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
                    requests.post(
                        f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                        data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': f'[데이터 체크 #{attempt}] {now} — 아직 미가용'}, timeout=10)
                except Exception:
                    pass
            print(f'\n다음 체크: 5분 후...')
            time.sleep(300)
    else:
        check_all()
