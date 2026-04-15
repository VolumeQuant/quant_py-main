"""Phase 8d: Phase 5a Top 15 공격 조합 × 섹터 cap{3,5} × defense{v77.1, v79} 재평가
(전수탐색 대신 인사이트 기반 재평가)
15 × 2 cap × 2 defense × 2 period = 120 실행. 단일 프로세스 2~3분.
"""
import sys, os, json, glob, time
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, 'C:/dev/backtest')
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator


def load_rankings(dirs):
    data = {}
    for d in dirs:
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            if len(fp.stem.replace('ranking_','')) != 8: continue
            k = fp.stem.replace('ranking_','')
            if k not in data:
                data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


STATE = Path('C:/dev/state')
STATE_D = STATE / 'defense'
BT_EXT = Path('C:/dev/backtest/bt_extended')
BT_EXT_D = Path('C:/dev/backtest/bt_extended_defense')

print('로딩...', flush=True)
t0 = time.time()
boost_rd = load_rankings([BT_EXT, STATE])
defense_rd = load_rankings([BT_EXT_D, STATE_D])
dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in dates}
sub_dates = [d for d in dates if '20210104' <= d <= '20260414']
ohlcv = pd.read_parquet(sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet('C:/dev/data_cache/kospi_yf.parquet')
kospi = kdf.iloc[:, 0].fillna(kdf['kospi']).sort_index()
ma200 = kospi.rolling(200).mean()
print(f'로딩 완료: {time.time()-t0:.1f}s')


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


def make_sector_cap(rk, cap):
    new = {}
    for d, lst in rk.items():
        sorted_lst = sorted(lst, key=lambda x: x.get('rank', 999))
        sc = defaultdict(int)
        kept = []
        for r in sorted_lst:
            sec = r.get('sector', 'UNK')
            if sc[sec] < cap:
                kept.append(dict(r)); sc[sec] += 1
        for i in range(len(kept)):
            kept[i]['rank'] = i + 1
            kept[i]['composite_rank'] = i + 1
        new[d] = kept
    return new


# TSIM 프리로드 (cap 3/5, 7.8y + 5.25y)
t_tsim = time.time()
tsims = {}
for cap in [3, 5]:
    rk_cap = make_sector_cap(boost_rk, cap)
    tsims[(cap, '78')]  = TurboSimulator(rk_cap, dates, ohlcv)
    tsims[(cap, '525')] = TurboSimulator({d: rk_cap[d] for d in sub_dates}, sub_dates, ohlcv)
print(f'TSIM 초기화 (4개): {time.time()-t_tsim:.1f}s')

reg78  = calc_regime(dates, 7)
reg525 = calc_regime(sub_dates, 7)

# Phase 5a Top 15 로드
top15 = pd.read_csv('C:/dev/backtest/phase5a_attack_grid.csv').head(15).to_dict('records')


def gs_params(label):
    if label == '3f_rev_oca_gp':  return ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
    if label == '3f_rev_oca_opm': return ('rev_z','oca_z','op_margin_z',0.5,0.3,0.2)
    return ('rev_z','oca_z',None,None,None,None)


DEFENSES = {
    'v77.1': {
        'params': {'v':0.30,'q':0.05,'g':0.10,'m':0.55,'g_rev':0.5,
                   'entry':3,'exit':6,'slots':7,'mom':'6m-1m'},
        'gs': ('rev_accel_z','op_margin_z',None,None,None,None),
    },
    'v79':  {
        'params': {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
                   'entry':3,'exit':6,'slots':7,'mom':'6m-1m'},
        'gs': ('rev_z','oca_z',None,None,None,None),
    },
}

t0 = time.time()
rows = []
for cap in [3, 5]:
    for i, c in enumerate(top15):
        gso = gs_params(c['gs'])
        ofs = {'v':c['V']/100,'q':c['Q']/100,'g':c['G']/100,'m':c['M']/100,
               'g_rev':0.5 if '3f' in c['gs'] else 0.7,
               'entry':3,'exit':6,'slots':3,'mom':c['mom']}
        for dname, dd in DEFENSES.items():
            gsd = dd['gs']
            try:
                r78 = tsims[(cap,'78')].run_regime(
                    defense_params=dd['params'], offense_params=ofs,
                    regime_dict=reg78, trailing_stop=-0.15,
                    g_sub1_o=gso[0],g_sub2_o=gso[1],g_sub3_o=gso[2],
                    g_w1_o=gso[3],g_w2_o=gso[4],g_w3_o=gso[5],
                    g_sub1_d=gsd[0],g_sub2_d=gsd[1],g_sub3_d=gsd[2],
                    g_w1_d=gsd[3],g_w2_d=gsd[4],g_w3_d=gsd[5],
                )
                r525 = tsims[(cap,'525')].run_regime(
                    defense_params=dd['params'], offense_params=ofs,
                    regime_dict=reg525, trailing_stop=-0.15,
                    g_sub1_o=gso[0],g_sub2_o=gso[1],g_sub3_o=gso[2],
                    g_w1_o=gso[3],g_w2_o=gso[4],g_w3_o=gso[5],
                    g_sub1_d=gsd[0],g_sub2_d=gsd[1],g_sub3_d=gsd[2],
                    g_w1_d=gsd[3],g_w2_d=gsd[4],g_w3_d=gsd[5],
                )
                rows.append({
                    'cap':cap, 'off_rank':i+1, 'defense':dname,
                    'V':c['V'],'Q':c['Q'],'G':c['G'],'M':c['M'],
                    'mom':c['mom'],'gs':c['gs'],
                    'cal_78':r78['calmar'],'cagr_78':r78['cagr'],'mdd_78':r78['mdd'],
                    'cal_525':r525['calmar'],'cagr_525':r525['cagr'],'mdd_525':r525['mdd'],
                })
            except Exception as ee:
                print(f'  cap={cap} off={i} def={dname}: ERR {str(ee)[:60]}')

df = pd.DataFrame(rows)
df['score'] = df['cal_525']*0.5 + df['cal_78']*0.5
df = df.sort_values('score', ascending=False)
df.to_csv('C:/dev/backtest/phase8d_cap_reoptim.csv', index=False, encoding='utf-8-sig')

print(f'\n소요: {time.time()-t0:.1f}s')
print(f'\n=== Top 10 (cap × defense × offense) ===')
cols = ['cap','defense','V','Q','G','M','mom','gs','cal_78','cal_525','cagr_78','mdd_78','score']
print(df[cols].head(10).to_string(index=False))

# cap별 Top 3
for cap in [3, 5]:
    print(f'\n=== cap={cap} Top 5 ===')
    sub = df[df['cap']==cap].head(5)
    print(sub[cols].to_string(index=False))

# 원본 v77.1 / v79 cap=99 baseline과 비교
print(f'\n=== v79 original (cap=99) baseline: 7.8y Cal 3.20, 5.25y 3.18 ===')
print(f'cap=3 Top score: {df[df["cap"]==3]["score"].max():.2f}')
print(f'cap=5 Top score: {df[df["cap"]==5]["score"].max():.2f}')
