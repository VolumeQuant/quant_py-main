"""G 서브팩터 조합 BT — rev_accel_z(=QoQ 가속도) 추가 효과 검증

가설: 링네트 사례처럼 TTM YoY는 좋지만 가속도(QoQ-like)가 나쁜 종목 거르기.
방법: 기존 v80 (rev+oca 2팩터) vs rev_accel/op_margin 포함 변형 비교.
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

    # G 서브팩터 조합 변형
    # 2팩터: g_sub1, g_sub2, g_rev_weight 사용 (G_SUB3=None)
    # 3팩터: g_sub1, g_sub2, g_sub3 + g_w1, g_w2, g_w3
    variants = [
        # (name, sub1, sub2, sub3, w1, w2, w3)
        ('A. v80 baseline (rev+oca 60/40)',     'rev_z', 'oca_z', None, None, None, None),
        ('B. 3f rev+oca+rev_accel 50/30/20',    'rev_z', 'oca_z', 'rev_accel_z', 0.5, 0.3, 0.2),
        ('C. 3f rev+oca+rev_accel 40/30/30',    'rev_z', 'oca_z', 'rev_accel_z', 0.4, 0.3, 0.3),
        ('D. 3f rev+rev_accel+op_margin',        'rev_z', 'rev_accel_z', 'op_margin_z', 0.5, 0.25, 0.25),
        ('E. 3f rev+oca+op_margin 50/30/20',    'rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2),
        ('F. v79 style rev+oca+gp 50/30/20',    'rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),
    ]

    periods = [
        ('2026 YTD',           '20260102', '20260511'),
        ('2024~2026 (2.3y)',  '20240102', '20260511'),
        ('2018~2026 (7.8y)',  '20180702', '20260511'),
    ]

    all_rows = []
    for label, ps, pe in periods:
        period_dates = [d for d in common if ps <= d <= pe]
        if not period_dates: continue
        regime_dict = calc_regime(period_dates, kospi, ma170)
        tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)

        print(f'\n=== {label} ({len(period_dates)}일) ===')
        rows = []
        for name, s1, s2, s3, w1, w2, w3 in variants:
            if s3 is None:
                # 2팩터: 기존 g_rev_w 사용
                r = tsim.run_regime(
                    defense_params=V80_D, offense_params=V80_O,
                    regime_dict=regime_dict,
                    trailing_stop=-0.10, stop_loss=-0.07,
                    g_sub1_o=s1, g_sub2_o=s2, g_sub3_o=None,
                    g_w1_o=None, g_w2_o=None, g_w3_o=None,
                    g_sub1_d='rev_z', g_sub2_d='oca_z', g_sub3_d=None,
                    g_w1_d=None, g_w2_d=None, g_w3_d=None,
                )
            else:
                r = tsim.run_regime(
                    defense_params=V80_D, offense_params=V80_O,
                    regime_dict=regime_dict,
                    trailing_stop=-0.10, stop_loss=-0.07,
                    g_sub1_o=s1, g_sub2_o=s2, g_sub3_o=s3,
                    g_w1_o=w1, g_w2_o=w2, g_w3_o=w3,
                    g_sub1_d='rev_z', g_sub2_d='oca_z', g_sub3_d=None,
                    g_w1_d=None, g_w2_d=None, g_w3_d=None,
                )
            rows.append({
                '전략': name,
                'CAGR': r['cagr'], 'MDD': r['mdd'],
                'Cal': r['calmar'], 'Sharpe': r['sharpe'],
                'Sortino': r['sortino'], 'total': r['total'],
            })
        df = pd.DataFrame(rows).sort_values('Cal', ascending=False).reset_index(drop=True)
        df.insert(0, 'rank', df.index + 1)
        print(df.to_string(index=False))
        for r in rows:
            all_rows.append({'기간': label, **r})

    pd.DataFrame(all_rows).to_csv(
        r'C:\dev\backtest\g_subfactor_result.csv',
        index=False, encoding='utf-8-sig')


if __name__ == '__main__':
    main()
