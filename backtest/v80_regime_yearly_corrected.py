"""v80 국면 연도별 비교 — 2025 기간 수정"""
import sys, os, json, glob
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
                with open(fp, 'r', encoding='utf-8') as f: data[k] = json.load(f)
    return data

PROJECT = Path(__file__).parent.parent
boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
dates = sorted(set(boost) & set(defense))
rk = {d: boost[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kospi = kospi_df.iloc[:, 0].fillna(kospi_df['kospi']).sort_index()
vix = pd.read_parquet(PROJECT/'data_cache'/'vix_yf_full.parquet')['vix'].sort_index()
vix_lag = vix.shift(1)
ma150 = kospi.rolling(150).mean()
ma170 = kospi.rolling(170).mean()
ma200 = kospi.rolling(200).mean()

# 올바른 기간 (2025 수정!)
PERIODS = {
    '7.8y':('20180702','20260414'),
    '5.25y':('20210104','20260414'),
    '2018H2':('20180702','20181228'),
    '2019':('20190102','20191230'),
    '2020':('20200102','20201230'),
    '2021':('20210104','20211230'),
    '2022':('20220103','20221228'),
    '2023':('20230102','20231228'),
    '2024':('20240102','20241230'),
    '2025':('20250102','20251230'),  # 수정됨!
    '2026':('20260102','20260414'),
    '2018H2-19':('20180702','20191231'),
    '2020-21':('20200102','20211230'),
    '2022-23':('20220103','20231228'),
    '2024-26':('20240102','20260414'),
}

tsims = {}
for pn, (ps, pe) in PERIODS.items():
    pd_ = [d for d in dates if ps <= d <= pe]
    if len(pd_) >= 20:
        tsims[pn] = (pd_, TurboSimulator({d: rk[d] for d in pd_}, pd_, ohlcv))

V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
V79_O = {'v':0.15,'q':0.05,'g':0.50,'m':0.30,'g_rev':0.5,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V79_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':7,'mom':'6m-1m'}
V79_GS_O = ('rev_z','oca_z','gp_growth_z',0.5,0.3,0.2)
GS_2F = ('rev_z','oca_z',None,None,None,None)

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

configs = {
    'v79 (MA200_7d 3f)': {
        'off': V79_O, 'def_': V79_D, 'gs_o': V79_GS_O, 'gs_d': GS_2F,
        'regime': build_regime(dates, lambda ts: kospi.get(ts,0)>ma200.get(ts,0), 7),
    },
    'v80 MA150_10d': {
        'off': V80_O, 'def_': V80_D, 'gs_o': GS_2F, 'gs_d': GS_2F,
        'regime': build_regime(dates, lambda ts: kospi.get(ts,0)>ma150.get(ts,0), 10),
    },
    'v80 MA170_8d': {
        'off': V80_O, 'def_': V80_D, 'gs_o': GS_2F, 'gs_d': GS_2F,
        'regime': build_regime(dates, lambda ts: kospi.get(ts,0)>ma170.get(ts,0), 8),
    },
    'v80 MA170+VIX20': {
        'off': V80_O, 'def_': V80_D, 'gs_o': GS_2F, 'gs_d': GS_2F,
        'regime': build_regime(dates, lambda ts: kospi.get(ts,0)>ma170.get(ts,0) and vix_lag.get(ts,20)<20, 8),
    },
}

order = ['7.8y','5.25y','2018H2','2019','2020','2021','2022','2023','2024','2025','2026',
         '2018H2-19','2020-21','2022-23','2024-26']

results = []
for cn, cfg in configs.items():
    for pn in order:
        if pn not in tsims: continue
        pd_, tsim = tsims[pn]
        reg = {d: cfg['regime'].get(d, False) for d in pd_}
        r = tsim.run_regime(
            defense_params=cfg['def_'], offense_params=cfg['off'],
            regime_dict=reg, trailing_stop=-0.15,
            g_sub1_o=cfg['gs_o'][0],g_sub2_o=cfg['gs_o'][1],g_sub3_o=cfg['gs_o'][2],
            g_w1_o=cfg['gs_o'][3],g_w2_o=cfg['gs_o'][4],g_w3_o=cfg['gs_o'][5],
            g_sub1_d=cfg['gs_d'][0],g_sub2_d=cfg['gs_d'][1],g_sub3_d=cfg['gs_d'][2],
            g_w1_d=cfg['gs_d'][3],g_w2_d=cfg['gs_d'][4],g_w3_d=cfg['gs_d'][5])
        results.append({'config':cn,'period':pn,'cal':r['calmar'],'cagr':r['cagr'],'mdd':r['mdd']})

df = pd.DataFrame(results)
col_order = list(configs.keys())

for metric, mn in [('cal','Calmar'),('cagr','CAGR(%)'),('mdd','MDD(%)')]:
    piv = df.pivot(index='period', columns='config', values=metric)
    piv = piv.reindex([p for p in order if p in piv.index])
    piv = piv[[c for c in col_order if c in piv.columns]]
    print('\n--- %s ---' % mn)
    print(piv.round(2).to_string())

# WF
print('\n--- WF 안정성 ---')
wf_periods = ['2018H2-19','2020-21','2022-23','2024-26']
for cn in col_order:
    wf = [df[(df['config']==cn)&(df['period']==p)]['cal'].values[0] for p in wf_periods if len(df[(df['config']==cn)&(df['period']==p)]) > 0]
    if wf:
        print('  %s: WF=[%s] min=%.2f mean=%.2f CV=%.2f' % (
            cn, ', '.join('%.2f' % c for c in wf), min(wf), np.mean(wf), np.std(wf)/np.mean(wf) if np.mean(wf)>0 else 999))
