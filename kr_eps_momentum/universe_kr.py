"""KR universe getter — US daily_runner의 fetch_dynamic_tickers 대체

KRX 시총 1천억+ 보통주 → yf ticker (.KS / .KQ) 매핑.
production data_cache 읽기 전용 (변경 X).
"""
import glob
import pandas as pd
from pathlib import Path

# production data_cache 경로 (read-only)
KR_CACHE = Path(r'C:/dev/data_cache')
UNIVERSE_CACHE = Path(__file__).resolve().parent.parent / 'yf_eps_workspace' / 'universe_kr.parquet'


def fetch_dynamic_tickers(min_mcap=1e12):  # KR adapt 2026-06-01: 1천억→1조 (EDA: yfinance EPS forecast 시총 1조+만 제공, 그 이하 76% 무의미 fetch)
    """US daily_runner.fetch_dynamic_tickers 호환 — set of yf symbol 반환.
    KR universe symbol cache (.KS/.KQ 결정 완료) 우선 사용.

    GHA 호환 (2026-06-01 fix): UNIVERSE_CACHE 정상 path → cwd 상대경로 fallback → KR_CACHE Linux 방어.
    """
    # 1) UNIVERSE_CACHE 정상 path (Path(__file__).parent.parent/'yf_eps_workspace'/...)
    candidates = [UNIVERSE_CACHE]
    # 2) cwd 상대경로 fallback (GHA working dir 다를 수 있음)
    candidates.append(Path.cwd() / 'yf_eps_workspace' / 'universe_kr.parquet')
    # 3) repo root 추정 (kr_eps_momentum 부모)
    candidates.append(Path(__file__).resolve().parent.parent.parent / 'quant_py-main' / 'yf_eps_workspace' / 'universe_kr.parquet')

    import sys as _sys_dbg
    for cache in candidates:
        if cache.exists():
            try:
                df = pd.read_parquet(cache)
                print(f'[universe debug] cache={cache} shape={df.shape} cols={list(df.columns)}', file=_sys_dbg.stderr)
                if 'symbol' in df.columns and 'mc_krw' in df.columns:
                    n_before = len(df)
                    df_f = df[df['mc_krw'] >= min_mcap]
                    tickers = set(df_f['symbol'].astype(str))
                    print(f'[universe debug] before {n_before} → after mc_krw>={min_mcap}: {len(df_f)} → tickers {len(tickers)}', file=_sys_dbg.stderr)
                    if tickers:
                        return tickers
                else:
                    print(f'[universe debug] required columns missing: symbol={"symbol" in df.columns} mc_krw={"mc_krw" in df.columns}', file=_sys_dbg.stderr)
            except Exception as _ex:
                print(f'[universe debug] cache={cache} read error: {_ex}', file=_sys_dbg.stderr)

    # 4) fallback — production market_cap_ALL (로컬 Windows only)
    if KR_CACHE.exists():
        files = sorted(KR_CACHE.glob('market_cap_ALL_*.parquet'))
        if files:
            df = pd.read_parquet(files[-1])
            df.columns = ['close', 'mc', 'vol', 'val', 'shares']
            df = df[df.mc >= min_mcap]
            df = df[df.index.astype(str).str.endswith('0')]
            return set(f'{str(t).zfill(6)}.KS' for t in df.index)

    # 5) 모든 path 실패 — 명확한 에러
    raise RuntimeError(
        f'KR universe 데이터 없음. '
        f'UNIVERSE_CACHE={UNIVERSE_CACHE} (exists={UNIVERSE_CACHE.exists()}), '
        f'cwd={Path.cwd()}, '
        f'KR_CACHE={KR_CACHE} (exists={KR_CACHE.exists()})'
    )


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
