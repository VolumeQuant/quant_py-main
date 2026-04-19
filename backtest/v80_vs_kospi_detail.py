"""v80 vs KOSPI 비교 + 2025년 매매 상세"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from turbo_simulator import TurboSimulator
from pathlib import Path

PROJECT = Path(__file__).parent.parent

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

boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
dates = sorted(set(boost) & set(defense))
rk = {d: boost[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kospi = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet').iloc[:,0].dropna()
ma170 = kospi.rolling(170).mean()

def calc_regime(target_dates):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 8 and md != s: md = s
        reg[d] = md
    return reg

GS = ('rev_z','oca_z',None,None,None,None)
V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}

def get_kospi_ret(yd):
    ks = ke = None
    for d in yd[:10]:
        v = kospi.get(pd.Timestamp(d))
        if v and not pd.isna(v): ks = v; break
    for d in reversed(yd[-10:]):
        v = kospi.get(pd.Timestamp(d))
        if v and not pd.isna(v): ke = v; break
    return (ke/ks-1)*100 if ks and ke else 0

# 연도별 비교
print('='*50)
print('v80 vs KOSPI 연도별')
print('='*50)
print(f'{"연도":<7} {"v80":>9} {"KOSPI":>9} {"초과":>9}')
print('-'*40)

periods = [
    ('2018H2','20180702','20181228'), ('2019','20190102','20191230'),
    ('2020','20200102','20201230'), ('2021','20210104','20211230'),
    ('2022','20220103','20221228'), ('2023','20230102','20231228'),
    ('2024','20240102','20241230'), ('2025','20250102','20260414'),
]
for yname, ys, ye in periods:
    yd = [d for d in dates if ys <= d <= ye]
    if len(yd) < 20: continue
    yreg = calc_regime(yd)
    ytsim = TurboSimulator({d: rk[d] for d in yd}, yd, ohlcv)
    yr = ytsim.run_regime(defense_params=V80_D, offense_params=V80_O,
        regime_dict=yreg, trailing_stop=-0.15,
        g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
        g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
    k_ret = get_kospi_ret(yd)
    v_ret = yr['total']
    print(f'{yname:<7} {v_ret:>+9.1f}% {k_ret:>+9.1f}% {v_ret-k_ret:>+9.1f}%p')

# 2025 매매 추적
print(f'\n{"="*50}')
print('2025년 개별 매매 상세')
print('='*50)

yd25 = [d for d in dates if '20250102' <= d <= '20260414']
reg25 = calc_regime(yd25)

tsim_b = TurboSimulator({d: rk[d] for d in yd25}, yd25, ohlcv)
tsim_b._ensure_cache(0.15, 0.00, 0.55, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
boost_flat = list(tsim_b._cached_flat)
tsim_d2 = TurboSimulator({d: defense[d]['rankings'] for d in yd25}, yd25, ohlcv)
tsim_d2._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
defense_flat = list(tsim_d2._cached_flat)

tk_names = {}
for d in yd25[-5:]:
    for item in rk[d]:
        tk_names[item.get('ticker','')] = item.get('name','?')

col_to_tk = {i: c for i, c in enumerate(ohlcv.columns)}

portfolio = {}
trades = []
prev_regime = None

for i in range(2, len(yd25)):
    d = yd25[i]
    cr = reg25.get(d, False)
    if prev_regime is not None and cr != prev_regime:
        for col, info in portfolio.items():
            cur_row = tsim_b._date_row_indices[i]
            if cur_row >= 0:
                ep = tsim_b._price_arr[cur_row, col]
                if ep > 0 and not np.isnan(ep):
                    tk = col_to_tk.get(col,'?')
                    trades.append({'ticker':tk,'name':tk_names.get(tk,'?'),
                        'entry':yd25[info['ei']],'exit':d,
                        'ret':(ep/info['ep']-1)*100,'days':i-info['ei'],'reason':'regime'})
        portfolio.clear()
    prev_regime = cr

    pipe = boost_flat[i] if cr and i < len(boost_flat) else (defense_flat[i] if not cr and i < len(defense_flat) else None)
    entry_p, exit_p, max_s = (3,6,3) if cr else (3,6,5)
    if pipe is None: continue
    wrank_arr, cand_cols, cand_prices, cand_wranks = pipe
    cur_row = tsim_b._date_row_indices[i]
    if cur_row < 0: continue

    to_rm = []
    for col, info in portfolio.items():
        cp = tsim_b._price_arr[cur_row, col]
        if np.isnan(cp) or cp <= 0: continue
        reason = None
        if (cp/info['ep']-1) <= -0.10: reason = 'stop_loss'
        elif (cp/info['peak']-1) <= -0.15: reason = 'trailing'
        elif wrank_arr[col] > exit_p: reason = 'rank_exit'
        if cp > info['peak']: info['peak'] = cp
        if reason:
            tk = col_to_tk.get(col,'?')
            trades.append({'ticker':tk,'name':tk_names.get(tk,'?'),
                'entry':yd25[info['ei']],'exit':d,
                'ret':(cp/info['ep']-1)*100,'days':i-info['ei'],'reason':reason})
            to_rm.append(col)
    for c in to_rm: del portfolio[c]

    sa = max_s - len(portfolio)
    if sa > 0:
        for k in range(len(cand_cols)):
            if sa <= 0: break
            if cand_wranks[k] <= entry_p:
                c = cand_cols[k]
                if c not in portfolio:
                    portfolio[c] = {'ep':cand_prices[k],'ei':i,'peak':cand_prices[k]}
                    sa -= 1

for col, info in portfolio.items():
    lr = tsim_b._date_row_indices[-1]
    if lr >= 0:
        ep = tsim_b._price_arr[lr, col]
        if ep > 0 and not np.isnan(ep):
            tk = col_to_tk.get(col,'?')
            trades.append({'ticker':tk,'name':tk_names.get(tk,'?'),
                'entry':yd25[info['ei']],'exit':yd25[-1],
                'ret':(ep/info['ep']-1)*100,'days':len(yd25)-1-info['ei'],'reason':'open'})

tdf = pd.DataFrame(trades)
wins = tdf[tdf['ret']>0]
losses = tdf[tdf['ret']<=0]
print(f'총 {len(tdf)}건: {len(wins)}승 {len(losses)}패 (승률 {len(wins)/len(tdf)*100:.0f}%)')
print(f'총 수익 합계: {tdf["ret"].sum():+.1f}%')

print(f'\n[수익 Top 10]')
for _, t in wins.sort_values('ret',ascending=False).head(10).iterrows():
    print(f'  {t["name"]:>12} {t["entry"]}~{t["exit"]} {t["days"]:>2}일 {t["ret"]:>+6.1f}% ({t["reason"]})')

print(f'\n[손실 Top 10]')
for _, t in losses.sort_values('ret').head(10).iterrows():
    print(f'  {t["name"]:>12} {t["entry"]}~{t["exit"]} {t["days"]:>2}일 {t["ret"]:>+6.1f}% ({t["reason"]})')

print(f'\n[퇴출 사유별]')
for reason, g in tdf.groupby('reason'):
    wr = (g['ret']>0).mean()*100
    print(f'  {reason:>12}: {len(g)}건 승률={wr:.0f}% 평균={g["ret"].mean():+.1f}% 합계={g["ret"].sum():+.1f}%')
