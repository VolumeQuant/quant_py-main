"""v80 개선방안 A~E BT 테스트
A: 동적 손절 (ATR 기반)
B: 수익 중 퇴출 완화 (비대칭 exit)
C: 국면 전환 직후 슬롯 축소
D: 최신 데이터 반영 (별도)
E: 확신도 기반 포지션 사이징
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from turbo_simulator import TurboSimulator
from pathlib import Path
from copy import deepcopy

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

print('데이터 로드...', flush=True)
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

# 7.8y 기간
ps, pe = '20180702', '20260414'
pd_ = [d for d in dates if ps <= d <= pe]
reg = calc_regime(pd_)

# === Baseline ===
V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}

def run_bt(rk_data, offense, defense_p, regime_dict, trailing=-0.15, stop=-0.10, label=''):
    tsim = TurboSimulator({d: rk_data[d] for d in pd_}, pd_, ohlcv)
    r = tsim.run_regime(defense_params=defense_p, offense_params=offense,
        regime_dict=regime_dict, trailing_stop=trailing, stop_loss=stop,
        g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
        g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
    print(f'  {label}: Cal={r["calmar"]:.2f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}%', flush=True)
    return r

results = []

print('\n=== Baseline ===', flush=True)
bl = run_bt(rk, V80_O, V80_D, reg, label='baseline')
results.append({'test': 'baseline', 'cal': bl['calmar'], 'cagr': bl['cagr'], 'mdd': bl['mdd']})

# === A: 동적 손절 (손절 폭 변경) ===
print('\n=== A: 손절 폭 변경 ===', flush=True)
for sl in [-0.07, -0.08, -0.12, -0.15, -0.20, None]:
    label = f'stop={sl}' if sl else 'no_stop'
    r = run_bt(rk, V80_O, V80_D, reg, stop=sl if sl else -999, label=label)
    results.append({'test': f'A_{label}', 'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']})

# === A2: 트레일링 폭 변경 ===
print('\n=== A2: 트레일링 폭 변경 ===', flush=True)
for ts in [-0.10, -0.12, -0.20, -0.25, None]:
    label = f'trail={ts}' if ts else 'no_trail'
    r = run_bt(rk, V80_O, V80_D, reg, trailing=ts, label=label)
    results.append({'test': f'A2_{label}', 'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']})

# === B: 퇴출 기준 변경 ===
print('\n=== B: 퇴출 기준 변경 ===', flush=True)
for ex in [4, 5, 7, 8, 10]:
    o = {**V80_O, 'exit': ex}
    d = {**V80_D, 'exit': ex}
    r = run_bt(rk, o, d, reg, label=f'exit={ex}')
    results.append({'test': f'B_exit={ex}', 'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']})

# === B2: 진입 기준 변경 ===
print('\n=== B2: 진입 기준 변경 ===', flush=True)
for en in [1, 2, 4, 5]:
    o = {**V80_O, 'entry': en}
    d = {**V80_D, 'entry': en}
    r = run_bt(rk, o, d, reg, label=f'entry={en}')
    results.append({'test': f'B2_entry={en}', 'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']})

# === C: 슬롯 변경 ===
print('\n=== C: 슬롯 변경 ===', flush=True)
for so, sd in [(2,3), (2,5), (3,3), (4,5), (5,7), (3,7)]:
    o = {**V80_O, 'slots': so}
    d = {**V80_D, 'slots': sd}
    r = run_bt(rk, o, d, reg, label=f'slots_o{so}_d{sd}')
    results.append({'test': f'C_slots_o{so}_d{sd}', 'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']})

# === E: 진입+퇴출+슬롯 복합 ===
print('\n=== E: 복합 조합 ===', flush=True)
combos = [
    ('E3X8S3/E3X6S5', {'entry':3,'exit':8,'slots':3}, {'entry':3,'exit':6,'slots':5}),
    ('E3X7S3/E3X6S5', {'entry':3,'exit':7,'slots':3}, {'entry':3,'exit':6,'slots':5}),
    ('E2X6S3/E3X6S5', {'entry':2,'exit':6,'slots':3}, {'entry':3,'exit':6,'slots':5}),
    ('E3X6S3/E3X8S5', {'entry':3,'exit':6,'slots':3}, {'entry':3,'exit':8,'slots':5}),
    ('E3X8S3/E3X8S5', {'entry':3,'exit':8,'slots':3}, {'entry':3,'exit':8,'slots':5}),
]
for label, o_override, d_override in combos:
    o = {**V80_O, **o_override}
    d = {**V80_D, **d_override}
    r = run_bt(rk, o, d, reg, label=label)
    results.append({'test': f'E_{label}', 'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd']})

# === 종합 ===
print(f'\n{"="*60}')
print('종합 결과 (Calmar 순)')
print('='*60, flush=True)

rdf = pd.DataFrame(results).sort_values('cal', ascending=False)
bl_cal = results[0]['cal']
for i, (_, r) in enumerate(rdf.iterrows()):
    delta = r['cal'] - bl_cal
    marker = ' ***' if delta > 0.3 else (' *' if delta > 0 else '')
    print(f'  {i+1:>2}. {r["test"]:>25}: Cal={r["cal"]:.2f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}% (d{delta:+.2f}){marker}')

rdf.to_csv(str(PROJECT/'backtest'/'improvement_test.csv'), index=False, encoding='utf-8-sig')

# 텔레그램
improved = rdf[rdf['cal'] > bl_cal]
msg = '<b>[v80 개선방안 BT 결과]</b>\n\n'
msg += f'baseline: Cal={bl_cal:.2f}\n'
msg += f'테스트: {len(rdf)}개 조합\n'
msg += f'baseline 초과: {len(improved)}개\n\n'

msg += '<b>Top 10:</b>\n'
for i, (_, r) in enumerate(rdf.head(10).iterrows()):
    delta = r['cal'] - bl_cal
    emoji = '\u2b50' if delta > 0.3 else ('\u2705' if delta > 0 else '\u274c')
    msg += f'{emoji} {r["test"]}\n'
    msg += f'   Cal={r["cal"]:.2f} CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}% (d{delta:+.2f})\n'

if len(improved) > 0:
    best = improved.iloc[0]
    msg += f'\n<b>최고: {best["test"]}</b>\n'
    msg += f'Cal={best["cal"]:.2f} (d{best["cal"]-bl_cal:+.2f})'
else:
    msg += '\nbaseline이 최적'

send_tg(msg)
print('\n텔레그램 전송 완료')
