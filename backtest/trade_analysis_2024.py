"""2024년 매매 상세 분석"""
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
kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna()
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

yd = [d for d in dates if '20240102' <= d <= '20241230']
reg = calc_regime(yd)

# 국면 현황
boost_days = sum(1 for d in yd if reg.get(d, False))
defense_days = len(yd) - boost_days
print(f'2024년 거래일: {len(yd)}일')
print(f'공격모드: {boost_days}일, 방어모드: {defense_days}일')
print(f'\n국면 전환 시점:')
prev = None
for d in yd:
    cur = reg.get(d, False)
    if prev is not None and cur != prev:
        mode = '공격' if cur else '방어'
        kv = kospi.get(pd.Timestamp(d))
        print(f'  {d}: {mode}으로 전환 (KOSPI {kv:.0f})')
    prev = cur

# 매매 추적
tsim_b = TurboSimulator({d: rk[d] for d in yd}, yd, ohlcv)
tsim_b._ensure_cache(0.15, 0.00, 0.55, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
boost_flat = list(tsim_b._cached_flat)
tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in yd}, yd, ohlcv)
tsim_d._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
defense_flat = list(tsim_d._cached_flat)

# ticker->name
tk_names = {}
for d in yd:
    for item in rk[d]:
        tk_names[item.get('ticker','')] = item.get('name','?')
col_to_tk = {i: c for i, c in enumerate(ohlcv.columns)}

portfolio = {}
trades = []
prev_regime = None

for i in range(2, len(yd)):
    d = yd[i]
    cr = reg.get(d, False)
    if prev_regime is not None and cr != prev_regime:
        for col, info in portfolio.items():
            cur_row = tsim_b._date_row_indices[i]
            if cur_row >= 0:
                ep = tsim_b._price_arr[cur_row, col]
                if ep > 0 and not np.isnan(ep):
                    tk = col_to_tk.get(col,'?')
                    trades.append({'ticker':tk,'name':tk_names.get(tk,'?'),
                        'entry_date':yd[info['ei']],'exit_date':d,
                        'entry_price':info['ep'],'exit_price':ep,
                        'ret':(ep/info['ep']-1)*100,'days':i-info['ei'],
                        'reason':'regime','mode':'boost' if prev_regime else 'defense',
                        'peak_ret':(info['peak']/info['ep']-1)*100})
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
        if cp > info['peak']: info['peak'] = cp
        reason = None
        if (cp/info['ep']-1) <= -0.10: reason = 'stop_loss'
        elif (cp/info['peak']-1) <= -0.15: reason = 'trailing'
        elif wrank_arr[col] > exit_p: reason = 'rank_exit'
        if reason:
            tk = col_to_tk.get(col,'?')
            trades.append({'ticker':tk,'name':tk_names.get(tk,'?'),
                'entry_date':yd[info['ei']],'exit_date':d,
                'entry_price':info['ep'],'exit_price':cp,
                'ret':(cp/info['ep']-1)*100,'days':i-info['ei'],
                'reason':reason,'mode':'boost' if cr else 'defense',
                'peak_ret':(info['peak']/info['ep']-1)*100})
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
                'entry_date':yd[info['ei']],'exit_date':yd[-1],
                'entry_price':info['ep'],'exit_price':ep,
                'ret':(ep/info['ep']-1)*100,'days':len(yd)-1-info['ei'],
                'reason':'open','mode':'boost' if reg.get(yd[-1],False) else 'defense',
                'peak_ret':(info['peak']/info['ep']-1)*100})

tdf = pd.DataFrame(trades)

print(f'\n{"="*70}')
print(f'2024년 매매 요약')
print(f'{"="*70}')
print(f'총 {len(tdf)}건: {(tdf["ret"]>0).sum()}승 {(tdf["ret"]<=0).sum()}패 (승률 {(tdf["ret"]>0).mean()*100:.0f}%)')
print(f'총 수익 합계: {tdf["ret"].sum():+.1f}%')
print(f'평균 보유: {tdf["days"].mean():.0f}일')

print(f'\n{"="*70}')
print(f'퇴출 사유별')
print(f'{"="*70}')
for reason, g in tdf.groupby('reason'):
    wr = (g['ret']>0).mean()*100
    print(f'{reason:>12}: {len(g):>3}건 승률={wr:.0f}% 평균={g["ret"].mean():+.1f}% 합계={g["ret"].sum():+.1f}% 보유={g["days"].mean():.0f}일')

print(f'\n{"="*70}')
print(f'국면별')
print(f'{"="*70}')
for mode, g in tdf.groupby('mode'):
    wr = (g['ret']>0).mean()*100
    print(f'{mode:>8}: {len(g):>3}건 승률={wr:.0f}% 평균={g["ret"].mean():+.1f}% 합계={g["ret"].sum():+.1f}%')

print(f'\n{"="*70}')
print(f'전체 매매 시간순')
print(f'{"="*70}')
print(f'{"종목":>12} {"진입":>10} {"퇴출":>10} {"일수":>4} {"수익률":>8} {"최고":>7} {"사유":>10} {"모드":>6}')
print('-'*70)
for _, t in tdf.sort_values('entry_date').iterrows():
    marker = ''
    if t['ret'] > 30: marker = ' ***'
    elif t['ret'] > 10: marker = ' *'
    elif t['ret'] < -8: marker = ' !'
    print(f'{t["name"]:>12} {t["entry_date"]:>10} {t["exit_date"]:>10} {t["days"]:>4} {t["ret"]:>+8.1f}% {t["peak_ret"]:>+7.1f}% {t["reason"]:>10} {t["mode"]:>6}{marker}')

print(f'\n{"="*70}')
print(f'수익 기여 Top 10 종목')
print(f'{"="*70}')
by_ticker = tdf.groupby('name').agg(
    trades=('ret','count'),
    total_ret=('ret','sum'),
    avg_ret=('ret','mean'),
    wins=('ret', lambda x: (x>0).sum())
).sort_values('total_ret', ascending=False)
for nm, r in by_ticker.head(10).iterrows():
    print(f'  {nm:>12}: {r["trades"]:.0f}건 합계={r["total_ret"]:+.1f}% 평균={r["avg_ret"]:+.1f}% ({r["wins"]:.0f}승)')

print(f'\n{"="*70}')
print(f'손실 기여 Top 10 종목')
print(f'{"="*70}')
for nm, r in by_ticker.tail(10).iterrows():
    print(f'  {nm:>12}: {r["trades"]:.0f}건 합계={r["total_ret"]:+.1f}% 평균={r["avg_ret"]:+.1f}% ({r["wins"]:.0f}승)')
