"""종목명 캐시 전체 갱신 — 월 1회 (Windows Task Scheduler에서 호출)

이름 변경/합병 반영. 프로덕션 파이프라인과 별도 실행.
스케줄: 매월 첫째 일요일 밤 (예: 22:00)

Usage:
    python refresh_ticker_names.py
"""
import sys
import json
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

from pykrx import stock as pykrx_stock
import pandas as pd
import krx_auth
krx_auth.login()

CACHE_DIR = Path(__file__).parent / 'data_cache'
NAMES_PATH = CACHE_DIR / 'ticker_names_cache.json'


def main():
    mcap_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
    if not mcap_files:
        print('market_cap 캐시 없음')
        return

    mcap = pd.read_parquet(mcap_files[-1])
    print(f'대상: {len(mcap)}종목')

    names = {}
    for i, ticker in enumerate(mcap.index):
        try:
            name = pykrx_stock.get_market_ticker_name(ticker)
            if name:
                names[ticker] = name
            time.sleep(1)
        except Exception:
            pass
        if (i + 1) % 500 == 0:
            print(f'  {i+1}/{len(mcap)} 완료')

    with open(NAMES_PATH, 'w', encoding='utf-8') as f:
        json.dump(names, f, ensure_ascii=False)
    print(f'종목명 캐시 갱신 완료: {len(names)}개 → {NAMES_PATH.name}')


if __name__ == '__main__':
    main()
