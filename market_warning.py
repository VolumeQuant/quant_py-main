"""시장조치 종목 필터 - 네이버 금융 기반

투자주의/투자경고/투자위험/매매정지/관리종목/불성실공시/환기종목
해당 종목을 프로덕션 ranking에서 제외.

Usage:
    from market_warning import filter_warned_stocks
    clean_rankings = filter_warned_stocks(rankings, top_n=30)
"""

import requests
import time


WARN_KEYWORDS = ['투자주의', '투자경고', '투자위험', '매매거래정지',
                 '관리종목', '불성실공시', '환기종목']


def check_warning_naver(ticker):
    """네이버 금융에서 시장조치 여부 확인.

    Returns: list of warning keywords, or empty list
    """
    url = f'https://finance.naver.com/item/main.naver?code={ticker}'
    try:
        r = requests.get(url, timeout=10,
                         headers={'User-Agent': 'Mozilla/5.0'})
        warnings = [kw for kw in WARN_KEYWORDS if kw in r.text]
        return warnings
    except Exception:
        return []


def filter_warned_stocks(rankings, top_n=30):
    """ranking 리스트에서 시장조치 종목 제거.

    상위 top_n 종목만 체크 (API 호출 최소화).

    Args:
        rankings: list of ranking dicts (ticker, name, ...)
        top_n: 상위 몇 종목까지 체크할지

    Returns:
        (filtered_rankings, warned_tickers)
        - filtered_rankings: 시장조치 종목 제거된 리스트
        - warned_tickers: {ticker: [warnings]} dict
    """
    warned = {}
    check_tickers = set()

    # 상위 top_n 종목만 체크
    sorted_r = sorted(rankings, key=lambda x: x.get('composite_rank', x.get('rank', 999)))
    for r in sorted_r[:top_n]:
        check_tickers.add(r['ticker'])

    for ticker in check_tickers:
        warnings = check_warning_naver(ticker)
        if warnings:
            warned[ticker] = warnings
        time.sleep(0.3)

    if warned:
        filtered = [r for r in rankings if r['ticker'] not in warned]
        # composite_rank 재정렬
        filtered.sort(key=lambda x: x.get('score', 0), reverse=True)
        for i, r in enumerate(filtered):
            r['composite_rank'] = i + 1
        names = ', '.join(f"{tk}({','.join(w)})" for tk, w in warned.items())
        print(f"[시장조치] {len(warned)}종목 제외: {names}")
        return filtered, warned

    return rankings, {}


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    # 테스트: 로킷헬스케어
    w = check_warning_naver('376900')
    print(f'376900: {w}')
