"""YF Step 3 — 시총 1천억+ 미probe 종목 yf 가용성 확장 검증

US 측 488종목 (시총 5천억+) 외 미probe 1039종목 (시총 1천억~5천억) probe.
패턴: US `kr_yf_deep_probe.py`와 동일 (3 worker × 0.4s sleep).

저장: C:/dev/yf_eps_workspace/results/kr_yf_extension_results.csv

production 무변경. yf 외부 API 호출 (사용자 명시 승인).
"""
import sys, time, csv
sys.stdout.reconfigure(encoding='utf-8')
import yfinance as yf
import pandas as pd
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

OUT_CSV = Path(r'C:/dev/yf_eps_workspace/results/kr_yf_extension_results.csv')
US_CSV = Path(r'C:/dev/claude code/eps-momentum-us/research/kr_yf_deep_results.csv')

WORKERS = 3
SLEEP = 0.4
MC_MIN = 1e11  # 1천억


def get_extension_universe():
    """시총 1천억+ 보통주 ∩ US 미probe 종목"""
    files = sorted(glob.glob(r'C:/dev/data_cache/market_cap_ALL_*.parquet'))
    df = pd.read_parquet(files[-1])
    df.columns = ['close', 'mc', 'vol', 'val', 'shares']
    # 보통주 + 시총 1천억+
    df = df[df.mc >= MC_MIN]
    df = df[df.index.astype(str).str.endswith('0')]
    df = df.sort_values('mc', ascending=False)
    print(f'  시총 {MC_MIN/1e8:.0f}억+ 보통주: {len(df)}종목')

    # US 미probe 종목
    us_df = pd.read_csv(US_CSV, dtype={'symbol': str})
    us_df['code'] = us_df['symbol'].str.replace(r'\.K[SQ]$', '', regex=True)
    us_tics = set(us_df['code'].str.zfill(6).tolist())
    print(f'  US probe 완료: {len(us_tics)}종목')

    rows = []
    for tk, row in df.iterrows():
        code = str(tk).zfill(6)
        if code in us_tics:
            continue
        rows.append({'code': code, 'mc_krw': float(row['mc'])})
    print(f'  미probe 대상: {len(rows)}종목')
    return rows


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
        'symbol': sym, 'name': '', 'market': mkt,
        'mc_krw': item['mc_krw'],
        'eps_trend_ok': False, 'fy_complete_0y': False, 'fy_complete_1y': False,
        'snap_ok_count': 0,
        '0y_current': None, '0y_7d': None, '0y_30d': None, '0y_60d': None, '0y_90d': None,
        '1y_current': None, '1y_90d': None,
        'endDate_0y_ok': False, 'endDate_1y_ok': False,
        'rev_ok_0y': False,
        'up7': None, 'up30': None, 'dn30': None, 'dn7': None,
        'na': None, 'rev_growth': None, 'op_margin': None, 'gross_margin': None,
        'fwd_pe': None, 'fwd_eps': None,
        'earn_date_present': False,
        'error': None,
    }
    try:
        t = t_probe if t_probe is not None else yf.Ticker(sym)
        try:
            et = t.eps_trend
            if et is not None and len(et) > 0:
                r['eps_trend_ok'] = True
                cols = ['current', '7daysAgo', '30daysAgo', '60daysAgo', '90daysAgo']
                col_keys = ['current', '7d', '30d', '60d', '90d']
                if '0y' in et.index:
                    not_nan = 0
                    for c, k in zip(cols, col_keys):
                        if c in et.columns:
                            v = et.loc['0y', c]
                            if not pd.isna(v):
                                r[f'0y_{k}'] = float(v)
                                not_nan += 1
                    r['snap_ok_count'] = not_nan
                    r['fy_complete_0y'] = (not_nan == 5)
                if '+1y' in et.index:
                    v = et.loc['+1y', 'current'] if 'current' in et.columns else None
                    if not pd.isna(v): r['1y_current'] = float(v)
                    v90 = et.loc['+1y', '90daysAgo'] if '90daysAgo' in et.columns else None
                    if not pd.isna(v90): r['1y_90d'] = float(v90)
                    r['fy_complete_1y'] = r['1y_current'] is not None and r['1y_90d'] is not None
        except Exception:
            pass

        try:
            raw = t._analysis._earnings_trend
            if raw:
                for item_ in raw:
                    p = item_.get('period'); ed = item_.get('endDate')
                    if p == '0y' and ed: r['endDate_0y_ok'] = True
                    if p == '+1y' and ed: r['endDate_1y_ok'] = True
        except Exception:
            pass

        try:
            er = t.eps_revisions
            if er is not None and len(er) > 0 and '0y' in er.index:
                row = er.loc['0y']
                up7 = row.get('upLast7days'); up30 = row.get('upLast30days')
                dn30 = row.get('downLast30days'); dn7 = row.get('downLast7Days')
                if up30 is not None and not pd.isna(up30):
                    r['up7'] = int(up7) if not pd.isna(up7) else 0
                    r['up30'] = int(up30)
                    r['dn30'] = int(dn30) if not pd.isna(dn30) else 0
                    r['dn7'] = int(dn7) if not pd.isna(dn7) else 0
                    r['rev_ok_0y'] = True
        except Exception:
            pass

        try:
            info = t.info
            r['name'] = info.get('shortName') or info.get('longName') or ''
            r['na'] = info.get('numberOfAnalystOpinions')
            r['rev_growth'] = info.get('revenueGrowth')
            r['op_margin'] = info.get('operatingMargins')
            r['gross_margin'] = info.get('grossMargins')
            r['fwd_pe'] = info.get('forwardPE')
            r['fwd_eps'] = info.get('forwardEps')
        except Exception:
            pass

        try:
            cal = t.calendar
            if cal and cal.get('Earnings Date'):
                r['earn_date_present'] = True
        except Exception:
            pass

    except Exception as e:
        r['error'] = str(e)[:80]

    time.sleep(SLEEP)
    return r


def main():
    print('=' * 70)
    print(f'YF Step 3 — 시총 1천억+ 미probe 종목 가용성 검증')
    print(f'  workers={WORKERS}, sleep={SLEEP}s')
    print('=' * 70)

    universe = get_extension_universe()
    if not universe:
        print('대상 종목 없음')
        return

    est_min = len(universe) * (SLEEP + 0.2) / WORKERS / 60
    print(f'  예상 시간: ~{est_min:.1f}분')
    print()

    results = []
    completed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(probe, u): u for u in universe}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            completed += 1
            if completed % 50 == 0 or completed == len(universe):
                ok = sum(1 for x in results if x['fy_complete_0y'])
                et_ok = sum(1 for x in results if x['eps_trend_ok'])
                el = (time.time() - t0) / 60
                print(f'  [{completed}/{len(universe)}] FY 가용: {ok}/{completed} ({ok/completed*100:.0f}%) '
                      f'eps_trend 존재: {et_ok}/{completed} ({et_ok/completed*100:.0f}%) ({el:.1f}분 경과)',
                      flush=True)

    if results:
        fields = list(results[0].keys())
        with open(OUT_CSV, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(results)
        print(f'\n✓ 저장: {OUT_CSV} ({len(results)} rows)')


if __name__ == '__main__':
    main()
