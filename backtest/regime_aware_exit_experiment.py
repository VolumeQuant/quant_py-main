"""Regime-aware exit rules — boost vs defense에 다른 SL/TS 적용

User 가설: 강세장(boost)엔 baseline (-15%/-10%) loose, 약세장(defense)엔 tight (-8%/-7%)
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

    V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
    V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
    GS = ('rev_z','oca_z',None,None,None,None)

    # 변형 (boost SL/TS, defense SL/TS)
    variants = [
        ('A. baseline (both -10/-15)',     -0.10, -0.15, -0.10, -0.15),
        ('B. both tight (-7/-8)',           -0.07, -0.08, -0.07, -0.08),
        ('C. boost loose, defense tight',   -0.10, -0.15, -0.07, -0.08),
        ('D. boost tight, defense loose',   -0.07, -0.08, -0.10, -0.15),
        ('E. boost -8 only',                -0.10, -0.08, -0.10, -0.15),
        ('F. boost -10/-12, defense -7/-8', -0.10, -0.12, -0.07, -0.08),
    ]

    period_dates = [d for d in common if '20180702' <= d <= '20260506']
    regime_dict = calc_regime(period_dates, kospi, ma170)
    print(f'기간: {len(period_dates)}일')

    tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)

    rows = []
    for name, sl_o, ts_o, sl_d, ts_d in variants:
        r = tsim.run_regime(
            defense_params=V80_D, offense_params=V80_O,
            regime_dict=regime_dict,
            stop_loss_o=sl_o, trailing_stop_o=ts_o,
            stop_loss_d=sl_d, trailing_stop_d=ts_d,
            g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
            g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
            g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
            g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
        )
        rows.append({
            '전략': name,
            'CAGR(%)': r['cagr'], 'MDD(%)': r['mdd'],
            'Calmar': r['calmar'], 'Sharpe': r['sharpe'],
            'Sortino': r['sortino'], '누적(%)': r['total'],
        })
    df = pd.DataFrame(rows).sort_values('Calmar', ascending=False).reset_index(drop=True)
    df.insert(0, '순위', df.index + 1)
    print('\n=== 7.8년 BT (regime-aware exit) ===')
    print(df.to_string(index=False))

    # 연도별
    print('\n=== 연도별 비교 (Calmar) ===')
    yearly = []
    for yr in ['2018','2019','2020','2021','2022','2023','2024','2025','2026']:
        ps = f'{yr}0101' if yr != '2018' else '20180702'
        pe = f'{yr}1231' if yr != '2026' else '20260506'
        pd_y = [d for d in common if ps <= d <= pe]
        if len(pd_y) < 30: continue
        regime_y = calc_regime(pd_y, kospi, ma170)
        boost_pct = sum(1 for v in regime_y.values() if v) / len(pd_y) * 100
        ts_y = TurboSimulator({d: rk_boost[d] for d in pd_y}, pd_y, ohlcv)
        row = {'year': yr, 'boost%': f'{boost_pct:.0f}'}
        for name, sl_o, ts_o, sl_d, ts_d in variants:
            r = ts_y.run_regime(
                defense_params=V80_D, offense_params=V80_O,
                regime_dict=regime_y,
                stop_loss_o=sl_o, trailing_stop_o=ts_o,
                stop_loss_d=sl_d, trailing_stop_d=ts_d,
                g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
                g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
                g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
                g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
            )
            short_name = name.split('.')[0].strip()
            row[short_name] = r['calmar']
        yearly.append(row)
    print(pd.DataFrame(yearly).to_string(index=False))


if __name__ == '__main__':
    main()
