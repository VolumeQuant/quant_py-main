"""Trailing Stop 변형 BT — user 동아엘텍 4/27 +30% → 4/28 -18% 사례 대응

점수 시스템 그대로 두고 매도 규칙만 강화.
trailing 좁히면 단기 급등→급락 종목 빨리 매도 가능.
"""
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT = Path(r'C:\dev')
sys.path.insert(0, str(PROJECT / 'backtest'))
from turbo_simulator import TurboSimulator


def load_rankings(dirs):
    data = {}
    for d in dirs:
        d = Path(d)
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8 or not k.isdigit(): continue
            if k not in data:
                with open(fp, encoding='utf-8') as f:
                    data[k] = json.load(f)
    return data


def calc_regime(target_dates, kospi, ma170):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv):
            reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 8 and md != s: md = s
        reg[d] = md
    return reg


def main():
    print('데이터 로드...', flush=True)
    boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
    defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
    common = sorted(set(boost) & set(defense))
    rk_boost = {d: boost[d]['rankings'] if isinstance(boost[d], dict) else boost[d] for d in common}

    ohlcv = pd.read_parquet(
        sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]
    ).replace(0, np.nan)
    kospi = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet').iloc[:,0].dropna()
    ma170 = kospi.rolling(170).mean()

    V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
             'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
    V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,
             'entry':3,'exit':6,'slots':3,'mom':'12m'}

    GS = ('rev_z','oca_z',None,None,None,None)

    # trailing stop 변형 (stop_loss는 고정 -10%)
    variants = [
        ('TS -20% (loose)',     -0.20, -0.10),
        ('TS -15% (baseline)',  -0.15, -0.10),
        ('TS -12%',             -0.12, -0.10),
        ('TS -10%',             -0.10, -0.10),
        ('TS -8% (tight)',      -0.08, -0.10),
        ('TS -6% (very tight)', -0.06, -0.10),
        ('TS off',              None,  -0.10),
    ]

    periods = [
        ('2026 YTD',           '20260102', '20260506'),
        ('2024~2026 (2.3y)',  '20240102', '20260506'),
        ('2018~2026 (7.8y)',  '20180702', '20260506'),
    ]

    all_rows = []
    for label, ps, pe in periods:
        print(f'\n=== {label}: {ps} ~ {pe} ===', flush=True)
        period_dates = [d for d in common if ps <= d <= pe]
        if not period_dates:
            continue
        regime_dict = calc_regime(period_dates, kospi, ma170)
        tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)

        rows = []
        for name, ts_pct, sl_pct in variants:
            r = tsim.run_regime(
                defense_params=V80_D, offense_params=V80_O,
                regime_dict=regime_dict,
                trailing_stop=ts_pct, stop_loss=sl_pct,
                g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
                g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
                g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
                g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
            )
            rows.append({
                '전략': name,
                'CAGR(%)': r['cagr'],
                'MDD(%)': r['mdd'],
                'Calmar': r['calmar'],
                'Sharpe': r['sharpe'],
                '누적(%)': r['total'],
            })
        df = pd.DataFrame(rows).sort_values('Calmar', ascending=False).reset_index(drop=True)
        df.insert(0, '순위', df.index + 1)
        print(df.to_string(index=False))
        for r in rows:
            all_rows.append({'기간': label, **r})

    pd.DataFrame(all_rows).to_csv(
        r'C:\dev\backtest\trailing_stop_result.csv',
        index=False, encoding='utf-8-sig')
    print('\n저장 완료')


if __name__ == '__main__':
    main()
