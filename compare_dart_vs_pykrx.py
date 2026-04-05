"""DART 기반 vs pykrx 기반 백테스트 비교 (2024~2026)

비교 항목: 누적수익률, CAGR, MDD, Sharpe, Alpha(vs KOSPI)
"""
import os, json, glob, time, math
import pandas as pd
import numpy as np
from pathlib import Path

PROJECT = Path(__file__).parent
OHLCV_DIR = PROJECT / 'data_cache'


def load_rankings(state_dirs):
    """여러 state 디렉토리에서 ranking 로드 (날짜순 병합)"""
    all_data = {}
    for sd in state_dirs:
        for fp in sorted(glob.glob(str(sd / 'ranking_*.json'))):
            d = os.path.basename(fp).replace('ranking_', '').replace('.json', '')
            with open(fp, 'r', encoding='utf-8') as fh:
                all_data[d] = json.load(fh)
    return all_data


def load_ohlcv():
    ohlcv_files = sorted(glob.glob(str(OHLCV_DIR / 'all_ohlcv_*.parquet')))
    if not ohlcv_files:
        return pd.DataFrame()
    full_files = [f for f in ohlcv_files if '_full' in f]
    if full_files:
        ohlcv_files = full_files
    parts = [pd.read_parquet(f).replace(0, np.nan) for f in ohlcv_files]
    return pd.concat(parts).groupby(level=0).first()


def load_kospi():
    """KOSPI 일간 수익률 로드"""
    import sys
    sys.path.insert(0, str(PROJECT))
    try:
        import krx_auth
        krx_auth.login()
        from pykrx import stock
        df = stock.get_index_ohlcv('20240101', '20260331', '1001')
        if not df.empty:
            return df.iloc[:, 3]  # 종가
    except:
        pass
    return pd.Series()


def simulate(all_data, ohlcv, entry_rank=5, exit_rank=12, max_slots=7):
    """v71 전략 시뮬레이션 — 값 기반 진입/퇴출, 전체 ranking wr"""
    dates = sorted(all_data.keys())
    portfolio = {}
    equity = 1.0
    peak = 1.0
    max_dd = 0
    start_date = None
    daily_returns = []
    daily_dates = []

    def get_price(ticker, date_str):
        ts = pd.Timestamp(date_str)
        if not ohlcv.empty and ts in ohlcv.index and ticker in ohlcv.columns:
            v = ohlcv.loc[ts, ticker]
            if pd.notna(v) and v > 0:
                return v
        return 0

    for i in range(len(dates)):
        d0 = dates[i]
        d1 = dates[i - 1] if i >= 1 else None
        d2 = dates[i - 2] if i >= 2 else None

        # 일간 수익률
        day_ret = 0
        if i >= 1 and portfolio:
            rets = []
            for tk in portfolio:
                pp = get_price(tk, dates[i - 1])
                cp = get_price(tk, d0)
                if pp > 0 and cp > 0:
                    rets.append(cp / pp - 1)
            if rets:
                day_ret = sum(rets) / len(rets)
                equity *= (1 + day_ret)
            if equity > peak:
                peak = equity
            dd = (equity / peak - 1) * 100
            if dd < max_dd:
                max_dd = dd
            daily_returns.append(day_ret)
            daily_dates.append(d0)

        if i < 2:
            continue

        # 손절 -10%
        for tk in list(portfolio.keys()):
            cp = get_price(tk, d0)
            ep = portfolio[tk]
            if cp > 0 and ep > 0 and (cp / ep - 1) <= -0.10:
                del portfolio[tk]

        r0 = all_data[d0].get('rankings', [])
        r1 = all_data[d1].get('rankings', [])
        r2 = all_data[d2].get('rankings', [])

        # 전체 ranking에서 wr 계산 (퇴출용)
        all_t0 = {r['ticker']: r for r in r0}
        all_t1 = {r['ticker']: r for r in r1}
        all_t2 = {r['ticker']: r for r in r2}

        def _wr(tk):
            if tk not in all_t0:
                return 999
            cr0 = all_t0[tk].get('composite_rank', all_t0[tk].get('rank', 999))
            cr1 = all_t1[tk].get('composite_rank', all_t1[tk].get('rank', 999)) if tk in all_t1 else 999
            cr2 = all_t2[tk].get('composite_rank', all_t2[tk].get('rank', 999)) if tk in all_t2 else 999
            return cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2

        # 퇴출
        for tk in list(portfolio.keys()):
            if _wr(tk) > exit_rank:
                del portfolio[tk]

        # 진입: top20 교집합 + 값 기반
        top20_t0 = {r['ticker']: r for r in r0 if r.get('composite_rank', r['rank']) <= 20}
        top20_t1 = {r['ticker']: r for r in r1 if r.get('composite_rank', r['rank']) <= 20}
        top20_t2 = {r['ticker']: r for r in r2 if r.get('composite_rank', r['rank']) <= 20}
        common = set(top20_t0) & set(top20_t1) & set(top20_t2)

        verified = []
        for tk in common:
            cr0 = top20_t0[tk].get('composite_rank', top20_t0[tk]['rank'])
            cr1 = top20_t1[tk].get('composite_rank', top20_t1[tk]['rank'])
            cr2 = top20_t2[tk].get('composite_rank', top20_t2[tk]['rank'])
            wr = cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2
            verified.append({'ticker': tk, 'weighted_rank': wr})
        verified.sort(key=lambda x: x['weighted_rank'])

        for v in verified:
            if v['ticker'] in portfolio:
                continue
            if len(portfolio) >= max_slots:
                break
            if v['weighted_rank'] <= entry_rank:
                ep = get_price(v['ticker'], d0)
                if ep > 0:
                    portfolio[v['ticker']] = ep
                    if start_date is None:
                        start_date = d0

    if not daily_returns:
        return None

    days = len(daily_returns)
    years = days / 252
    cum = (equity - 1) * 100
    cagr = (equity ** (1 / years) - 1) * 100 if years > 0 else 0

    # Sharpe
    if len(daily_returns) >= 2:
        mean_r = np.mean(daily_returns)
        std_r = np.std(daily_returns, ddof=1)
        sharpe = (mean_r / std_r) * (252 ** 0.5) if std_r > 0 else 0
    else:
        sharpe = 0

    return {
        'cum': cum, 'cagr': cagr, 'mdd': max_dd, 'sharpe': sharpe,
        'days': days, 'start_date': start_date,
        'daily_returns': daily_returns, 'daily_dates': daily_dates,
    }


def calc_alpha(sys_daily, sys_dates, kospi_prices):
    """KOSPI 대비 Alpha 계산"""
    if kospi_prices.empty or not sys_daily:
        return 0
    kospi_rets = kospi_prices.pct_change().dropna()
    # 날짜 매칭
    matched = []
    for d, r in zip(sys_dates, sys_daily):
        ts = pd.Timestamp(d)
        if ts in kospi_rets.index:
            matched.append((r, kospi_rets.loc[ts]))
    if len(matched) < 10:
        return 0
    sys_cum = 1
    bench_cum = 1
    for sr, br in matched:
        sys_cum *= (1 + sr)
        bench_cum *= (1 + br)
    years = len(matched) / 252
    sys_ann = (sys_cum ** (1 / years) - 1) * 100 if years > 0 else 0
    bench_ann = (bench_cum ** (1 / years) - 1) * 100 if years > 0 else 0
    return sys_ann - bench_ann


if __name__ == '__main__':
    import sys as _sys
    _sys.stdout.reconfigure(encoding='utf-8')

    print('데이터 로딩...')
    ohlcv = load_ohlcv()
    kospi = load_kospi()

    # DART 기반 (새로 생성)
    dart_dirs = [PROJECT / 'state' / 'bt_2024', PROJECT / 'state' / 'bt_2025', PROJECT / 'state']
    dart_data = load_rankings(dart_dirs)
    dart_dates = sorted(dart_data.keys())
    dart_2024 = {d: dart_data[d] for d in dart_dates if '20240102' <= d <= '20260320'}

    # pykrx 기반 (백업)
    pykrx_dirs = [PROJECT / 'state' / 'bt_2024_pykrx_backup', PROJECT / 'state' / 'bt_2025_pykrx_backup', PROJECT / 'state']
    pykrx_data = load_rankings(pykrx_dirs)
    pykrx_dates = sorted(pykrx_data.keys())
    pykrx_2024 = {d: pykrx_data[d] for d in pykrx_dates if '20240102' <= d <= '20260320'}

    print(f'DART ranking: {len(dart_2024)}일')
    print(f'pykrx ranking: {len(pykrx_2024)}일')
    print()

    # 시뮬레이션
    print('시뮬레이션 실행...')
    dart_result = simulate(dart_2024, ohlcv, entry_rank=5, exit_rank=12, max_slots=7)
    pykrx_result = simulate(pykrx_2024, ohlcv, entry_rank=5, exit_rank=12, max_slots=7)

    # Alpha
    dart_alpha = calc_alpha(dart_result['daily_returns'], dart_result['daily_dates'], kospi) if dart_result else 0
    pykrx_alpha = calc_alpha(pykrx_result['daily_returns'], pykrx_result['daily_dates'], kospi) if pykrx_result else 0

    print()
    print(f'{"":>15} {"DART 기반":>12} {"pykrx 기반":>12} {"차이":>10}')
    print('=' * 52)
    if dart_result and pykrx_result:
        for label, dk, pk in [
            ('누적수익률', dart_result['cum'], pykrx_result['cum']),
            ('CAGR', dart_result['cagr'], pykrx_result['cagr']),
            ('MDD', dart_result['mdd'], pykrx_result['mdd']),
            ('Sharpe', dart_result['sharpe'], pykrx_result['sharpe']),
            ('Alpha', dart_alpha, pykrx_alpha),
        ]:
            diff = dk - pk
            fmt = '.1f' if label != 'Sharpe' else '.2f'
            print(f'{label:>15} {dk:>11{fmt}}% {pk:>11{fmt}}% {diff:>+9{fmt}}%p')
    else:
        print('시뮬레이션 실패')
        if not dart_result:
            print('  DART: 데이터 부족')
        if not pykrx_result:
            print('  pykrx: 데이터 부족')
