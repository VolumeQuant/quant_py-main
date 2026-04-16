"""C(필터 없음) ranking에서 사후 필터 적용 → 4옵션 TurboSim Phase 8 비교

옵션 C ranking에 모든 종목 z-score 포함 → 사후에:
  baseline: V/Q/G/M 중 하나라도 < -1.5 제외
  A: V/Q/G/M 중 하나라도 < -2.0 제외
  B: Q/G/M 중 하나라도 < -1.5 제외 (V 면제)
  C: 필터 없음 (원본 그대로)
  D: (V/Q/G/M 중 하나 < -1.5) AND (Q+G+M 평균 ≤ 0) 제외

각 옵션별 ranking을 TurboSim에 넘겨 7.8y + 5.25y 성과 비교.
"""
import sys, os, json, glob, time
from pathlib import Path
sys.path.insert(0, 'C:/dev/backtest')
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator


def load_rankings_from_dir(boost_dir, defense_dir):
    """boost + defense ranking 로드 (TurboSim용)"""
    data = {}
    for d in [Path(boost_dir), Path(defense_dir)]:
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8: continue
            if k not in data:
                data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


def apply_filter(rankings_data, mode):
    """ranking_data의 각 날짜에서 사후 필터 적용 → 필터된 rankings 반환"""
    filtered = {}
    for date_str, data in rankings_data.items():
        ranks = data.get('rankings', [])
        if mode == 'C':
            kept = ranks  # 필터 없음
        elif mode == 'baseline':
            kept = [r for r in ranks if all(
                r.get(f, 0) >= -1.5 for f in ['value_s', 'quality_s', 'momentum_s']
            ) and r.get('score', 0) >= -1.5]  # score는 growth 포함 종합
        elif mode == 'A':
            kept = [r for r in ranks if all(
                r.get(f, 0) >= -2.0 for f in ['value_s', 'quality_s', 'momentum_s']
            )]
        elif mode == 'B':
            kept = [r for r in ranks if all(
                r.get(f, 0) >= -1.5 for f in ['quality_s', 'momentum_s']
            )]  # V 면제
        elif mode == 'D':
            def d_pass(r):
                v, q, m = r.get('value_s', 0), r.get('quality_s', 0), r.get('momentum_s', 0)
                qgm_avg = (q + m) / 2  # growth는 score에 포함
                any_below = v < -1.5 or q < -1.5 or m < -1.5
                return not (any_below and qgm_avg <= 0)
            kept = [r for r in ranks if d_pass(r)]
        else:
            kept = ranks

        filtered[date_str] = kept
    return filtered


# C ranking 경로
C_BOOST = Path('C:/dev/backtest/extreme_C_boost')
C_DEFENSE = Path('C:/dev/backtest/extreme_C_defense')
C_BOOST_EXT = Path('C:/dev/backtest/extreme_C_boost_ext')
C_DEFENSE_EXT = Path('C:/dev/backtest/extreme_C_defense_ext')

print('C ranking 로드...', flush=True)
boost_rd = load_rankings_from_dir(C_BOOST_EXT, C_BOOST)  # 2018~2026
defense_rd = load_rankings_from_dir(C_DEFENSE_EXT, C_DEFENSE)

dates = sorted(set(boost_rd) & set(defense_rd))
print(f'  dates: {len(dates)} ({dates[0]}~{dates[-1]})')

# OHLCV
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

# KOSPI regime
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()


def calc_regime(target_dates, confirm=7):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma200.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg


sub_dates = [d for d in dates if '20210104' <= d <= '20260415']
reg_78 = calc_regime(dates, 7)
reg_525 = calc_regime(sub_dates, 7)

# v79 파라미터
OFFENSE = {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,'entry':3,'exit':6,'slots':3,'mom':'12m'}
DEFENSE = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}
O_GS = ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
D_GS = ('rev_z','oca_z',None,None,None,None)

OPTIONS = ['baseline', 'A', 'B', 'C', 'D']

print('\n=== 4옵션 BT 비교 ===')
results = []

for opt in OPTIONS:
    t0 = time.time()
    # 사후 필터 적용
    boost_filtered = apply_filter({d: boost_rd[d] for d in dates}, opt)
    defense_filtered = apply_filter({d: defense_rd[d] for d in dates}, opt)

    # TurboSim용 rankings
    boost_rk = {d: boost_filtered[d] for d in dates}
    sub_boost_rk = {d: boost_filtered[d] for d in sub_dates}

    tsim_78 = TurboSimulator(boost_rk, dates, ohlcv)
    tsim_525 = TurboSimulator(sub_boost_rk, sub_dates, ohlcv)

    try:
        r78 = tsim_78.run_regime(
            defense_params=DEFENSE, offense_params=OFFENSE,
            regime_dict=reg_78, trailing_stop=-0.15,
            g_sub1_o=O_GS[0],g_sub2_o=O_GS[1],g_sub3_o=O_GS[2],
            g_w1_o=O_GS[3],g_w2_o=O_GS[4],g_w3_o=O_GS[5],
            g_sub1_d=D_GS[0],g_sub2_d=D_GS[1],g_sub3_d=D_GS[2],
            g_w1_d=D_GS[3],g_w2_d=D_GS[4],g_w3_d=D_GS[5],
        )
        r525 = tsim_525.run_regime(
            defense_params=DEFENSE, offense_params=OFFENSE,
            regime_dict=reg_525, trailing_stop=-0.15,
            g_sub1_o=O_GS[0],g_sub2_o=O_GS[1],g_sub3_o=O_GS[2],
            g_w1_o=O_GS[3],g_w2_o=O_GS[4],g_w3_o=O_GS[5],
            g_sub1_d=D_GS[0],g_sub2_d=D_GS[1],g_sub3_d=D_GS[2],
            g_w1_d=D_GS[3],g_w2_d=D_GS[4],g_w3_d=D_GS[5],
        )
        elapsed = time.time() - t0
        results.append({
            'option': opt,
            'cal_78': r78['calmar'], 'cagr_78': r78['cagr'], 'mdd_78': r78['mdd'],
            'cal_525': r525['calmar'], 'cagr_525': r525['cagr'], 'mdd_525': r525['mdd'],
            'score': r78['calmar']*0.5 + r525['calmar']*0.5,
            'time': elapsed,
        })
        print(f'  {opt:>10}: 7.8y Cal={r78["calmar"]:.2f} CAGR={r78["cagr"]:.1f}% MDD={r78["mdd"]:.1f}%  |  '
              f'5.25y Cal={r525["calmar"]:.2f}  |  score={r78["calmar"]*0.5+r525["calmar"]*0.5:.2f}  ({elapsed:.1f}s)')
    except Exception as e:
        print(f'  {opt:>10}: ERR {str(e)[:60]}')

# 요약
print(f'\n=== 요약 (score = cal_78*0.5 + cal_525*0.5) ===')
df = pd.DataFrame(results).sort_values('score', ascending=False)
print(df[['option','cal_78','cagr_78','mdd_78','cal_525','score']].to_string(index=False))
