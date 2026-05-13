"""B-2, B-3, B-4 종합 BT
B-2: stop_loss 변형 (TS -8% 고정)
B-3: take_profit 추가 (TS -8%, SL -10%)
B-4: 변동성 regime-aware TS (KOSPI 30d vol 기반 동적)
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


def calc_vol_regime(target_dates, kospi, lookback=30):
    """KOSPI 30d realized vol 기반 high/low vol regime
    True = high vol (vol > rolling median), False = low vol"""
    rets = kospi.pct_change()
    vol = rets.rolling(lookback).std() * np.sqrt(252)
    vol_med = vol.rolling(252).median()
    out = {}
    for d in target_dates:
        ts = pd.Timestamp(d)
        v = vol.get(ts)
        m = vol_med.get(ts)
        if v is None or pd.isna(v) or pd.isna(m):
            out[d] = False
        else:
            out[d] = v > m
    return out


def metrics_from_rets(rets):
    rets = np.asarray(rets, dtype=np.float64)
    n = len(rets)
    if n == 0 or rets.std() == 0:
        return {'cagr': 0, 'mdd': 0, 'calmar': 0, 'sharpe': 0, 'total': 0}
    eq = np.cumprod(1 + rets); total = (eq[-1]-1)*100
    cagr = (eq[-1]**(252/n) - 1)*100
    sharpe = rets.mean()/rets.std()*np.sqrt(252)
    eq2 = np.empty(n+1); eq2[0]=1; eq2[1:]=eq
    peak = np.maximum.accumulate(eq2)
    mdd = abs(((eq2-peak)/peak).min())*100
    cal = cagr/mdd if mdd > 0 else 0
    return {'cagr': round(cagr,2), 'mdd': round(mdd,2),
            'calmar': round(cal,3), 'sharpe': round(sharpe,3),
            'total': round(total,2)}


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

    ps, pe = '20180702', '20260506'
    period_dates = [d for d in common if ps <= d <= pe]
    regime_dict = calc_regime(period_dates, kospi, ma170)
    vol_regime = calc_vol_regime(period_dates, kospi)
    n = len(period_dates)
    print(f'기간: {ps} ~ {pe}, {n}일')
    high_vol_pct = sum(1 for v in vol_regime.values() if v) / n * 100
    print(f'  high-vol regime: {high_vol_pct:.0f}%')

    tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)

    def run(ts, sl, tp=None):
        return tsim.run_regime(
            defense_params=V80_D, offense_params=V80_O,
            regime_dict=regime_dict,
            trailing_stop=ts, stop_loss=sl, take_profit=tp,
            g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
            g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
            g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
            g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
        )

    rows = []

    # baseline
    print('\n=== Baseline ===')
    r = run(-0.15, -0.10, None)
    rows.append({'전략': 'v80 baseline (TS-15%, SL-10%)', **{k:r[k] for k in ['cagr','mdd','calmar','sharpe','total']}})

    # B-2: stop_loss tightening (TS=-8% 고정)
    print('\n=== B-2: SL 변형 (TS=-8%) ===')
    for sl in [-0.07, -0.08, -0.10, -0.12, -0.15]:
        r = run(-0.08, sl, None)
        rows.append({'전략': f'B2: TS-8% SL{int(sl*100)}%', **{k:r[k] for k in ['cagr','mdd','calmar','sharpe','total']}})

    # B-3: take_profit (TS=-8%, SL=-10%)
    print('\n=== B-3: TP 추가 (TS=-8%, SL=-10%) ===')
    for tp in [0.30, 0.50, 0.75, 1.00, 1.50, 2.00]:
        r = run(-0.08, -0.10, tp)
        rows.append({'전략': f'B3: TS-8% TP+{int(tp*100)}%', **{k:r[k] for k in ['cagr','mdd','calmar','sharpe','total']}})

    # B-4: 변동성 regime-aware TS
    print('\n=== B-4: vol-regime aware TS ===')
    # 두 개 BT 돌려서 vol regime에 따라 daily ret 골라쓰기
    r_tight = run(-0.08, -0.10, None)  # high vol day → tight TS
    r_loose = run(-0.15, -0.10, None)  # low vol day → loose TS
    rets_tight = np.asarray(r_tight['_daily_rets'])
    rets_loose = np.asarray(r_loose['_daily_rets'])
    # 동적 결합
    for label, hi_idx, lo_idx in [
        ('B4: HV→TS-8% / LV→TS-15%', rets_tight, rets_loose),
        ('B4: HV→TS-15% / LV→TS-8% (역)', rets_loose, rets_tight),
    ]:
        dyn_rets = np.zeros(n)
        for i, d in enumerate(period_dates):
            dyn_rets[i] = hi_idx[i] if vol_regime[d] else lo_idx[i]
        rows.append({'전략': label, **metrics_from_rets(dyn_rets)})

    # B-4 변형: 손절도 같이
    rets_tight_sl = np.asarray(run(-0.08, -0.07, None)['_daily_rets'])
    rets_loose_sl = np.asarray(run(-0.15, -0.10, None)['_daily_rets'])
    dyn_rets = np.zeros(n)
    for i, d in enumerate(period_dates):
        dyn_rets[i] = rets_tight_sl[i] if vol_regime[d] else rets_loose_sl[i]
    rows.append({'전략': 'B4: HV→TS-8% SL-7% / LV→TS-15% SL-10%',
                 **metrics_from_rets(dyn_rets)})

    df = pd.DataFrame(rows).sort_values('calmar', ascending=False).reset_index(drop=True)
    df.insert(0, '순위', df.index + 1)
    df.columns = ['순위','전략','CAGR(%)','MDD(%)','Calmar','Sharpe','누적(%)']
    print('\n=== 전체 결과 (7.8년) ===')
    print(df.to_string(index=False))
    df.to_csv(r'C:\dev\backtest\b2b3b4_result.csv', index=False, encoding='utf-8-sig')


if __name__ == '__main__':
    main()
