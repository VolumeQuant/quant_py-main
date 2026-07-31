# -*- coding: utf-8 -*-
"""KR 섹터 브레드스 look-ahead 감사 (2026-07-31)

계기: US 레포 감사에서 '신호를 그날 종가로 판정해 그날 수익에 적용'하는 버그 발견.
KR send_telegram_auto.calc_system_returns L298도 동일 패턴:
    cp = _get_price(tk, d0);  avg_ret = cp/pp - 1        # d-1 -> d0 수익
    _sc = _breadth_scale.get(d0)                          # d0 종가 기준 상태
    avg_ret = _sc*avg_ret + (1-_sc)*cash                  # d0 상태를 d0 수익에 적용
=> 브레드스 도입 근거였던 "Calmar 4.08 -> 4.36"이 이 낙관에 기댄 것인지 재측정.

방법: 실제 production 보유(state ranking + wr<=3 진입 / wr>EXIT 이탈)를 리플레이해
      일별 포트폴리오 수익을 만들고, 브레드스 스케일을 lag=0(현행) / lag=1(정직)로 적용 비교.
"""
import os, sys, json, glob
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
BASE = r'C:\dev'
sys.path.insert(0, BASE)
os.chdir(BASE)

import breadth_diagnostic as BD

STATE_DIR = os.path.join(BASE, 'state')
PX_FILE = os.path.join(BASE, 'data_cache', 'all_ohlcv_adj_20170601_20260730.parquet')
ENTRY, EXIT, SLOTS = 3, 5, 3          # production boost 파라미터 (E3 X5 S3)
CASH_DAILY = 0.03 / 252


def load_prices():
    df = pd.read_parquet(PX_FILE)
    if '종가' in df.columns:
        df = df.reset_index() if df.index.names != [None] else df
    return df


def main():
    files = sorted(glob.glob(os.path.join(STATE_DIR, 'ranking_2*.json')))
    dates = []
    ranks = {}
    for f in files:
        d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        if not (d.isdigit() and len(d) == 8):
            continue
        try:
            j = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        rows = j.get('data') or j.get('rankings') or (j if isinstance(j, list) else None)
        if not rows:
            continue
        m = {}
        for r in rows:
            tk = str(r.get('종목코드') or r.get('ticker') or '').zfill(6)
            wr = r.get('weighted_rank', r.get('rank'))
            if tk and wr is not None:
                try:
                    m[tk] = float(wr)
                except Exception:
                    pass
        if m:
            ranks[d] = m
            dates.append(d)
    dates.sort()
    print('state 랭킹 로드: %d일 (%s ~ %s)' % (len(dates), dates[0], dates[-1]))

    P = pd.read_parquet(PX_FILE)          # 이미 wide: index=날짜, columns=종목코드
    P.index = pd.to_datetime(P.index).strftime('%Y%m%d')
    P.columns = [str(c).zfill(6) for c in P.columns]
    print('가격 매트릭스: %s ~ %s, 종목 %d' % (P.index[0], P.index[-1], P.shape[1]))

    dates = [d for d in dates if d in P.index]
    scale = BD.breadth_scale_by_date(dates)
    n_fire = sum(1 for d in dates if scale.get(d, 1.0) != 1.0)
    print('브레드스 발동일: %d / %d (%.1f%%)' % (n_fire, len(dates), n_fire / len(dates) * 100))

    # 보유 리플레이 (production 룰)
    hold = []
    rows = []
    for i, d in enumerate(dates):
        rk = ranks[d]
        if i >= 1:
            pv = dates[i - 1]
            rr = []
            for t in hold:
                try:
                    a, b = P.at[pv, t], P.at[d, t]
                    if a and b and a > 0:
                        rr.append(b / a - 1)
                except Exception:
                    pass
            raw = float(np.mean(rr)) if rr else 0.0
        else:
            raw = 0.0
        rows.append((d, raw))
        keep = [t for t in hold if rk.get(t, 9999) <= EXIT]
        if len(keep) < SLOTS:
            pool = sorted([(v, t) for t, v in rk.items() if v <= ENTRY and t not in keep])
            for _, t in pool[:SLOTS - len(keep)]:
                keep.append(t)
        hold = keep

    R = pd.Series({d: r for d, r in rows})
    S = pd.Series({d: (scale.get(d, 1.0) != 1.0) for d in dates})

    def stat(r):
        nav = (1 + r).cumprod()
        yrs = len(r) / 252
        c = (nav.iloc[-1] ** (1 / yrs) - 1) * 100
        m = (nav / nav.cummax() - 1).min() * 100
        return c, m, c / abs(m)

    print()
    print('%-30s %10s %10s %8s' % ('', 'CAGR', 'MDD', 'Calmar'))
    print('-' * 62)
    c, m, k = stat(R)
    print('%-30s %+9.1f%% %+9.1f%% %8.2f' % ('브레드스 미적용', c, m, k))
    for lag, lbl in [(0, 'lag=0 (현행 코드·오염)'), (1, 'lag=1 (정직)'), (2, 'lag=2 (보수)')]:
        s = S.shift(lag).fillna(False)
        r2 = R.where(~s, 0.5 * R + 0.5 * CASH_DAILY)
        c, m, k = stat(r2)
        print('%-30s %+9.1f%% %+9.1f%% %8.2f' % (lbl, c, m, k))


if __name__ == '__main__':
    main()
