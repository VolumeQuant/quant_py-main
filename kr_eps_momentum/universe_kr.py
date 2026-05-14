"""KR universe getter — US daily_runner의 fetch_dynamic_tickers 대체

KRX 시총 1천억+ 보통주 → yf ticker (.KS / .KQ) 매핑.
production data_cache 읽기 전용 (변경 X).
"""
import glob
import pandas as pd
from pathlib import Path

# production data_cache 경로 (read-only)
KR_CACHE = Path(r'C:/dev/data_cache')


def get_kr_universe(min_mcap_krw=1e11, exclude_pref=True):
    """KR 보통주 시총 1천억+ ticker 리스트
    Returns: list of {'code': '005930', 'symbol': '005930.KS', 'mc_krw': ...}
    .KS / .KQ는 probe 단계에서 결정 (try_market 패턴, US 코드와 동일).
    """
    files = sorted(KR_CACHE.glob('market_cap_ALL_*.parquet'))
    if not files:
        raise RuntimeError(f'market_cap parquet 없음: {KR_CACHE}')
    df = pd.read_parquet(files[-1])
    df.columns = ['close', 'mc', 'vol', 'val', 'shares']
    df = df[df.mc >= min_mcap_krw]
    if exclude_pref:
        # 우선주 제외 (끝자리 != 0)
        df = df[df.index.astype(str).str.endswith('0')]
    df = df.sort_values('mc', ascending=False)
    return [{'code': str(tk).zfill(6), 'symbol': None, 'mc_krw': float(row['mc'])}
            for tk, row in df.iterrows()]


def get_kr_trading_dates(start, end):
    """KR 거래일 (KRX). pykrx 호출은 외부 API라 cache 우선.
    OHLCV parquet의 index를 거래일로 사용."""
    files = sorted(KR_CACHE.glob('all_ohlcv_*_full*.parquet')) or \
            sorted(KR_CACHE.glob('all_ohlcv_*.parquet'))
    files = sorted([f for f in files if not f.stem.startswith('all_ohlcv_2019')],
                   key=lambda f: f.stem.split('_')[2])
    df = pd.read_parquet(files[0])
    dates = [d.strftime('%Y%m%d') for d in df.index]
    return [d for d in dates if start <= d <= end]


# Commodity 제외 키워드 (KR — fast_generate_rankings_v2.py EXCLUDE_KEYWORDS 참고)
KR_COMMODITY_KEYWORDS = {
    '석유', '정유', '광업', '제련', '아연', '동',
    '시멘트', '철강', '제철', '비철금속',
    '농업', '축산',
}


if __name__ == '__main__':
    univ = get_kr_universe()
    print(f'KR universe (시총 1천억+ 보통주): {len(univ)}종목')
    print(f'  Top 5:')
    for u in univ[:5]:
        print(f'    {u["code"]} (시총 {u["mc_krw"]/1e8:.0f}억)')
