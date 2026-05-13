"""Top N 균등배분 실험 — regime switching 포함 (공정 비교)

공격 모드(boost)에서만 entry/exit/slots 변경, 방어 모드는 v80 그대로 유지.
국면: KP_MA170_8d. KOSPI > MA170 8일 확인 → boost ↔ defense 전환.
"""
import sys, json, glob, os
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
    """KP_MA170_8d: KOSPI > MA170 8일 연속 확인 후 boost↔defense 전환"""
    reg = {}
    md = False  # 시작: defense (False=defense, True=boost)
    stk = 0
    ss = None
    for d in target_dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts)
        mv = ma170.get(ts)
        if kv is None or pd.isna(mv):
            reg[d] = md
            continue
        s = kv > mv
        if s == ss:
            stk += 1
        else:
            stk = 1
            ss = s
        if stk >= 8 and md != s:
            md = s
        reg[d] = md
    return reg


def main():
    print('데이터 로드...', flush=True)
    boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
    defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
    common = sorted(set(boost) & set(defense))
    print(f'  공격: {len(boost)}일, 방어: {len(defense)}일, 공통: {len(common)}일')

    rk_boost = {d: boost[d]['rankings'] if isinstance(boost[d], dict) else boost[d] for d in common}
    rk_defense = {d: defense[d]['rankings'] if isinstance(defense[d], dict) else defense[d] for d in common}

    ohlcv = pd.read_parquet(
        sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]
    ).replace(0, np.nan)
    kospi = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet').iloc[:, 0].dropna()
    ma170 = kospi.rolling(170).mean()

    # v80 defense는 고정
    V80_D = {'v': 0.30, 'q': 0.15, 'g': 0.15, 'm': 0.40, 'g_rev': 0.7,
             'entry': 3, 'exit': 6, 'slots': 5, 'mom': '6m-1m'}

    # 공격 모드 변형들 (defense는 v80 고정)
    OFFENSE_BASE = {'v': 0.15, 'q': 0.00, 'g': 0.55, 'm': 0.30, 'g_rev': 0.6, 'mom': '12m'}
    configs = [
        ('v80 baseline',     {**OFFENSE_BASE, 'entry': 3,  'exit': 6,  'slots': 3}),
        ('Top 3 균등',       {**OFFENSE_BASE, 'entry': 3,  'exit': 3,  'slots': 3}),
        ('Top 5 균등',       {**OFFENSE_BASE, 'entry': 5,  'exit': 5,  'slots': 5}),
        ('Top 10 균등',      {**OFFENSE_BASE, 'entry': 10, 'exit': 10, 'slots': 10}),
        ('Top 15 균등',      {**OFFENSE_BASE, 'entry': 15, 'exit': 15, 'slots': 15}),
        ('Top 20 균등',      {**OFFENSE_BASE, 'entry': 20, 'exit': 20, 'slots': 20}),
        ('Top 5 (X10)',      {**OFFENSE_BASE, 'entry': 5,  'exit': 10, 'slots': 5}),
        ('Top 10 (X15)',     {**OFFENSE_BASE, 'entry': 10, 'exit': 15, 'slots': 10}),
        ('Top 20 (X25)',     {**OFFENSE_BASE, 'entry': 20, 'exit': 25, 'slots': 20}),
    ]

    GS_O = ('rev_z', 'oca_z', None, None, None, None)  # 2팩터 (rev+oca)
    GS_D = ('rev_z', 'oca_z', None, None, None, None)

    periods = [
        ('2026 YTD',           '20260102', '20260506'),
        ('2024~2026 (2.3년)',  '20240102', '20260506'),
        ('2021~2026 (5.3년)',  '20210104', '20260506'),
        ('2018~2026 (7.8년)',  '20180702', '20260506'),
    ]

    all_rows = []
    for label, ps, pe in periods:
        print(f'\n{"="*78}\n[기간 {label}: {ps} ~ {pe}]', flush=True)
        period_dates = [d for d in common if ps <= d <= pe]
        if not period_dates:
            print('  데이터 없음 → 스킵')
            continue
        regime_dict = calc_regime(period_dates, kospi, ma170)
        boost_count = sum(1 for v in regime_dict.values() if v)
        defense_count = len(regime_dict) - boost_count
        print(f'  {len(period_dates)}일: 공격 {boost_count}일 ({boost_count/len(period_dates)*100:.0f}%) / 방어 {defense_count}일 ({defense_count/len(period_dates)*100:.0f}%)')

        # 시뮬레이터는 boost rankings만 사용 (run_regime이 내부에서 defense 자동 전환)
        # 단, 같은 인스턴스에 boost ranking 저장; defense_params 따로 적용
        tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)

        rows = []
        for name, ofs in configs:
            try:
                r = tsim.run_regime(
                    defense_params=V80_D, offense_params=ofs,
                    regime_dict=regime_dict,
                    trailing_stop=-0.15, stop_loss=-0.10,
                    g_sub1_o=GS_O[0], g_sub2_o=GS_O[1], g_sub3_o=GS_O[2],
                    g_w1_o=GS_O[3], g_w2_o=GS_O[4], g_w3_o=GS_O[5],
                    g_sub1_d=GS_D[0], g_sub2_d=GS_D[1], g_sub3_d=GS_D[2],
                    g_w1_d=GS_D[3], g_w2_d=GS_D[4], g_w3_d=GS_D[5],
                )
            except Exception as e:
                print(f'  {name}: ERROR {e}')
                continue
            rows.append({
                '전략': name,
                'E/X/S': f'{ofs["entry"]}/{ofs["exit"]}/{ofs["slots"]}',
                'CAGR(%)': r['cagr'],
                'MDD(%)': r['mdd'],
                'Calmar': r['calmar'],
                'Sharpe': r['sharpe'],
                '누적(%)': r['total'],
                '보유수': r['avg_holdings'],
            })
        df = pd.DataFrame(rows)
        df = df.sort_values('Calmar', ascending=False).reset_index(drop=True)
        df.insert(0, '순위', df.index + 1)
        print(df.to_string(index=False))
        for r in rows:
            all_rows.append({'기간': label, **r})

    out = Path(r'C:\dev\backtest\topn_regime_result.csv')
    pd.DataFrame(all_rows).to_csv(out, index=False, encoding='utf-8-sig')
    print(f'\n결과 저장: {out}')


if __name__ == '__main__':
    main()
