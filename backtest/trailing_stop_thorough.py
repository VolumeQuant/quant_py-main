"""Trailing Stop — 연도별 + Sharpe/Sortino 포함 철저 검증"""
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


def metrics_from_rets(rets):
    rets = np.asarray(rets, dtype=np.float64)
    n = len(rets)
    if n == 0 or rets.std() == 0:
        return {'cagr':0,'mdd':0,'calmar':0,'sharpe':0,'sortino':0,'total':0,'winrate':0}
    eq = np.cumprod(1 + rets); total = (eq[-1]-1)*100
    cagr = (eq[-1]**(252/n) - 1)*100
    sharpe = rets.mean()/rets.std()*np.sqrt(252)
    down = rets[rets < 0]
    down_std = down.std() if len(down) > 0 else rets.std()
    sortino = (rets.mean()/down_std*np.sqrt(252)) if down_std > 0 else sharpe
    eq2 = np.empty(n+1); eq2[0]=1; eq2[1:]=eq
    peak = np.maximum.accumulate(eq2)
    mdd = abs(((eq2-peak)/peak).min())*100
    cal = cagr/mdd if mdd > 0 else 0
    winrate = (rets > 0).sum() / (rets != 0).sum() * 100 if (rets != 0).any() else 0
    return {'cagr':round(cagr,2),'mdd':round(mdd,2),'calmar':round(cal,3),
            'sharpe':round(sharpe,3),'sortino':round(sortino,3),
            'total':round(total,2),'winrate':round(winrate,1)}


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

    # 비교 대상 (3개 핵심)
    variants = [
        ('A. baseline (TS-15% SL-10%)', -0.15, -0.10),
        ('B. TS-8% only',                -0.08, -0.10),
        ('C. TS-8% + SL-7%',             -0.08, -0.07),
    ]

    # 연도별 BT
    print('\n=== 연도별 비교 (Calmar/Sharpe/Sortino/MDD) ===\n')
    years = ['2018','2019','2020','2021','2022','2023','2024','2025','2026']
    yearly_data = {v[0]: {} for v in variants}

    for yr in years:
        ps = f'{yr}0101' if yr != '2018' else '20180702'
        pe = f'{yr}1231' if yr != '2026' else '20260506'
        period_dates = [d for d in common if ps <= d <= pe]
        if len(period_dates) < 30:
            continue
        regime_dict = calc_regime(period_dates, kospi, ma170)
        boost_pct = sum(1 for v in regime_dict.values() if v) / len(period_dates) * 100
        tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)

        rows = []
        for name, ts_p, sl_p in variants:
            r = tsim.run_regime(
                defense_params=V80_D, offense_params=V80_O,
                regime_dict=regime_dict,
                trailing_stop=ts_p, stop_loss=sl_p,
                g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
                g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
                g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
                g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
            )
            rows.append({
                '전략': name,
                'CAGR': r['cagr'], 'MDD': r['mdd'],
                'Cal': r['calmar'], 'Sharpe': r['sharpe'],
                'Sortino': r['sortino'],
            })
            yearly_data[name][yr] = r

        df = pd.DataFrame(rows)
        # 우승자 확인 (Calmar 기준)
        winner_idx = df['Cal'].idxmax()
        winner = df.iloc[winner_idx]['전략'].split('.')[0]
        print(f'[{yr}] (boost {boost_pct:.0f}%): 우승자 = {winner}')
        print(df.to_string(index=False))
        print()

    # 전체 7.8년
    print('\n=== 7.8년 전체 (2018-07~2026-05) ===')
    period_dates = [d for d in common if '20180702' <= d <= '20260506']
    regime_dict = calc_regime(period_dates, kospi, ma170)
    tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)
    full_rows = []
    for name, ts_p, sl_p in variants:
        r = tsim.run_regime(
            defense_params=V80_D, offense_params=V80_O,
            regime_dict=regime_dict,
            trailing_stop=ts_p, stop_loss=sl_p,
            g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
            g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
            g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
            g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
        )
        rets = np.asarray(r['_daily_rets'])
        m = metrics_from_rets(rets)
        full_rows.append({
            '전략': name,
            'CAGR(%)': m['cagr'], 'MDD(%)': m['mdd'],
            'Calmar': m['calmar'], 'Sharpe': m['sharpe'],
            'Sortino': m['sortino'], '승률(%)': m['winrate'],
            '누적(%)': m['total'],
        })
    print(pd.DataFrame(full_rows).to_string(index=False))

    # 연도별 우승 횟수
    print('\n=== 연도별 우승 횟수 ===')
    win_count = {v[0]: 0 for v in variants}
    for yr in years:
        if yr not in yearly_data[variants[0][0]]:
            continue
        cals = {v[0]: yearly_data[v[0]][yr]['calmar'] for v in variants}
        winner = max(cals, key=cals.get)
        win_count[winner] += 1
    for name, cnt in win_count.items():
        print(f'  {name}: {cnt}회')

    # 메모리 기록과 비교
    print('\n=== MEMORY.md 기록 vs 이번 BT ===')
    print(f'기록 v80 7.8y Cal: 3.97')
    print(f'이번 BT baseline 7.8y Cal: {full_rows[0]["Calmar"]:.2f}')
    print(f'차이는 BT 종료일/cooldown 등 미세 설정 차이 가능')


if __name__ == '__main__':
    main()
