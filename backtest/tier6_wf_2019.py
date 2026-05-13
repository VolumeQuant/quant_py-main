"""Tier 6+ WF 검증 — v80.6 통합 후보 4구간 WF + 인접 안정성

비교 후보:
  1. baseline (현 production)
  2. v80.5 — boost+defense 변경, regime 그대로
  3. v80.6 — 모든 변경 (MA250/8d)
  4~ 인접 안정성 (MA240/8d, MA260/8d, MA250/7d, MA250/9d, MA200/10d)
"""
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

print('=== Tier 6+ WF 검증 ===', flush=True)
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
MA_CACHE = {p: kospi.rolling(p).mean() for p in [170, 200, 240, 250, 260]}

PERIODS = {
    '7.4y': ('20190102', '20260512'),
    'WF1 (19)':    ('20190102', '20191231'),
    'WF2 (20-21)': ('20200102', '20211230'),
    'WF3 (22-23)': ('20220103', '20231228'),
    'WF4 (24-26)': ('20240102', '20260512'),
}

print('  TSIM 초기화...', flush=True)
TSIMS = {}
for pname, (ps, pe) in PERIODS.items():
    pdates = [d for d in all_dates if ps <= d <= pe]
    if len(pdates) < 50: continue
    TSIMS[pname] = (pdates, TurboSimulator({d: boost_rk[d] for d in pdates}, pdates, ohlcv))
print(f'  로드 완료: {time.time()-t_start:.1f}초\n', flush=True)

def calc_regime(target_dates, ma_period, confirm):
    ma = MA_CACHE[ma_period]
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

# 후보 (regime, boost, defense, sl, ts, name)
BOOST_BASELINE = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.6,
                  'entry':3,'exit':6,'slots':3,'mom':'12m'}
BOOST_V805 = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.5,
              'entry':2,'exit':6,'slots':5,'mom':'12m'}
DEFENSE_BASELINE = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,
                    'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
DEFENSE_T4 = {'v':0.35,'q':0.15,'g':0.15,'m':0.35,'g_rev':0.8,
              'entry':3,'exit':6,'slots':4,'mom':'6m-1m'}

candidates = [
    ('baseline (MA170/8d + 옛 boost/def)', (170,8), BOOST_BASELINE, DEFENSE_BASELINE, -0.10, -0.15),
    ('v80.5 (MA170/8d + 새 boost/def)',    (170,8), BOOST_V805,     DEFENSE_T4,        -0.10, -0.08),
    ('v80.6 (MA250/8d 통합)',              (250,8), BOOST_V805,     DEFENSE_T4,        -0.10, -0.08),
    # 인접 안정성
    ('adj: MA240/8d',                      (240,8), BOOST_V805,     DEFENSE_T4,        -0.10, -0.08),
    ('adj: MA260/8d',                      (260,8), BOOST_V805,     DEFENSE_T4,        -0.10, -0.08),
    ('adj: MA250/7d',                      (250,7), BOOST_V805,     DEFENSE_T4,        -0.10, -0.08),
    ('adj: MA250/9d',                      (250,9), BOOST_V805,     DEFENSE_T4,        -0.10, -0.08),
    ('adj: MA200/10d',                     (200,10), BOOST_V805,    DEFENSE_T4,        -0.10, -0.08),
]

print('=== BT 실행 ===', flush=True)
results = []
for name, (ma_p, conf), boost_p, defense_p, sl, ts in candidates:
    row = {'name': name, 'ma': ma_p, 'conf': conf}
    for pname, (pdates, tsim) in TSIMS.items():
        reg = calc_regime(pdates, ma_p, conf)
        try:
            r = tsim.run_regime(defense_params=defense_p, offense_params=boost_p,
                                regime_dict=reg, trailing_stop=ts, stop_loss=sl,
                                g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
                                g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
                                g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
                                g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
            row[pname] = r['calmar']
            if pname == '7.4y':
                row['cagr'] = r['cagr']
                row['mdd'] = r['mdd']
                row['sharpe'] = r['sharpe']
        except Exception as e:
            row[pname] = 0
    wf_vals = [row.get(p, 0) for p in PERIODS if p.startswith('WF')]
    row['wf_min'] = min(wf_vals)
    row['wf_mean'] = np.mean(wf_vals)
    row['cv'] = np.std(wf_vals) / np.mean(wf_vals) if np.mean(wf_vals) > 0 else 99
    results.append(row)
    print(f'  {name}: 7.4y={row.get("7.4y",0):.2f} WF=[{wf_vals[0]:.2f},{wf_vals[1]:.2f},{wf_vals[2]:.2f},{wf_vals[3]:.2f}] CV={row["cv"]:.2f}', flush=True)

# 출력 표
print('\n' + '=' * 115)
print(f'{"name":<42} {"7.4y":>6} {"CAGR":>6} {"MDD":>6} {"WF1":>6} {"WF2":>6} {"WF3":>6} {"WF4":>6} {"min":>5} {"mean":>5} {"CV":>5}')
print('-' * 115)
bl = results[0]
for r in results:
    delta = r['7.4y'] - bl['7.4y']
    mark = ' ⭐' if delta > 1.0 else (' ✓' if delta > 0 else '')
    print(f'{r["name"][:41]:<42} {r["7.4y"]:>6.2f} {r["cagr"]:>6.1f} {r["mdd"]:>6.1f} '
          f'{r["WF1 (19)"]:>6.2f} {r["WF2 (20-21)"]:>6.2f} {r["WF3 (22-23)"]:>6.2f} {r["WF4 (24-26)"]:>6.2f} '
          f'{r["wf_min"]:>5.2f} {r["wf_mean"]:>5.2f} {r["cv"]:>5.2f}{mark}')

# 인접 안정성 (v80.6 기준)
print('\n=== 인접 안정성 (v80.6 통합 기준) ===')
v806 = next(r for r in results if 'v80.6 (MA250/8d' in r['name'])
adj = [r for r in results if r['name'].startswith('adj:')]
adj_cals = [v806['7.4y']] + [r['7.4y'] for r in adj]
adj_cv = np.std(adj_cals) / np.mean(adj_cals)
print(f'  v80.6 Cal: {v806["7.4y"]:.2f}')
print(f'  인접 5 평균: {np.mean(adj_cals):.2f}, 표준편차: {np.std(adj_cals):.2f}')
print(f'  인접 CV: {adj_cv:.3f} {"PASS (<0.30)" if adj_cv < 0.30 else "FAIL"}')

# 저장 + 텔레그램
df = pd.DataFrame(results)
df.to_csv('C:/dev/_tier6_wf_results_20260513.csv', index=False)

msg = '<b>[Tier 6+ WF 검증]</b>\n\n'
msg += f'baseline Cal: {bl["7.4y"]:.2f}\n\n'
for r in results[:3]:
    msg += f'• {r["name"][:40]}\n  Cal={r["7.4y"]:.2f} CAGR={r["cagr"]:.0f}% MDD={r["mdd"]:.0f}%\n  WF=[{r["WF1 (19)"]:.1f},{r["WF2 (20-21)"]:.1f},{r["WF3 (22-23)"]:.1f},{r["WF4 (24-26)"]:.1f}] CV={r["cv"]:.2f}\n\n'
msg += f'인접 CV: {adj_cv:.3f} ({"PASS" if adj_cv < 0.30 else "FAIL"})'
send_tg(msg)
print('\ntelegram sent')
