"""Stop Loss + Trailing Stop 최적 조합 탐색
v80 E3X6S3/E3X6S5 고정, SL × TS 그리드서치
"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
import requests
from turbo_simulator import TurboSimulator
from pathlib import Path

PROJECT = Path(__file__).parent.parent
BOT = '8504167814:AAHC_fSmYslVAnKHIneZZOvb_8zRgUpOA9g'
PID = '7580571403'
def send_tg(msg):
    if len(msg) > 4096: msg = msg[:4090] + '...'
    requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                  data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)

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

print('load...', flush=True)
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

PERIODS = {
    '7.8y': ('20180702','20260414'),
    'WF1': ('20180702','20191231'),
    'WF2': ('20200102','20211230'),
    'WF3': ('20220103','20231228'),
    'WF4': ('20240102','20260414'),
}

# SL x TS 그리드
stop_losses = [None, -0.05, -0.06, -0.07, -0.08, -0.09, -0.10, -0.12, -0.15, -0.20]
trailings = [None, -0.08, -0.10, -0.12, -0.15, -0.18, -0.20, -0.25, -0.30]

all_results = []
total = len(stop_losses) * len(trailings)
count = 0

for sl in stop_losses:
    for ts in trailings:
        count += 1
        label = f'SL{int(sl*100) if sl else "X"}_TS{int(ts*100) if ts else "X"}'

        row = {'sl': sl, 'ts': ts, 'label': label}
        for pname, (ps, pe) in PERIODS.items():
            pd_ = [d for d in dates if ps <= d <= pe]
            if len(pd_) < 20: continue
            reg = calc_regime(pd_)
            tsim = TurboSimulator({d: rk[d] for d in pd_}, pd_, ohlcv)
            r = tsim.run_regime(defense_params=V80_D, offense_params=V80_O,
                regime_dict=reg,
                trailing_stop=ts,
                stop_loss=sl if sl else -999,
                g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
                g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
                g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
                g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
            row[pname] = r['calmar']
            if pname == '7.8y':
                row['cagr'] = r['cagr']
                row['mdd'] = r['mdd']

        wf = [row.get(f'WF{i}', 0) for i in range(1, 5)]
        row['wf_min'] = min(wf)
        row['wf_mean'] = np.mean(wf)
        row['cv'] = np.std(wf)/np.mean(wf) if np.mean(wf) > 0 else 99
        all_results.append(row)

        if count % 10 == 0:
            print(f'  [{count}/{total}] {label}: Cal={row.get("7.8y",0):.2f}', flush=True)

# 정렬
rdf = pd.DataFrame(all_results).sort_values('7.8y', ascending=False)
bl = next(r for r in all_results if r['sl'] == -0.10 and r['ts'] == -0.15)
bl_cal = bl['7.8y']

# 출력
print(f'\n{"="*100}')
print(f'SL x TS 그리드서치 결과 ({total}조합)')
print(f'{"="*100}')
print(f'baseline (SL-10% TS-15%): Cal={bl_cal:.2f} CAGR={bl["cagr"]:.1f}% MDD={bl["mdd"]:.1f}% CV={bl["cv"]:.2f}')

print(f'\nTop 20:')
print(f'{"순위":>4} {"SL":>5} {"TS":>5} {"Cal":>6} {"CAGR":>7} {"MDD":>6} {"WF1":>5} {"WF2":>5} {"WF3":>5} {"WF4":>5} {"min":>5} {"CV":>5}')
print('-'*85)
for i, (_, r) in enumerate(rdf.head(20).iterrows()):
    sl_str = f'{int(r["sl"]*100)}%' if pd.notna(r['sl']) else 'X'
    ts_str = f'{int(r["ts"]*100)}%' if pd.notna(r['ts']) else 'X'
    wf = [r.get(f'WF{j}',0) for j in range(1,5)]
    d = r['7.8y'] - bl_cal
    cv_ok = r['cv'] < 0.40
    marker = ' ***' if d > 0.2 and cv_ok else (' **' if d > 0.1 and cv_ok else (' *' if d > 0 else ''))
    print(f'{i+1:>4} {sl_str:>5} {ts_str:>5} {r["7.8y"]:>6.2f} {r["cagr"]:>7.1f} {r["mdd"]:>6.1f} {wf[0]:>5.2f} {wf[1]:>5.2f} {wf[2]:>5.2f} {wf[3]:>5.2f} {r["wf_min"]:>5.2f} {r["cv"]:>5.2f}{marker}')

# 히트맵 (Cal 기준)
print(f'\n{"="*100}')
print(f'Calmar 히트맵 (SL x TS)')
print(f'{"="*100}')
sl_ts = 'SL/TS'
header = f'{sl_ts:>7}'
for ts in trailings:
    header += f' {f"{int(ts*100)}%" if ts else "X":>6}'
print(header)
print('-'*(7 + 7*len(trailings)))
for sl in stop_losses:
    sl_str = f'{int(sl*100)}%' if sl else 'X'
    line = f'{sl_str:>7}'
    for ts in trailings:
        match = next((r for r in all_results if r['sl']==sl and r['ts']==ts), None)
        if match:
            cal = match['7.8y']
            line += f' {cal:>6.2f}'
        else:
            line += f' {"?":>6}'
    print(line)

# 인접 안정성: Top 3 설정
print(f'\n{"="*100}')
print(f'Top 5 인접 안정성 검증')
print(f'{"="*100}')
for i, (_, r) in enumerate(rdf.head(5).iterrows()):
    sl, ts = r['sl'], r['ts']
    # 인접: SL +-1~2%, TS +-2~3%
    adj_cals = []
    for r2 in all_results:
        sl_diff = abs((r2['sl'] or -999) - (sl or -999))
        ts_diff = abs((r2['ts'] or -999) - (ts or -999))
        if 0 < sl_diff <= 0.03 and ts_diff == 0:
            adj_cals.append(r2['7.8y'])
        elif sl_diff == 0 and 0 < ts_diff <= 0.05:
            adj_cals.append(r2['7.8y'])
    if adj_cals:
        all_vals = adj_cals + [r['7.8y']]
        adj_cv = np.std(all_vals) / np.mean(all_vals) if np.mean(all_vals) > 0 else 99
        passed = adj_cv < 0.15
        sl_str = f'{int(sl*100)}%' if sl else 'X'
        ts_str = f'{int(ts*100)}%' if ts else 'X'
        print(f'  #{i+1} SL={sl_str} TS={ts_str}: Cal={r["7.8y"]:.2f}, 인접={[f"{c:.2f}" for c in adj_cals]}, 인접CV={adj_cv:.3f} {"PASS" if passed else "FAIL"}')

# CSV 저장
rdf.to_csv(str(PROJECT/'backtest'/'sl_ts_grid_results.csv'), index=False, encoding='utf-8-sig')

# 텔레그램 (2개 메시지)
msg1 = '<b>[SL x TS 그리드서치 결과]</b>\n\n'
msg1 += f'v80 E3X6S3/E3X6S5 고정\n'
msg1 += f'SL {len(stop_losses)}단계 x TS {len(trailings)}단계 = {total}조합\n\n'
msg1 += f'baseline (SL-10% TS-15%): Cal={bl_cal:.2f}\n\n'
msg1 += '<b>Top 10:</b>\n'
for i, (_, r) in enumerate(rdf.head(10).iterrows()):
    sl_str = f'{int(r["sl"]*100)}%' if pd.notna(r['sl']) else 'X'
    ts_str = f'{int(r["ts"]*100)}%' if pd.notna(r['ts']) else 'X'
    d = r['7.8y'] - bl_cal
    cv_ok = r['cv'] < 0.40
    emoji = '\u2b50' if d > 0.1 and cv_ok else ('\u2705' if d > 0 else '\u274c')
    msg1 += f'{emoji} SL={sl_str} TS={ts_str}\n'
    msg1 += f'   Cal={r["7.8y"]:.2f}(d{d:+.2f}) CAGR={r["cagr"]:.0f}% MDD={r["mdd"]:.0f}% CV={r["cv"]:.2f}\n'
send_tg(msg1)

msg2 = '<b>[SL x TS 쉬운 설명]</b>\n\n'
msg2 += '<b>Stop Loss (SL)</b> = 손절\n'
msg2 += '산 가격 대비 얼마나 빠지면 파는지\n'
msg2 += 'SL-7% = 7% 빠지면 즉시 매도\n\n'
msg2 += '<b>Trailing Stop (TS)</b> = 추적 손절\n'
msg2 += '최고점 대비 얼마나 빠지면 파는지\n'
msg2 += '산 후 +50% 올랐다가 TS-15%면\n'
msg2 += '→ 최고점 대비 15% 빠질 때 매도\n'
msg2 += '→ 아직 +27.5% 수익인 상태에서 확정\n\n'
msg2 += '<b>현재 v80</b>: SL-10% TS-15%\n\n'

best = rdf.iloc[0]
d = best['7.8y'] - bl_cal
sl_str = f'{int(best["sl"]*100)}%' if best['sl'] else 'X'
ts_str = f'{int(best["ts"]*100)}%' if best['ts'] else 'X'
msg2 += f'<b>최적: SL={sl_str} TS={ts_str}</b>\n'
msg2 += f'Cal {bl_cal:.2f} -> {best["7.8y"]:.2f} ({d:+.2f})\n'
msg2 += f'CAGR {bl["cagr"]:.0f}% -> {best["cagr"]:.0f}%\n'
msg2 += f'MDD {bl["mdd"]:.0f}% -> {best["mdd"]:.0f}%\n'
msg2 += f'CV={best["cv"]:.2f} (0.40 이하면 안정)\n\n'

# WF 통과 + CV<0.40인 최고
stable = rdf[rdf['cv'] < 0.40]
if len(stable) > 0:
    sb = stable.iloc[0]
    d2 = sb['7.8y'] - bl_cal
    sl2 = f'{int(sb["sl"]*100)}%' if sb['sl'] else 'X'
    ts2 = f'{int(sb["ts"]*100)}%' if sb['ts'] else 'X'
    msg2 += f'<b>안정적 최고 (CV<0.40):</b>\n'
    msg2 += f'SL={sl2} TS={ts2}\n'
    msg2 += f'Cal={sb["7.8y"]:.2f}(d{d2:+.2f}) CV={sb["cv"]:.2f}'

send_tg(msg2)
print('\ntelegram sent')
