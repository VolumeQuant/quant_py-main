"""Tier 8C — gr 0.4 후보 WF + 인접 + 033100 의존 종합 평가"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from pathlib import Path
from turbo_simulator import TurboSimulator

PROJECT = Path(__file__).parent.parent

from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
def send_tg(msg):
    if len(msg) > 4096: msg = msg[:4090] + '...'
    try:
        requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                      data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
    except: pass

print('=== Tier 8C — gr 0.4 후보 종합 평가 ===', flush=True)
t_start = time.time()

def load_rankings(dirs):
    data = {}
    for d in dirs:
        d = Path(d)
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            k = fp.stem.replace('ranking_', '')
            if len(k) != 8 or not k.isdigit(): continue
            if k not in data:
                with open(fp, 'r', encoding='utf-8') as f:
                    data[k] = json.load(f)
    return data

boost_rd = load_rankings([PROJECT / 'state'])
defense_rd = load_rankings([PROJECT / 'state' / 'defense'])
all_dates = sorted(set(boost_rd) & set(defense_rd))
boost_rk = {d: boost_rd[d]['rankings'] for d in all_dates}

ohlcv = pd.read_parquet(PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet').replace(0, np.nan)
kdf = pd.read_parquet(PROJECT / 'data_cache' / 'kospi_yf.parquet')
kospi = kdf.iloc[:, 0].copy()
for c in kdf.columns[1:]:
    kospi = kospi.fillna(kdf[c])
kospi = kospi.dropna()
ma250 = kospi.rolling(250).mean()

PERIODS = {
    '7.4y': ('20190102', '20260512'),
    'WF1 (19)':    ('20190102', '20191231'),
    'WF2 (20-21)': ('20200102', '20211230'),
    'WF3 (22-23)': ('20220103', '20231228'),
    'WF4 (24-26)': ('20240102', '20260512'),
}

print('  TSIM 초기화 (orig + no033)...', flush=True)
TSIMS_ORIG = {}
TSIMS_NO033 = {}
for pname, (ps, pe) in PERIODS.items():
    pdates = [d for d in all_dates if ps <= d <= pe]
    if len(pdates) < 50: continue
    TSIMS_ORIG[pname] = (pdates, TurboSimulator({d: boost_rk[d] for d in pdates}, pdates, ohlcv))
    boost_rk_no033 = {d: [r for r in boost_rk[d] if r['ticker'] != '033100'] for d in pdates}
    TSIMS_NO033[pname] = (pdates, TurboSimulator(boost_rk_no033, pdates, ohlcv))
print(f'  로드 완료: {time.time()-t_start:.1f}초\n', flush=True)

def calc_regime(target_dates, ma_period=250, confirm=8):
    ma = kospi.rolling(ma_period).mean()
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d); kv = kospi.get(ts); mv = ma.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg

GS = ('rev_z', 'oca_z', None, None, None, None)
DEFENSE_T4 = {'v':0.35,'q':0.15,'g':0.15,'m':0.35,'g_rev':0.8,
              'entry':3,'exit':6,'slots':4,'mom':'6m-1m'}

def bp(e, s, x, gr):
    return {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':gr,
            'entry':e,'exit':x,'slots':s,'mom':'12m'}

# 후보 — gr 0.4 + 인접 gr (0.3, 0.45, 0.35), 다른 변형
candidates = [
    ('v80.6 (gr0.5)',           bp(2, 5, 6, 0.5), -0.10, -0.08),
    ('v80.6_gr0.4 (제안)',       bp(2, 5, 6, 0.4), -0.10, -0.08),
    # gr 0.4 인접
    ('adj: gr0.3',              bp(2, 5, 6, 0.3), -0.10, -0.08),
    ('adj: gr0.35',             bp(2, 5, 6, 0.35), -0.10, -0.08),
    ('adj: gr0.45',             bp(2, 5, 6, 0.45), -0.10, -0.08),
    # 다른 변형 (gr 0.4 기준)
    ('adj: gr0.4_sb4',          bp(2, 4, 6, 0.4), -0.10, -0.08),
    ('adj: gr0.4_sb6',          bp(2, 6, 6, 0.4), -0.10, -0.08),
    ('adj: gr0.4_x5',           bp(2, 5, 5, 0.4), -0.10, -0.08),
    ('adj: gr0.4_x7',           bp(2, 5, 7, 0.4), -0.10, -0.08),
    ('adj: gr0.4_TS-7',         bp(2, 5, 6, 0.4), -0.10, -0.07),
    ('adj: gr0.4_TS-10',        bp(2, 5, 6, 0.4), -0.10, -0.10),
]

print('=== BT 실행 (orig + no033) ===', flush=True)
results = []
for name, boost_p, sl, ts in candidates:
    row = {'name': name}
    for env, tsims in [('orig', TSIMS_ORIG), ('no033', TSIMS_NO033)]:
        for pname, (pdates, tsim) in tsims.items():
            reg = calc_regime(pdates)
            try:
                r = tsim.run_regime(defense_params=DEFENSE_T4, offense_params=boost_p,
                                    regime_dict=reg, trailing_stop=ts, stop_loss=sl,
                                    g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
                                    g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
                                    g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
                                    g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
                row[f'{env}_{pname}'] = r['calmar']
                if pname == '7.4y':
                    row[f'{env}_cagr'] = r['cagr']
                    row[f'{env}_mdd'] = r['mdd']
            except Exception as e:
                row[f'{env}_{pname}'] = 0
    # delta + CV
    row['delta'] = row.get('orig_7.4y', 0) - row.get('no033_7.4y', 0)
    wf_orig = [row.get(f'orig_{p}', 0) for p in PERIODS if p.startswith('WF')]
    wf_no033 = [row.get(f'no033_{p}', 0) for p in PERIODS if p.startswith('WF')]
    row['cv_orig'] = np.std(wf_orig) / np.mean(wf_orig) if np.mean(wf_orig) > 0 else 99
    row['cv_no033'] = np.std(wf_no033) / np.mean(wf_no033) if np.mean(wf_no033) > 0 else 99
    results.append(row)
    print(f'  {name}: orig={row["orig_7.4y"]:.2f} no033={row["no033_7.4y"]:.2f} delta={row["delta"]:.2f} CV(orig)={row["cv_orig"]:.2f}', flush=True)

print('\n' + '=' * 120)
print(f'{"name":<28} {"orig":>5} {"no033":>5} {"delta":>5} {"WF1o":>5} {"WF2o":>5} {"WF3o":>5} {"WF4o":>5} {"CVo":>5} {"WF1n":>5} {"WF2n":>5} {"WF3n":>5} {"WF4n":>5} {"CVn":>5}')
print('-' * 120)
for r in results:
    print(f'{r["name"][:27]:<28} {r["orig_7.4y"]:>5.2f} {r["no033_7.4y"]:>5.2f} {r["delta"]:>5.2f} '
          f'{r["orig_WF1 (19)"]:>5.2f} {r["orig_WF2 (20-21)"]:>5.2f} {r["orig_WF3 (22-23)"]:>5.2f} {r["orig_WF4 (24-26)"]:>5.2f} {r["cv_orig"]:>5.2f} '
          f'{r["no033_WF1 (19)"]:>5.2f} {r["no033_WF2 (20-21)"]:>5.2f} {r["no033_WF3 (22-23)"]:>5.2f} {r["no033_WF4 (24-26)"]:>5.2f} {r["cv_no033"]:>5.2f}')

# 인접 안정성 (gr 0.4 기준)
gr04 = next(r for r in results if 'gr0.4 (제안)' in r['name'])
adj = [r for r in results if r['name'].startswith('adj:')]
adj_cals = [gr04['orig_7.4y']] + [r['orig_7.4y'] for r in adj]
adj_cv = np.std(adj_cals) / np.mean(adj_cals)
adj_cals_n = [gr04['no033_7.4y']] + [r['no033_7.4y'] for r in adj]
adj_cv_n = np.std(adj_cals_n) / np.mean(adj_cals_n)

print(f'\n=== 인접 안정성 (gr 0.4 기준) ===')
print(f'  orig 환경: 평균 {np.mean(adj_cals):.2f}, CV {adj_cv:.3f} {"PASS" if adj_cv < 0.30 else "FAIL"}')
print(f'  no033 환경: 평균 {np.mean(adj_cals_n):.2f}, CV {adj_cv_n:.3f} {"PASS" if adj_cv_n < 0.30 else "FAIL"}')

df = pd.DataFrame(results)
df.to_csv('C:/dev/_tier8c_gr04_20260513.csv', index=False)

msg = '<b>[Tier 8C — gr 0.4 종합 평가]</b>\n\n'
for r in results[:3]:
    msg += f'• {r["name"][:30]}\n  orig {r["orig_7.4y"]:.2f} / no033 {r["no033_7.4y"]:.2f} (delta {r["delta"]:.2f})\n  WF(orig)=[{r["orig_WF1 (19)"]:.1f},{r["orig_WF2 (20-21)"]:.1f},{r["orig_WF3 (22-23)"]:.1f},{r["orig_WF4 (24-26)"]:.1f}] CV={r["cv_orig"]:.2f}\n\n'
msg += f'인접 CV orig {adj_cv:.3f} / no033 {adj_cv_n:.3f}'
send_tg(msg)
print('\ntelegram sent')
