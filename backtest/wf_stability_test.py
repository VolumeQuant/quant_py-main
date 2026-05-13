"""WF + 인접 안정성 테스트: o2_d5, SL-7% 및 인접 설정"""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from turbo_simulator import TurboSimulator
from pathlib import Path

PROJECT = Path(__file__).parent.parent
from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
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

PERIODS = {
    '7.4y': ('20190102','20260512'),  # 2018 H2 데이터 부족 제외 (사용자 5/13 결정)
    'WF1': ('20190102','20191231'),   # 2019 (1년) — 시장 약세
    'WF2': ('20200102','20211230'),   # 2020-21 (2년) — 코로나 + 회복
    'WF3': ('20220103','20231228'),   # 2022-23 (2년) — 약세 + 회복
    'WF4': ('20240102','20260512'),   # 2024-26 (2년 4개월) — 강세
}

def make_params(entry, exit_r, slots, mom, v, q, g, m, g_rev):
    return {'v':v, 'q':q, 'g':g, 'm':m, 'g_rev':g_rev,
            'entry':entry, 'exit':exit_r, 'slots':slots, 'mom':mom}

O_BASE = lambda s=3, sl_override=None: make_params(3, 6, s, '12m', 0.15, 0.00, 0.55, 0.30, 0.6)
D_BASE = lambda s=5: make_params(3, 6, s, '6m-1m', 0.30, 0.15, 0.15, 0.40, 0.7)

configs = [
    # (name, offense, defense, stop_loss, trailing)
    ('baseline S3/S5 SL10', O_BASE(3), D_BASE(5), -0.10, -0.15),
    # 후보 1: o2_d5
    ('o2_d5 SL10', O_BASE(2), D_BASE(5), -0.10, -0.15),
    # 후보 2: SL-7%
    ('S3/S5 SL7', O_BASE(3), D_BASE(5), -0.07, -0.15),
    # 복합
    ('o2_d5 SL7', O_BASE(2), D_BASE(5), -0.07, -0.15),
    # 인접: o2_d5 주변
    ('o1_d5 SL10', O_BASE(1), D_BASE(5), -0.10, -0.15),
    ('o2_d4 SL10', O_BASE(2), D_BASE(4), -0.10, -0.15),
    ('o2_d6 SL10', O_BASE(2), D_BASE(6), -0.10, -0.15),
    ('o3_d5 SL10', O_BASE(3), D_BASE(5), -0.10, -0.15),
    # 인접: SL 주변
    ('S3/S5 SL6', O_BASE(3), D_BASE(5), -0.06, -0.15),
    ('S3/S5 SL8', O_BASE(3), D_BASE(5), -0.08, -0.15),
    ('S3/S5 SL9', O_BASE(3), D_BASE(5), -0.09, -0.15),
    ('S3/S5 SL12', O_BASE(3), D_BASE(5), -0.12, -0.15),
]

all_results = []
for name, o_p, d_p, sl, tr in configs:
    row = {'name': name}
    for pname, (ps, pe) in PERIODS.items():
        pd_ = [d for d in dates if ps <= d <= pe]
        if len(pd_) < 20: continue
        reg = calc_regime(pd_)
        tsim = TurboSimulator({d: rk[d] for d in pd_}, pd_, ohlcv)
        r = tsim.run_regime(defense_params=d_p, offense_params=o_p,
            regime_dict=reg, trailing_stop=tr, stop_loss=sl,
            g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
            g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
            g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
            g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
        row[pname] = r['calmar']
        if pname == '7.4y':
            row['cagr'] = r['cagr']
            row['mdd'] = r['mdd']
    wf = [row.get(f'WF{i}', 0) for i in range(1, 5)]
    row['wf_min'] = min(wf)
    row['wf_mean'] = np.mean(wf)
    row['cv'] = np.std(wf)/np.mean(wf) if np.mean(wf) > 0 else 99
    all_results.append(row)
    print(f'{name}: Cal={row["7.4y"]:.2f} WF=[{wf[0]:.2f},{wf[1]:.2f},{wf[2]:.2f},{wf[3]:.2f}] CV={row["cv"]:.2f}', flush=True)

# 출력
bl_cal = all_results[0]['7.4y']
print(f'\n{"="*95}')
print(f'{"설정":<20} {"7.4y":>6} {"CAGR":>6} {"MDD":>6} {"WF1":>6} {"WF2":>6} {"WF3":>6} {"WF4":>6} {"min":>6} {"mean":>6} {"CV":>5}')
print('-'*95)
for r in sorted(all_results, key=lambda x: x['7.4y'], reverse=True):
    wf = [r.get(f'WF{i}',0) for i in range(1,5)]
    d = r['7.4y'] - bl_cal
    m = ' ***' if d > 0.2 and r['cv'] < 0.40 else (' *' if d > 0 else '')
    print(f'{r["name"]:<20} {r["7.4y"]:>6.2f} {r.get("cagr",0):>6.1f} {r.get("mdd",0):>6.1f} {wf[0]:>6.2f} {wf[1]:>6.2f} {wf[2]:>6.2f} {wf[3]:>6.2f} {r["wf_min"]:>6.2f} {r["wf_mean"]:>6.2f} {r["cv"]:>5.2f}{m}')

# 인접 안정성 판정
print('\n=== 인접 안정성 판정 ===')
for target in ['o2_d5 SL10', 'S3/S5 SL7']:
    t = next(r for r in all_results if r['name'] == target)
    adj = [r for r in all_results if r['name'] != target and r['name'] != 'baseline S3/S5 SL10']
    # 해당 설정의 인접만 필터
    if 'o2' in target:
        adj = [r for r in all_results if any(x in r['name'] for x in ['o1_d5','o2_d4','o2_d6','o3_d5'])]
    else:
        adj = [r for r in all_results if any(x in r['name'] for x in ['SL6','SL8','SL9','SL12'])]
    adj_cals = [r['7.4y'] for r in adj]
    t_cal = t['7.4y']
    adj_cv = np.std(adj_cals + [t_cal]) / np.mean(adj_cals + [t_cal])
    passed = adj_cv < 0.30
    print(f'  {target}: Cal={t_cal:.2f}, 인접 Cal={[f"{c:.2f}" for c in adj_cals]}, 인접 CV={adj_cv:.2f} {"PASS" if passed else "FAIL"}')

# 텔레그램
msg = '<b>[WF + 인접 안정성 결과]</b>\n\n'
msg += f'baseline: Cal={bl_cal:.2f}\n\n'

for r in sorted(all_results, key=lambda x: x['7.4y'], reverse=True):
    d = r['7.4y'] - bl_cal
    wf = [r.get(f'WF{i}',0) for i in range(1,5)]
    cv_ok = r['cv'] < 0.40
    emoji = '\u2b50' if d > 0.2 and cv_ok else ('\u2705' if d > 0 else '\u274c')
    msg += f'{emoji} <b>{r["name"]}</b>\n'
    msg += f'   Cal={r["7.4y"]:.2f}(d{d:+.2f}) CAGR={r.get("cagr",0):.0f}% MDD={r.get("mdd",0):.0f}%\n'
    msg += f'   WF=[{wf[0]:.1f},{wf[1]:.1f},{wf[2]:.1f},{wf[3]:.1f}] CV={r["cv"]:.2f}\n\n'

send_tg(msg)
print('\ntelegram sent')
