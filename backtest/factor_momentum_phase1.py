"""Factor Momentum Phase 1 — 시기별 최선 tilt 다양성 측정

Gupta-Kelly (2019) 가설: 어느 팩터가 최근 알파를 내는지 시간에 따라 변동
→ 동적 가중 의미 있음

검증: 각 연도별로 4종 tilt 중 어느 것이 최선 Calmar였는지 확인.
모든 연도에 같은 tilt가 최선 → 동적 의미 없음.
연도별로 변동 → 동적 가능성 큼.
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

    # offense tilt 후보 (defense는 v80 고정)
    tilts = [
        ('V-tilt',     {'v':0.40,'q':0.00,'g':0.30,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}),
        ('G-tilt(=v80)', {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}),
        ('M-tilt',     {'v':0.15,'q':0.00,'g':0.30,'m':0.55,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}),
        ('Balanced',   {'v':0.25,'q':0.00,'g':0.40,'m':0.35,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}),
        ('Q-tilt',     {'v':0.15,'q':0.20,'g':0.35,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}),
    ]

    GS = ('rev_z','oca_z',None,None,None,None)

    # 연도별 + 전체
    years = ['2018','2019','2020','2021','2022','2023','2024','2025','2026']
    periods = [(y, f'{y}0101', f'{y}1231') for y in years]
    periods.append(('2018~2026 (전체)', '20180702', '20260506'))

    summary = {}  # tilt → list of yearly Calmar
    yearly_winners = {}  # year → winner tilt

    for label, ps, pe in periods:
        period_dates = [d for d in common if ps <= d <= pe]
        if len(period_dates) < 50:
            continue
        regime_dict = calc_regime(period_dates, kospi, ma170)
        boost_pct = sum(1 for v in regime_dict.values() if v) / len(regime_dict) * 100
        tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)

        rows = []
        for name, ofs in tilts:
            r = tsim.run_regime(
                defense_params=V80_D, offense_params=ofs,
                regime_dict=regime_dict,
                trailing_stop=-0.15, stop_loss=-0.10,
                g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
                g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
                g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
                g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
            )
            rows.append({'tilt': name, 'CAGR': r['cagr'], 'MDD': r['mdd'],
                          'Calmar': r['calmar'], 'Sharpe': r['sharpe']})
            summary.setdefault(name, []).append((label, r['calmar'], r['cagr']))

        df = pd.DataFrame(rows).sort_values('Calmar', ascending=False)
        winner = df.iloc[0]['tilt']
        yearly_winners[label] = (winner, df.iloc[0]['Calmar'])
        print(f'\n[{label}] (boost {boost_pct:.0f}% / defense {100-boost_pct:.0f}%)')
        print(df.to_string(index=False))

    # 우승 빈도
    print('\n' + '='*60)
    print('연도별 우승 tilt:')
    win_counter = {}
    for yr, (w, cal) in yearly_winners.items():
        if yr.startswith('20'):
            print(f'  {yr}: {w} (Cal {cal:.2f})')
            win_counter[w] = win_counter.get(w, 0) + 1
    print('\n전체 우승 카운트:')
    for tilt, cnt in sorted(win_counter.items(), key=lambda x: -x[1]):
        print(f'  {tilt}: {cnt}회')

    # 다양성 측정
    print('\nTilt 별 연도별 Calmar:')
    for tilt, results in summary.items():
        cals = [c for _, c, _ in results if not _.startswith('2018~')]
        if cals:
            print(f'  {tilt:15s} mean={np.mean(cals):.2f} std={np.std(cals):.2f} min={min(cals):.2f} max={max(cals):.2f}')


if __name__ == '__main__':
    main()
