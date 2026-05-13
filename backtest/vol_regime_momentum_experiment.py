"""변동성 regime-aware 모멘텀 (Barroso-Santa-Clara 2015 응용)

가설: 변동성 spike → 모멘텀 알파 crash 위험 → 노출 자동 축소
구현: M_adjusted = M_original × (1 - vol_penalty)
       penalty = min(1, (vol_5d/vol_60d - threshold) / threshold) × max_scale

vs baseline: 같은 v80 (E3X6S3) + regime switching
"""
import sys, json, copy
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
        if not d.exists():
            continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8 or not k.isdigit():
                continue
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


def compute_vol_penalty_matrix(price_df, dates, lookback_short=5, lookback_long=60,
                                threshold=1.5, max_scale=0.5):
    """종목별 (date, ticker) → vol penalty (0~max_scale)
    1.0 = 변동성 정상 → penalty 0
    1.5 이상 → 점진 증가, max_scale 도달
    """
    rets = price_df.pct_change()
    vol_short = rets.rolling(lookback_short).std()
    vol_long = rets.rolling(lookback_long).std()
    ratio = vol_short / vol_long.replace(0, np.nan)
    excess = (ratio - threshold).clip(lower=0)
    penalty = (excess / threshold).clip(upper=1) * max_scale  # 0 ~ max_scale
    return penalty.fillna(0)


def apply_vol_penalty_to_rankings(rk_data, penalty_df, dates):
    """ranking dict의 momentum_s에 vol penalty 적용 → 새 dict 반환"""
    new_rk = {}
    for d in dates:
        if d not in rk_data:
            continue
        ts = pd.Timestamp(d)
        if ts not in penalty_df.index:
            new_rk[d] = rk_data[d]
            continue
        pen_row = penalty_df.loc[ts]
        new_list = []
        for r in rk_data[d]:
            r2 = dict(r)
            t = r['ticker']
            if t in pen_row.index:
                pen = pen_row[t]
                if pd.notna(pen) and pen > 0:
                    r2['momentum_s'] = float(r['momentum_s']) * (1.0 - float(pen))
                    # 4종 모멘텀에도 동일 적용
                    for col in ['mom_6m_s', 'mom_6m1m_s', 'mom_12m_s', 'mom_12m1m_s']:
                        if col in r2 and r2[col] is not None:
                            r2[col] = float(r2[col]) * (1.0 - float(pen))
            new_list.append(r2)
        new_rk[d] = new_list
    return new_rk


def main():
    print('데이터 로드...', flush=True)
    boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
    defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
    common = sorted(set(boost) & set(defense))
    rk_boost_orig = {d: boost[d]['rankings'] if isinstance(boost[d], dict) else boost[d] for d in common}

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

    # 변형 (threshold, max_scale)
    variants = [
        ('baseline (no penalty)',  None, None),
        ('vol_pen [1.5, 0.3]',     1.5, 0.3),
        ('vol_pen [1.5, 0.5]',     1.5, 0.5),
        ('vol_pen [1.5, 0.7]',     1.5, 0.7),
        ('vol_pen [2.0, 0.5]',     2.0, 0.5),
        ('vol_pen [1.2, 0.5]',     1.2, 0.5),  # aggressive (낮은 threshold)
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

        rows = []
        for name, thr, scale in variants:
            if thr is None:
                rk_used = {d: rk_boost_orig[d] for d in period_dates}
            else:
                pen_df = compute_vol_penalty_matrix(ohlcv, period_dates,
                                                    threshold=thr, max_scale=scale)
                rk_used = apply_vol_penalty_to_rankings(rk_boost_orig, pen_df, period_dates)
            tsim = TurboSimulator(rk_used, period_dates, ohlcv)
            r = tsim.run_regime(
                defense_params=V80_D, offense_params=V80_O,
                regime_dict=regime_dict,
                trailing_stop=-0.15, stop_loss=-0.10,
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
        r'C:\dev\backtest\vol_regime_momentum_result.csv',
        index=False, encoding='utf-8-sig')
    print(f'\n결과 저장')


if __name__ == '__main__':
    main()
