"""Factor Momentum Phase 2 — 동적 tilt 선택 BT (Gupta-Kelly 2019)

각 tilt를 정적으로 BT한 daily returns를 받아,
매일 과거 N일 cum-return으로 최선 tilt 선택 (또는 softmax 가중 ensemble).

UPPER BOUND 성격: 무거래비용, seamless 전환 가정.
이 정도로도 baseline 못 이기면 factor momentum 실패.
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


def calc_metrics(rets):
    rets = np.asarray(rets, dtype=np.float64)
    n = len(rets)
    if n == 0 or rets.std() == 0:
        return {'cagr': 0, 'mdd': 0, 'calmar': 0, 'sharpe': 0, 'total': 0}
    equity = np.cumprod(1 + rets)
    total = (equity[-1] - 1) * 100
    cagr = (equity[-1] ** (252/n) - 1) * 100
    sharpe = rets.mean() / rets.std() * np.sqrt(252)
    eq2 = np.empty(n+1); eq2[0]=1; eq2[1:]=equity
    peak = np.maximum.accumulate(eq2)
    mdd = abs(((eq2-peak)/peak).min()) * 100
    calmar = cagr / mdd if mdd > 0 else 0
    return {'cagr': round(cagr,2), 'mdd': round(mdd,2),
            'calmar': round(calmar,3), 'sharpe': round(sharpe,3),
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

    tilts = {
        'V':       {'v':0.40,'q':0.00,'g':0.30,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'},
        'G':       {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'},
        'M':       {'v':0.15,'q':0.00,'g':0.30,'m':0.55,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'},
        'Balanced':{'v':0.25,'q':0.00,'g':0.40,'m':0.35,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'},
        'Q':       {'v':0.15,'q':0.20,'g':0.35,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'},
    }
    GS = ('rev_z','oca_z',None,None,None,None)

    # 7.8년 전체 기간 사용
    ps, pe = '20180702', '20260506'
    period_dates = [d for d in common if ps <= d <= pe]
    regime_dict = calc_regime(period_dates, kospi, ma170)
    n = len(period_dates)
    print(f'기간: {ps} ~ {pe}, {n}일')

    # 각 tilt 정적 BT → daily returns 추출
    tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)
    tilt_rets = {}
    print('정적 tilt BT 실행...')
    for name, ofs in tilts.items():
        r = tsim.run_regime(
            defense_params=V80_D, offense_params=ofs,
            regime_dict=regime_dict,
            trailing_stop=-0.15, stop_loss=-0.10,
            g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
            g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
            g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
            g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
        )
        rets = np.asarray(r['_daily_rets'], dtype=np.float64)
        tilt_rets[name] = rets
        print(f'  {name:10s}: Cal {r["calmar"]:.2f}, CAGR {r["cagr"]:.1f}%, MDD {r["mdd"]:.1f}%')

    tilt_names = list(tilt_rets.keys())
    tilt_arr = np.stack([tilt_rets[t] for t in tilt_names])  # (n_tilts, n_dates)

    # === 동적 선택 전략들 ===
    print('\n=== 동적 tilt 선택 BT ===')
    rows = []

    # Baseline: G-tilt 정적
    rows.append({'전략': 'Static G-tilt (baseline)', **calc_metrics(tilt_rets['G'])})

    # 변형: lookback × 결정 방식
    lookbacks = [30, 60, 120, 252]
    decisions = ['top1', 'top2_avg', 'softmax']

    for lb in lookbacks:
        for decision in decisions:
            dyn_rets = np.zeros(n)
            for i in range(n):
                if i < lb:
                    # warmup: G-tilt 사용
                    dyn_rets[i] = tilt_arr[tilt_names.index('G')][i]
                    continue
                # 과거 lb일 cum-return per tilt
                cum_rets = np.array([
                    np.prod(1 + tilt_arr[t_idx, i-lb:i]) - 1
                    for t_idx in range(len(tilt_names))
                ])
                if decision == 'top1':
                    chosen = np.argmax(cum_rets)
                    dyn_rets[i] = tilt_arr[chosen, i]
                elif decision == 'top2_avg':
                    top2 = np.argsort(-cum_rets)[:2]
                    dyn_rets[i] = tilt_arr[top2, i].mean()
                elif decision == 'softmax':
                    # softmax with temperature 0.5 (sharper)
                    z = cum_rets * 5
                    z -= z.max()
                    w = np.exp(z) / np.exp(z).sum()
                    dyn_rets[i] = (w * tilt_arr[:, i]).sum()
            label = f'Dyn lb={lb}d {decision}'
            rows.append({'전략': label, **calc_metrics(dyn_rets)})

    df = pd.DataFrame(rows).sort_values('calmar', ascending=False).reset_index(drop=True)
    df.insert(0, '순위', df.index + 1)
    df.columns = ['순위','전략','CAGR(%)','MDD(%)','Calmar','Sharpe','누적(%)']
    print(df.to_string(index=False))

    # 추가 분석: 어떤 tilt가 매일 선택됐는지 (lookback=60, top1)
    print('\n=== 동적 선택 빈도 (lb=60d, top1) ===')
    lb = 60
    chosen_counts = {t: 0 for t in tilt_names}
    for i in range(n):
        if i < lb:
            chosen_counts['G'] += 1
            continue
        cum_rets = np.array([
            np.prod(1 + tilt_arr[t_idx, i-lb:i]) - 1
            for t_idx in range(len(tilt_names))
        ])
        chosen = tilt_names[np.argmax(cum_rets)]
        chosen_counts[chosen] += 1
    for t, c in sorted(chosen_counts.items(), key=lambda x: -x[1]):
        print(f'  {t:10s}: {c}일 ({c/n*100:.1f}%)')

    df.to_csv(r'C:\dev\backtest\factor_momentum_phase2_result.csv',
              index=False, encoding='utf-8-sig')
    print(f'\n저장: backtest/factor_momentum_phase2_result.csv')


if __name__ == '__main__':
    main()
