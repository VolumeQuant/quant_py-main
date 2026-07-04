# -*- coding: utf-8 -*-
"""실체결 로깅 + 실행갭 리포트 (2026-07-05) — BT(신호 종가) vs 실제 체결가 누수 측정.

사용법:
  체결 기록:  python execution_gap.py add 000660 buy 323500 [--date 20260706] [--qty 10] [--note "시간외"]
  리포트:     python execution_gap.py report

- 로그: execution_log.csv (repo 커밋 대상 — 유실 방지)
- 신호가 = 그날 state/ranking_*.json의 price(종가). BT는 신호일 종가 체결을 가정하므로
  갭 = 체결가와 종가의 차이가 곧 '실행 누수'.
- buy 갭 +0.5% = 종가보다 0.5% 비싸게 삼(손해). sell 갭 +0.5% = 종가보다 0.5% 싸게 팖(손해).
"""
import sys
import os
import csv
import json
import argparse
from pathlib import Path
from datetime import datetime

R = Path(__file__).parent
LOG = R / 'execution_log.csv'
FIELDS = ['date', 'ticker', 'side', 'fill_price', 'qty', 'signal_close', 'gap_pct', 'note']


def _signal_close(date_str, ticker):
    fp = R / 'state' / f'ranking_{date_str}.json'
    if not fp.exists():
        return None
    try:
        data = json.load(open(fp, encoding='utf-8'))
        for r in data.get('rankings', []):
            if r.get('ticker') == ticker:
                return r.get('price')
    except Exception:
        pass
    return None


def cmd_add(args):
    date_str = args.date or datetime.now().strftime('%Y%m%d')
    ticker = args.ticker.zfill(6)
    side = args.side.lower()
    assert side in ('buy', 'sell'), 'side는 buy/sell'
    close = _signal_close(date_str, ticker)
    gap = None
    if close:
        raw = args.price / close - 1
        gap = raw if side == 'buy' else -raw   # 양수 = 손해 방향
    new = not LOG.exists()
    with open(LOG, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({'date': date_str, 'ticker': ticker, 'side': side,
                    'fill_price': args.price, 'qty': args.qty or '',
                    'signal_close': close or '',
                    'gap_pct': round(gap * 100, 3) if gap is not None else '',
                    'note': args.note or ''})
    gtxt = f'갭 {gap*100:+.2f}% ({"손해" if gap > 0 else "이득"})' if gap is not None else '신호가 없음(랭킹 밖) — 갭 미계산'
    print(f'기록됨: {date_str} {ticker} {side} {args.price:,.0f} | 신호종가 {close or "?"} | {gtxt}')


def cmd_report(_args):
    if not LOG.exists():
        print('기록 없음 — 먼저 add로 체결을 기록하세요.')
        return
    rows = list(csv.DictReader(open(LOG, encoding='utf-8')))
    rows = [r for r in rows if r.get('gap_pct') not in (None, '')]
    if not rows:
        print('갭 계산 가능한 기록 없음.')
        return
    gaps = [float(r['gap_pct']) for r in rows]
    buys = [float(r['gap_pct']) for r in rows if r['side'] == 'buy']
    sells = [float(r['gap_pct']) for r in rows if r['side'] == 'sell']
    print(f'총 {len(rows)}건 | 평균 갭 {sum(gaps)/len(gaps):+.2f}% (양수=손해)')
    if buys:
        print(f'  매수 {len(buys)}건: 평균 {sum(buys)/len(buys):+.2f}%')
    if sells:
        print(f'  매도 {len(sells)}건: 평균 {sum(sells)/len(sells):+.2f}%')
    rt = (sum(buys)/len(buys) if buys else 0) + (sum(sells)/len(sells) if sells else 0)
    print(f'  왕복 평균 {rt:+.2f}% × 연 ~21회 매매 = 연 드래그 추정 {rt*21:+.1f}%p')
    print('\n[최근 10건]')
    for r in rows[-10:]:
        print(f"  {r['date']} {r['ticker']} {r['side']:4s} 체결 {float(r['fill_price']):,.0f} vs 종가 {r['signal_close']} → {float(r['gap_pct']):+.2f}% {r.get('note','')}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('add')
    a.add_argument('ticker'); a.add_argument('side'); a.add_argument('price', type=float)
    a.add_argument('--date'); a.add_argument('--qty', type=float); a.add_argument('--note')
    sub.add_parser('report')
    args = ap.parse_args()
    cmd_add(args) if args.cmd == 'add' else cmd_report(args)
