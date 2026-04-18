"""v80 국면 Step 2+3+4: KOSPI MA 촘촘 + 보조 조합 + WF"""
import sys, os, json, glob, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator
from pathlib import Path

def load_rankings(dirs):
    data = {}
    for d in dirs:
        d = Path(d)
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8: continue
            if k not in data:
                with open(fp, 'r', encoding='utf-8') as f:
                    data[k] = json.load(f)
    return data

PROJECT = Path(__file__).parent.parent
print('데이터 로드...', flush=True)
boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
dates = sorted(set(boost) & set(defense))
rk = {d: boost[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)

kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kospi = kospi_df.iloc[:, 0].fillna(kospi_df['kospi']).sort_index()
kosdaq = pd.read_parquet(PROJECT/'data_cache'/'kosdaq_yf_full.parquet')['kosdaq'].sort_index()
vix = pd.read_parquet(PROJECT/'data_cache'/'vix_yf_full.parquet')['vix'].sort_index()
vix_lag = vix.shift(1)

kospi_mas = {n: kospi.rolling(n).mean() for n in range(80, 210, 10)}
kosdaq_mas = {n: kosdaq.rolling(n).mean() for n in [100, 120, 150]}

PERIODS = {'7.8y': ('20180702','20260414'), '5.25y': ('20210104','20260414')}
WF = {'2018H2-19':('20180702','20191231'),'2020-21':('20200102','20211230'),
      '2022-23':('20220103','20231228'),'2024-26':('20240102','20260414')}

tsims = {}
for pname, (ps, pe) in {**PERIODS, **WF}.items():
    pd_ = [d for d in dates if ps <= d <= pe]
    if len(pd_) >= 20:
        tsims[pname] = (pd_, TurboSimulator({d: rk[d] for d in pd_}, pd_, ohlcv))

V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS_O = ('rev_z','oca_z',None,None,None,None)
GS_D = ('rev_z','oca_z',None,None,None,None)

def build_regime(target_dates, rule_fn, confirm):
    reg = {}; mode = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d)
        try: s = rule_fn(ts)
        except: s = False
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and mode != s: mode = s
        reg[d] = mode
    return reg

def run_full(regime_map, periods=None):
    if periods is None: periods = ['7.8y','5.25y']
    res = {}
    for pname in periods:
        if pname not in tsims: continue
        pd_, tsim = tsims[pname]
        reg = {d: regime_map.get(d, False) for d in pd_}
        r = tsim.run_regime(defense_params=V80_D, offense_params=V80_O,
            regime_dict=reg, trailing_stop=-0.15,
            g_sub1_o=GS_O[0],g_sub2_o=GS_O[1],g_sub3_o=GS_O[2],
            g_w1_o=GS_O[3],g_w2_o=GS_O[4],g_w3_o=GS_O[5],
            g_sub1_d=GS_D[0],g_sub2_d=GS_D[1],g_sub3_d=GS_D[2],
            g_w1_d=GS_D[3],g_w2_d=GS_D[4],g_w3_d=GS_D[5])
        res[pname] = r
    return res

def calc_score(res):
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    return (c78*c525)**0.5 if c78>0 and c525>0 else 0

print('초기화 완료\n', flush=True)

# ════════════════════════════════════════
# Step 2: KOSPI MA 촘촘 탐색
# ════════════════════════════════════════
print('='*60)
print('Step 2: KOSPI MA 촘촘 탐색 (MA80~200 x 확인3~15)')
print('='*60, flush=True)

results_2 = []
for ma_n in range(80, 210, 10):
    ma = kospi_mas[ma_n]
    for cd in range(3, 16):
        reg = build_regime(dates, lambda ts, m=ma: kospi.get(ts,0) > m.get(ts,0), cd)
        res = run_full(reg)
        sc = calc_score(res)
        sw = sum(1 for i in range(1, len(dates)) if reg.get(dates[i]) != reg.get(dates[i-1]))
        c78 = res.get('7.8y',{}).get('calmar',0)
        c525 = res.get('5.25y',{}).get('calmar',0)
        results_2.append(('KP_MA%d_%dd' % (ma_n, cd), ma_n, cd, c78, c525, sc, sw))
    print('  MA%d 완료 (%d조합)' % (ma_n, len(results_2)), flush=True)

results_2.sort(key=lambda x: -x[5])
print('\nStep 2 완료: %d조합' % len(results_2))

print('\n=== Step 2 Top 15 ===')
for i, (label, ma_n, cd, c78, c525, sc, sw) in enumerate(results_2[:15]):
    print('  %2d. %15s: score=%.3f (7.8y=%.2f 5.25y=%.2f) sw=%d' % (i+1, label, sc, c78, c525, sw))

# 인접안정성 Top 5
print('\n=== Top 5 인접안정성 ===')
for i, (label, ma_n, cd, c78, c525, sc, sw) in enumerate(results_2[:5]):
    neighbors = [(s) for _, m, c, _, _, s, _ in results_2
                 if abs(m-ma_n) <= 10 and abs(c-cd) <= 1 and (m != ma_n or c != cd)]
    adj_mean = np.mean(neighbors) if neighbors else 0
    adj_cv = np.std(neighbors) / adj_mean if adj_mean > 0 else 999
    print('  #%d %s: base=%.3f adj_mean=%.3f CV=%.2f (n=%d)' % (i+1, label, sc, adj_mean, adj_cv, len(neighbors)))

# ════════════════════════════════════════
# Step 3: 보조 조합
# ════════════════════════════════════════
print('\n' + '='*60)
print('Step 3: KOSPI MA Top 5 + 보조 지표 조합')
print('='*60, flush=True)

top5_kp = results_2[:5]
results_3 = []

for label_kp, ma_n_kp, cd_kp, _, _, sc_base, _ in top5_kp:
    ma_kp = kospi_mas[ma_n_kp]
    results_3.append((label_kp + ' (solo)', sc_base, 0, 'solo'))

    # AND KOSDAQ
    for kd_n in [100, 120, 150]:
        ma_kd = kosdaq_mas[kd_n]
        reg = build_regime(dates,
            lambda ts, mkp=ma_kp, mkd=ma_kd: kospi.get(ts,0)>mkp.get(ts,0) and kosdaq.get(ts,0)>mkd.get(ts,0),
            cd_kp)
        res = run_full(reg)
        sc = calc_score(res)
        sw = sum(1 for i in range(1,len(dates)) if reg.get(dates[i])!=reg.get(dates[i-1]))
        results_3.append(('%s AND KD%d' % (label_kp, kd_n), sc, sw, 'AND_KD'))

    # AND VIX
    for vt in [18, 20, 23]:
        reg = build_regime(dates,
            lambda ts, mkp=ma_kp, vt_=vt: kospi.get(ts,0)>mkp.get(ts,0) and vix_lag.get(ts,20)<vt_,
            cd_kp)
        res = run_full(reg)
        sc = calc_score(res)
        sw = sum(1 for i in range(1,len(dates)) if reg.get(dates[i])!=reg.get(dates[i-1]))
        results_3.append(('%s AND VIX<%d' % (label_kp, vt), sc, sw, 'AND_VIX'))

    # 비대칭: 공격=KOSPI AND KOSDAQ, 방어=KOSPI OR VIX
    for kd_n, vt in [(120, 20), (120, 23), (150, 20)]:
        ma_kd = kosdaq_mas[kd_n]
        def asym(ts, mkp=ma_kp, mkd=ma_kd, vt_=vt):
            kp_ok = kospi.get(ts, 0) > mkp.get(ts, 0)
            kd_ok = kosdaq.get(ts, 0) > mkd.get(ts, 0)
            vix_ok = vix_lag.get(ts, 20) < vt_
            return kp_ok and kd_ok and vix_ok
        reg = build_regime(dates, asym, cd_kp)
        res = run_full(reg)
        sc = calc_score(res)
        sw = sum(1 for i in range(1,len(dates)) if reg.get(dates[i])!=reg.get(dates[i-1]))
        results_3.append(('%s ASYM(KD%d+V%d)' % (label_kp, kd_n, vt), sc, sw, 'ASYM'))

print('Step 3 완료: %d조합' % len(results_3))
results_3.sort(key=lambda x: -x[1])

print('\n=== Step 3 Top 15 ===')
for i, (label, sc, sw, typ) in enumerate(results_3[:15]):
    marker = ' *solo*' if typ == 'solo' else ''
    print('  %2d. %45s: score=%.3f sw=%d%s' % (i+1, label, sc, sw, marker))

best_solo = max([r for r in results_3 if r[3]=='solo'], key=lambda x: x[1])
best_combo = max([r for r in results_3 if r[3]!='solo'], key=lambda x: x[1])
print('\n=== 단독 vs 조합 최고 ===')
print('  solo:  %s score=%.3f' % (best_solo[0], best_solo[1]))
print('  combo: %s score=%.3f sw=%d' % (best_combo[0], best_combo[1], best_combo[2]))
print('  Delta: %+.3f' % (best_combo[1] - best_solo[1]))

# ════════════════════════════════════════
# Step 4: Top 5 WF
# ════════════════════════════════════════
print('\n' + '='*60)
print('Step 4: Top 5 WF 검증')
print('='*60, flush=True)

# Step 2 단독 Top 5로 WF
for label, ma_n, cd, c78, c525, sc, sw in results_2[:5]:
    ma = kospi_mas[ma_n]
    reg = build_regime(dates, lambda ts, m=ma: kospi.get(ts,0) > m.get(ts,0), cd)
    res = run_full(reg, periods=list(WF.keys()))
    wf_cals = [res.get(p, {}).get('calmar', 0) for p in WF]
    wf_min = min(wf_cals) if wf_cals else 0
    wf_mean = np.mean(wf_cals) if wf_cals else 0
    wf_cv = np.std(wf_cals) / wf_mean if wf_mean > 0 else 999
    print('  %s: WF=[%s] min=%.2f mean=%.2f CV=%.2f' % (
        label, ', '.join('%.2f' % c for c in wf_cals), wf_min, wf_mean, wf_cv))

pd.DataFrame(results_2, columns=['label','ma_n','confirm','cal_78','cal_525','score','switches']).to_csv(
    str(PROJECT/'backtest'/'v80_regime_step2_fine.csv'), index=False, encoding='utf-8-sig')
pd.DataFrame(results_3, columns=['label','score','switches','type']).to_csv(
    str(PROJECT/'backtest'/'v80_regime_step3_combos.csv'), index=False, encoding='utf-8-sig')
print('\n저장 완료')
