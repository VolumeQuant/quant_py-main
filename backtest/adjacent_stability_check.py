"""인접 안정성 테스트 — TS/SL 후보 주변 9개 조합 검증

CV < 0.3 통과 = 안정 plateau (진짜 알파)
CV > 0.3 실패 = 노이즈 spike (BT overfit 의심)
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
    # 2026-05-12: state/가 7.8년 전부 흡수. bt_extended 분리 사용 안 함
    boost = load_rankings([PROJECT/'state'])
    defense = load_rankings([PROJECT/'state'/'defense'])
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

    period_dates = [d for d in common if '20180702' <= d <= '20260506']
    regime_dict = calc_regime(period_dates, kospi, ma170)
    tsim = TurboSimulator({d: rk_boost[d] for d in period_dates}, period_dates, ohlcv)

    def run(ts, sl):
        r = tsim.run_regime(
            defense_params=V80_D, offense_params=V80_O,
            regime_dict=regime_dict,
            trailing_stop=ts, stop_loss=sl,
            g_sub1_o=GS[0], g_sub2_o=GS[1], g_sub3_o=GS[2],
            g_w1_o=GS[3], g_w2_o=GS[4], g_w3_o=GS[5],
            g_sub1_d=GS[0], g_sub2_d=GS[1], g_sub3_d=GS[2],
            g_w1_d=GS[3], g_w2_d=GS[4], g_w3_d=GS[5],
        )
        return r['calmar']

    # 후보 + 5x5 grid 인접
    candidates = [
        ('baseline (TS-15 SL-10)', -0.15, -0.10),
        ('TS-10 SL-7 (제 추천)',    -0.10, -0.07),
        ('TS-8  SL-7 (대안1)',       -0.08, -0.07),
        ('TS-8  SL-10 (대안2)',      -0.08, -0.10),
    ]

    print('=== 인접 안정성 (CV < 0.3 통과) ===\n')
    for name, ts_c, sl_c in candidates:
        # 5x5 grid: TS ± {1, 2} %p, SL ± {1, 2} %p
        ts_grid = [ts_c - 0.02, ts_c - 0.01, ts_c, ts_c + 0.01, ts_c + 0.02]
        sl_grid = [sl_c - 0.02, sl_c - 0.01, sl_c, sl_c + 0.01, sl_c + 0.02]
        cals = []
        center_cal = None
        grid_table = []
        for sl in sl_grid:
            row = []
            for ts in ts_grid:
                c = run(round(ts, 3), round(sl, 3))
                cals.append(c)
                if abs(ts - ts_c) < 0.005 and abs(sl - sl_c) < 0.005:
                    center_cal = c
                row.append(c)
            grid_table.append(row)
        cals = np.array(cals)
        cv = cals.std() / cals.mean() if cals.mean() != 0 else float('inf')
        passed = '✅' if cv < 0.3 else '❌'

        print(f'[{name}]')
        print(f'  중심 Calmar: {center_cal:.3f}')
        print(f'  25개 평균: {cals.mean():.3f}, std: {cals.std():.3f}, CV: {cv:.3f} {passed}')
        print(f'  min: {cals.min():.3f}, max: {cals.max():.3f}')
        # grid 출력
        print(f'  5x5 grid (TS axis →, SL axis ↓):')
        ts_labels = [f'{int(t*100)}%' for t in ts_grid]
        sl_labels = [f'SL{int(s*100)}%' for s in sl_grid]
        df = pd.DataFrame(grid_table, columns=ts_labels, index=sl_labels)
        print(df.round(2).to_string())
        print()


if __name__ == '__main__':
    main()
