"""Tier 3 — Top 5 후보 WF stability + 안정성 검증

Tier 2 Top 5 + baseline + Tier 1 best 비교.
4구간 WF + CV + 인접 안정성.

후보:
  1. baseline (e3 sb3 sd5 SL-10 TS-15 gr0.6) — 현 production
  2. Tier 1 best (e2 sb5 sd5 SL-7 TS-10 gr0.6) — Tier 1 Top
  3. v80.5 (e2 sb5 sd5 SL-10 TS-8 gr0.5) — Tier 2 plateau 대표
  4. Tier 2 best (e2 sb5 sd4 SL-10 TS-8 gr0.5) — Tier 2 Top 1
  5. Tier 2 slot7 (e2 sb7 sd7 SL-10 TS-8 gr0.5) — Tier 2 큰 slot
  6. v80.5 conservative (e2 sb5 sd5 SL-10 TS-10 gr0.5) — TS 보수적

각 5 후보 × 5 구간 = 30 BT
인접 안정성 추가 (v80.5 ±1) = 6 후보 × 5 구간 = 30 BT
총 ~60 BT ≈ 2분
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

# === 데이터 로드 ===
print('=== Tier 3 — 데이터 로드 ===', flush=True)
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

# 구간
PERIODS = {
    '7.4y': ('20190102', '20260512'),
    'WF1 (19)':    ('20190102', '20191231'),
    'WF2 (20-21)': ('20200102', '20211230'),
    'WF3 (22-23)': ('20220103', '20231228'),
    'WF4 (24-26)': ('20240102', '20260512'),
}

# 각 구간별 TSIM (재사용)
print('  TSIM 초기화 (구간별)...', flush=True)
TSIMS = {}
for pname, (ps, pe) in PERIODS.items():
    pdates = [d for d in all_dates if ps <= d <= pe]
    if len(pdates) < 50: continue
    TSIMS[pname] = (pdates, TurboSimulator({d: boost_rk[d] for d in pdates}, pdates, ohlcv),
                    calc_regime(pdates))
print(f'  로드 완료: {time.time()-t_start:.1f}초\n', flush=True)

GS_FIXED = ('rev_z', 'oca_z', None, None, None, None)
DEFENSE_BASE = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'mom':'6m-1m'}

# === 후보 ===
candidates = [
    # (name, entry, sb, sd, SL, TS, gr)
    ('baseline (e3 sb3 sd5 SL10 TS15 gr0.6)', 3, 3, 5, -0.10, -0.15, 0.6),
    ('Tier1 best (e2 sb5 sd5 SL7 TS10 gr0.6)', 2, 5, 5, -0.07, -0.10, 0.6),
    ('v80.5 plateau (e2 sb5 sd5 SL10 TS8 gr0.5)', 2, 5, 5, -0.10, -0.08, 0.5),
    ('Tier2 best (e2 sb5 sd4 SL10 TS8 gr0.5)', 2, 5, 4, -0.10, -0.08, 0.5),
    ('v80.5 slot7 (e2 sb7 sd7 SL10 TS8 gr0.5)', 2, 7, 7, -0.10, -0.08, 0.5),
    ('v80.5 conserv TS10 (e2 sb5 sd5 SL10 TS10 gr0.5)', 2, 5, 5, -0.10, -0.10, 0.5),
    # 인접 안정성 — v80.5 plateau ±1 변형
    ('adj: sb4', 2, 4, 5, -0.10, -0.08, 0.5),
    ('adj: sb6', 2, 6, 5, -0.10, -0.08, 0.5),
    ('adj: sd4', 2, 5, 4, -0.10, -0.08, 0.5),  # = Tier 2 best
    ('adj: sd6', 2, 5, 6, -0.10, -0.08, 0.5),
    ('adj: SL-9', 2, 5, 5, -0.09, -0.08, 0.5),
    ('adj: SL-11', 2, 5, 5, -0.11, -0.08, 0.5),
    ('adj: TS-7', 2, 5, 5, -0.10, -0.07, 0.5),
    ('adj: TS-9', 2, 5, 5, -0.10, -0.09, 0.5),
    ('adj: gr0.4', 2, 5, 5, -0.10, -0.08, 0.4),
    ('adj: gr0.6', 2, 5, 5, -0.10, -0.08, 0.6),
]

# === 실행 ===
print('=== BT 실행 ===', flush=True)
results = []
for name, entry, sb, sd, sl, ts, gr in candidates:
    boost_p = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':gr,
               'entry':entry,'exit':6,'slots':sb,'mom':'12m'}
    defense_p = {**DEFENSE_BASE, 'slots':sd}
    row = {'name': name, 'entry':entry,'sb':sb,'sd':sd,'sl':sl,'ts':ts,'gr':gr}
    for pname, (pdates, tsim, reg) in TSIMS.items():
        try:
            r = tsim.run_regime(defense_params=defense_p, offense_params=boost_p,
                                regime_dict=reg, trailing_stop=ts, stop_loss=sl,
                                g_sub1_o=GS_FIXED[0], g_sub2_o=GS_FIXED[1], g_sub3_o=GS_FIXED[2],
                                g_w1_o=GS_FIXED[3], g_w2_o=GS_FIXED[4], g_w3_o=GS_FIXED[5],
                                g_sub1_d=GS_FIXED[0], g_sub2_d=GS_FIXED[1], g_sub3_d=GS_FIXED[2],
                                g_w1_d=GS_FIXED[3], g_w2_d=GS_FIXED[4], g_w3_d=GS_FIXED[5])
            row[pname] = r['calmar']
            if pname == '7.4y':
                row['cagr'] = r['cagr']
                row['mdd'] = r['mdd']
                row['sharpe'] = r['sharpe']
        except Exception as e:
            row[pname] = 0
    # CV
    wf_vals = [row.get(p, 0) for p in PERIODS if p.startswith('WF')]
    row['wf_min'] = min(wf_vals)
    row['wf_mean'] = np.mean(wf_vals)
    row['cv'] = np.std(wf_vals) / np.mean(wf_vals) if np.mean(wf_vals) > 0 else 99
    results.append(row)
    print(f'  {name}: 7.4y={row.get("7.4y",0):.2f} WF=[{wf_vals[0]:.2f},{wf_vals[1]:.2f},{wf_vals[2]:.2f},{wf_vals[3]:.2f}] CV={row["cv"]:.2f}', flush=True)

# === 출력 표 ===
print('\n' + '=' * 110)
print(f'{"name":<48} {"7.4y":>6} {"CAGR":>6} {"MDD":>6} {"WF1":>6} {"WF2":>6} {"WF3":>6} {"WF4":>6} {"min":>5} {"mean":>5} {"CV":>5}')
print('-' * 110)
bl_cal = results[0]['7.4y']
for r in sorted(results, key=lambda x: x['7.4y'], reverse=True):
    delta = r['7.4y'] - bl_cal
    mark = ' ⭐' if delta > 0.5 and r['cv'] < 0.85 else (' *' if delta > 0 else '')
    print(f'{r["name"][:47]:<48} {r["7.4y"]:>6.2f} {r["cagr"]:>6.1f} {r["mdd"]:>6.1f} '
          f'{r["WF1 (19)"]:>6.2f} {r["WF2 (20-21)"]:>6.2f} {r["WF3 (22-23)"]:>6.2f} {r["WF4 (24-26)"]:>6.2f} '
          f'{r["wf_min"]:>5.2f} {r["wf_mean"]:>5.2f} {r["cv"]:>5.2f}{mark}')

# 인접 안정성 — v80.5 plateau 기준
print('\n=== 인접 안정성 (v80.5 plateau 기준) ===')
plateau = next(r for r in results if 'plateau' in r['name'])
adj_results = [r for r in results if r['name'].startswith('adj:')]
adj_cals = [plateau['7.4y']] + [r['7.4y'] for r in adj_results]
adj_cv = np.std(adj_cals) / np.mean(adj_cals)
print(f'  plateau Cal: {plateau["7.4y"]:.2f}')
print(f'  인접 Cal 평균: {np.mean(adj_cals):.2f}, 표준편차: {np.std(adj_cals):.2f}')
print(f'  인접 CV: {adj_cv:.3f} {"PASS (<0.30)" if adj_cv < 0.30 else "FAIL"}')

# 저장
df = pd.DataFrame(results)
df.to_csv('C:/dev/_tier3_wf_results_20260513.csv', index=False)
print(f'\n저장: C:/dev/_tier3_wf_results_20260513.csv')

# 텔레그램
msg = '<b>[Tier 3 — WF + 인접 안정성]</b>\n\n'
msg += f'baseline Cal: {bl_cal:.2f}\n\n<b>Top 후보:</b>\n'
for r in sorted(results, key=lambda x: x['7.4y'], reverse=True)[:7]:
    if r['name'].startswith('adj:'): continue
    d = r['7.4y'] - bl_cal
    msg += f'• {r["name"][:35]}\n  Cal={r["7.4y"]:.2f} ({d:+.2f}) CAGR={r["cagr"]:.0f}% MDD={r["mdd"]:.0f}% CV={r["cv"]:.2f}\n'
msg += f'\n인접 CV: {adj_cv:.3f} ({"PASS" if adj_cv < 0.30 else "FAIL"})'
send_tg(msg)
print('telegram sent')
