# -*- coding: utf-8 -*-
"""
실발송 고정 원장 (as-sent ledger) — 2026-07-08

문제: 텔레그램 "시스템 수익률"(calc_system_returns)은 현재 룰로 과거 전체를
소급 리플레이한 값이라, 룰이 바뀔 때마다 과거 성적도 바뀜 (라이브 실적과 괴리).

해결: 발송 시점의 picks를 append-only로 박제(state/asent_ledger.csv)하고,
그 박제본으로만 계산한 성적을 개인봇 검문소에 병기 (채널 메시지 불변).

- record_today(picks, date_str): 같은 date 재실행 시 덮어쓰지 않고 스킵 (박제 원칙)
- ledger_performance(): 전일 기록 픽 동일가중 보유 → 오늘 수익 (일별 체인)
- build_ledger_line(): 검문소용 1줄 (5일 미만 축적 중, 실패 시 빈 문자열)
- 백필: python asent_ledger.py --backfill  (state/web_data_*.json → 원장)
- 킬스위치: ASENT_LEDGER_DISABLE=1
"""
import csv
import glob
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
STATE_DIR = BASE_DIR / 'state'
LEDGER_PATH = STATE_DIR / 'asent_ledger.csv'
DATA_CACHE = BASE_DIR / 'data_cache'

FIELDS = ['date', 'tickers', 'names', 'prices']
SEP = '|'


def _disabled():
    return os.environ.get('ASENT_LEDGER_DISABLE') == '1'


def _load_ledger():
    """원장 CSV → list of dict (date 오름차순). 없으면 []."""
    if not LEDGER_PATH.exists():
        return []
    rows = []
    with open(LEDGER_PATH, 'r', encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            if row.get('date'):
                rows.append(row)
    rows.sort(key=lambda r: r['date'])
    return rows


def _existing_dates():
    return {r['date'] for r in _load_ledger()}


def _latest_adj_parquet():
    cands = sorted(glob.glob(str(DATA_CACHE / 'all_ohlcv_adj_*.parquet')))
    if not cands:
        raise FileNotFoundError('all_ohlcv_adj_*.parquet 없음')
    return cands[-1]


def _asof_price(series, ts):
    """ts 이하 마지막 유효 종가 (없으면 None)."""
    s = series.dropna()
    s = s[s.index <= ts]
    if len(s) == 0:
        return None
    return float(s.iloc[-1])


def _append_row(date_str, tickers, names, prices):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    new_file = not LEDGER_PATH.exists()
    with open(LEDGER_PATH, 'a', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({
            'date': date_str,
            'tickers': SEP.join(tickers),
            'names': SEP.join(names),
            'prices': SEP.join(prices),
        })


def record_today(picks, date_str):
    """발송 시점 picks 박제 (append-only).

    picks: [{'ticker': .., 'name': ..}, ...] (빈 리스트 = cash, 그것도 기록)
    date_str: 'YYYYMMDD'
    같은 date 재실행 시 덮어쓰지 않고 스킵. 반환: True(기록) / False(스킵).
    """
    if _disabled():
        return False
    date_str = str(date_str).replace('-', '')[:8]
    if date_str in _existing_dates():
        print(f'  [원장] {date_str} 이미 기록됨 — 스킵 (박제 원칙)')
        return False

    tickers = [str(p.get('ticker', '')) for p in (picks or [])]
    names = [str(p.get('name', '')) for p in (picks or [])]

    # 기록 시점 참고용 가격 (adj 종가 asof). 실패해도 기록은 진행 (성적계산은 parquet 사용).
    prices = [''] * len(tickers)
    if tickers:
        try:
            import pandas as pd
            df = pd.read_parquet(_latest_adj_parquet(),
                                 columns=[t for t in tickers if t])
            ts = pd.Timestamp(f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}')
            prices = []
            for t in tickers:
                p = _asof_price(df[t], ts) if t in df.columns else None
                prices.append(f'{p:.2f}' if p is not None else '')
        except Exception as e:
            print(f'  [원장] 가격 조회 실패 (기록은 진행): {e}')
            prices = [''] * len(tickers)

    _append_row(date_str, tickers, names, prices)
    print(f'  [원장] {date_str} 기록: {len(tickers)}종목 ({", ".join(names) or "cash"})')
    return True


def ledger_performance():
    """원장 기반 성적: 매일 "전일 기록 픽 동일가중 보유 → 오늘 수익" 체인.

    가격 = all_ohlcv_adj (glob 최신), KOSPI = kospi_yf.parquet.
    반환 dict: days, start, end, cum_pct, mdd_pct, kospi_pct, equity(list)
    원장 2행 미만이면 None.
    """
    import pandas as pd

    rows = _load_ledger()
    if len(rows) < 2:
        return None

    all_tickers = sorted({t for r in rows for t in r['tickers'].split(SEP) if t})
    px = pd.read_parquet(_latest_adj_parquet(),
                         columns=all_tickers if all_tickers else None)

    def _ts(d):
        return pd.Timestamp(f'{d[:4]}-{d[4:6]}-{d[6:8]}')

    dates = [_ts(r['date']) for r in rows]
    equity = [1.0]
    for i in range(1, len(rows)):
        prev_picks = [t for t in rows[i - 1]['tickers'].split(SEP) if t]
        d0, d1 = dates[i - 1], dates[i]
        rets = []
        for t in prev_picks:
            if t not in px.columns:
                continue
            p0 = _asof_price(px[t], d0)
            p1 = _asof_price(px[t], d1)
            if p0 and p1 and p0 > 0:
                rets.append(p1 / p0 - 1.0)
        day_ret = sum(rets) / len(rets) if rets else 0.0  # 픽 없음/가격 없음 = cash
        equity.append(equity[-1] * (1.0 + day_ret))

    eq = pd.Series(equity)
    cum_pct = (eq.iloc[-1] - 1.0) * 100
    mdd_pct = ((eq / eq.cummax()) - 1.0).min() * 100

    kospi_pct = None
    try:
        k = pd.read_parquet(DATA_CACHE / 'kospi_yf.parquet')['close'].dropna()
        k0 = _asof_price(k, dates[0])
        k1 = _asof_price(k, dates[-1])
        if k0 and k1:
            kospi_pct = (k1 / k0 - 1.0) * 100
    except Exception:
        pass

    return {
        'days': len(rows),
        'start': rows[0]['date'],
        'end': rows[-1]['date'],
        'cum_pct': round(cum_pct, 2),
        'mdd_pct': round(mdd_pct, 2),
        'kospi_pct': round(kospi_pct, 2) if kospi_pct is not None else None,
        'equity': [round(v, 6) for v in equity],
    }


def build_ledger_line():
    """개인봇 검문소용 1줄. 5일 미만 축적 중, 실패/비활성 시 빈 문자열 (안전)."""
    if _disabled():
        return ''
    try:
        n = len(_load_ledger())
        if n == 0:
            return ''
        if n < 5:
            return f'📒 실발송 원장: 축적 중 ({n}일째)'
        perf = ledger_performance()
        if not perf:
            return f'📒 실발송 원장: 축적 중 ({n}일째)'
        kospi_s = (f' (KOSPI {perf["kospi_pct"]:+.1f}%)'
                   if perf.get('kospi_pct') is not None else '')
        return (f'📒 실발송 원장: 기록 {perf["days"]}일째 · '
                f'누적 {perf["cum_pct"]:+.1f}%{kospi_s} · '
                f'MDD {perf["mdd_pct"]:.1f}%')
    except Exception:
        return ''


def backfill_from_web_data():
    """state/web_data_*.json의 picks를 날짜순 일괄 박제 (1회용). date당 1행."""
    files = sorted(glob.glob(str(STATE_DIR / 'web_data_*.json')))
    if not files:
        print('web_data_*.json 없음')
        return 0
    done = _existing_dates()
    added = 0
    for fp in files:
        date_str = Path(fp).stem.replace('web_data_', '')
        if not (len(date_str) == 8 and date_str.isdigit()):
            continue
        if date_str in done:
            continue
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                picks = json.load(f).get('picks', []) or []
        except Exception as e:
            print(f'  {date_str}: 읽기 실패 스킵 ({e})')
            continue
        if record_today(picks, date_str):
            added += 1
            done.add(date_str)
    print(f'\n백필 완료: {added}일 추가 (원장 총 {len(_load_ledger())}일)')
    return added


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='실발송 고정 원장 (as-sent ledger)')
    ap.add_argument('--backfill', action='store_true',
                    help='state/web_data_*.json에서 과거 picks 일괄 박제 (1회용)')
    ap.add_argument('--perf', action='store_true', help='원장 성적 출력')
    args = ap.parse_args()

    if args.backfill:
        backfill_from_web_data()
    if args.perf or args.backfill:
        perf = ledger_performance()
        if perf:
            eqs = perf.pop('equity')
            print('\n[ledger_performance]')
            for k, v in perf.items():
                print(f'  {k}: {v}')
        else:
            print('원장 데이터 부족 (2일 미만)')
        print('\n[build_ledger_line]')
        print(' ', build_ledger_line() or '(빈 문자열)')
    if not (args.backfill or args.perf):
        ap.print_help()
