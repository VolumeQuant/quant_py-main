"""KR yf EPS 모멘텀 daily probe — 시총 1천억+ 보통주 자동 수집

매일 1회 실행 (장 시작 전 권장).
저장: C:/dev/yf_eps_workspace/data_cache_yf/kr_yf_YYYYMMDD.parquet

universe: market_cap parquet 최신 + 시총 1천억+ + 보통주 (끝자리 0)
호출: 1 worker × 0.4s sleep (안전 모드, 약 13분/회)
production 무관 (격리 워크스페이스)
"""
import sys, time, argparse
sys.stdout.reconfigure(encoding='utf-8')
import yfinance as yf
import pandas as pd
import numpy as np
import glob
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r'C:/dev/yf_eps_workspace')
CACHE_DIR = ROOT / 'data_cache_yf'
LOGS_DIR = ROOT / 'logs' / 'daily'
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# probe 설정
WORKERS = 3
SLEEP = 0.4
MC_MIN = 1e11  # 1천억


def get_universe():
    """KRX 시총 1천억+ 보통주"""
    files = sorted(glob.glob(r'C:/dev/data_cache/market_cap_ALL_*.parquet'))
    df = pd.read_parquet(files[-1])
    df.columns = ['close', 'mc', 'vol', 'val', 'shares']
    df = df[df.mc >= MC_MIN]
    df = df[df.index.astype(str).str.endswith('0')]
    df = df.sort_values('mc', ascending=False)
    return [{'code': str(tk).zfill(6), 'mc_krw': float(row['mc'])}
            for tk, row in df.iterrows()]


def try_market(code):
    for mkt in ['KS', 'KQ']:
        sym = f'{code}.{mkt}'
        try:
            t = yf.Ticker(sym)
            et = t.eps_trend
            if et is not None and len(et) > 0:
                return sym, mkt, t
        except Exception:
            continue
        time.sleep(0.1)
    return f'{code}.KS', '?', None


def probe(item):
    code = item['code']
    sym, mkt, t_probe = try_market(code)
    r = {
        'ticker': code, 'symbol': sym, 'market': mkt, 'mc_krw': item['mc_krw'],
        'eps_trend_ok': False, 'fy_complete_0y': False,
        '0y_current': np.nan, '0y_7d': np.nan, '0y_30d': np.nan, '0y_60d': np.nan, '0y_90d': np.nan,
        '1y_current': np.nan, '1y_90d': np.nan,
        'rev_ok_0y': False,
        'up7': np.nan, 'up30': np.nan, 'dn30': np.nan, 'dn7': np.nan,
        'na': np.nan, 'fwd_pe': np.nan, 'fwd_eps': np.nan, 'op_margin': np.nan,
    }
    try:
        t = t_probe if t_probe is not None else yf.Ticker(sym)
        try:
            et = t.eps_trend
            if et is not None and len(et) > 0:
                r['eps_trend_ok'] = True
                if '0y' in et.index:
                    not_nan = 0
                    for c, k in [('current','current'), ('7daysAgo','7d'), ('30daysAgo','30d'),
                                 ('60daysAgo','60d'), ('90daysAgo','90d')]:
                        if c in et.columns:
                            v = et.loc['0y', c]
                            if not pd.isna(v):
                                r[f'0y_{k}'] = float(v); not_nan += 1
                    r['fy_complete_0y'] = (not_nan == 5)
                if '+1y' in et.index:
                    if 'current' in et.columns:
                        v = et.loc['+1y', 'current']
                        if not pd.isna(v): r['1y_current'] = float(v)
                    if '90daysAgo' in et.columns:
                        v = et.loc['+1y', '90daysAgo']
                        if not pd.isna(v): r['1y_90d'] = float(v)
        except Exception:
            pass

        try:
            er = t.eps_revisions
            if er is not None and len(er) > 0 and '0y' in er.index:
                row = er.loc['0y']
                up30 = row.get('upLast30days')
                if up30 is not None and not pd.isna(up30):
                    r['up7'] = int(row.get('upLast7days') or 0)
                    r['up30'] = int(up30)
                    r['dn30'] = int(row.get('downLast30days') or 0)
                    r['dn7'] = int(row.get('downLast7Days') or 0)
                    r['rev_ok_0y'] = True
        except Exception:
            pass

        try:
            info = t.info
            r['na'] = info.get('numberOfAnalystOpinions')
            r['fwd_pe'] = info.get('forwardPE')
            r['fwd_eps'] = info.get('forwardEps')
            r['op_margin'] = info.get('operatingMargins')
        except Exception:
            pass
    except Exception:
        pass

    time.sleep(SLEEP)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=None, help='YYYYMMDD (default: today)')
    args = ap.parse_args()
    date_str = args.date or datetime.now().strftime('%Y%m%d')

    out_file = CACHE_DIR / f'kr_yf_{date_str}.parquet'
    if out_file.exists():
        print(f'이미 존재: {out_file}. 건너뜀.')
        return

    t_start = time.time()
    print(f'=== KR yf daily probe — {date_str} ===')
    universe = get_universe()
    print(f'  유니버스: {len(universe)}종목 (시총 {MC_MIN/1e8:.0f}억+ 보통주)')
    print(f'  workers={WORKERS}, sleep={SLEEP}s')
    print(f'  예상: ~{len(universe) * (SLEEP+0.2) / WORKERS / 60:.0f}분')

    results = []
    completed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(probe, u): u for u in universe}
        for fut in as_completed(futures):
            results.append(fut.result())
            completed += 1
            if completed % 100 == 0 or completed == len(universe):
                ok = sum(1 for x in results if x['fy_complete_0y'])
                el = (time.time() - t_start) / 60
                print(f'  [{completed}/{len(universe)}] fy_complete {ok} ({ok/completed*100:.0f}%) — {el:.1f}분', flush=True)

    df = pd.DataFrame(results)
    df['date'] = date_str
    df = df.sort_values('mc_krw', ascending=False)
    # numeric 컬럼 강제 변환 + Infinity 처리 (parquet 호환)
    for col in ['fwd_pe', 'fwd_eps', 'op_margin', '0y_current', '0y_7d', '0y_30d',
                '0y_60d', '0y_90d', '1y_current', '1y_90d']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.replace([np.inf, -np.inf], np.nan)
    df.to_parquet(out_file, index=False)

    elapsed = (time.time() - t_start) / 60
    fy_ok = df['fy_complete_0y'].sum()
    et_ok = df['eps_trend_ok'].sum()
    na3 = (df['na'].fillna(0) >= 3).sum()
    print(f'\n=== 완료 ===')
    print(f'  저장: {out_file}')
    print(f'  종목: {len(df)}, et_ok {et_ok} ({et_ok/len(df)*100:.0f}%), '
          f'fy_complete {fy_ok} ({fy_ok/len(df)*100:.0f}%), na>=3 {na3} ({na3/len(df)*100:.0f}%)')
    print(f'  소요: {elapsed:.1f}분')


if __name__ == '__main__':
    main()
