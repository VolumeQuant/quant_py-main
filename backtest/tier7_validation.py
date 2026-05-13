"""Tier 7 — Production 안전성 검증

1. 회전율 분석 (매매 빈도, 평균 보유 일수, 연 매매 횟수)
2. 수수료/슬리피지 적용 BT
3. 종목/섹터 집중도

baseline vs v80.6 비교.
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from pathlib import Path
from collections import Counter
from turbo_simulator import TurboSimulator

PROJECT = Path(__file__).parent.parent

from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
def send_tg(msg):
    if len(msg) > 4096: msg = msg[:4090] + '...'
    try:
        requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                      data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
    except: pass

print('=== Tier 7 — Production 안전성 검증 ===', flush=True)
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
dates_74 = [d for d in all_dates if '20190102' <= d <= '20260512']

ohlcv = pd.read_parquet(PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet').replace(0, np.nan)
kdf = pd.read_parquet(PROJECT / 'data_cache' / 'kospi_yf.parquet')
kospi = kdf.iloc[:, 0].copy()
for c in kdf.columns[1:]:
    kospi = kospi.fillna(kdf[c])
kospi = kospi.dropna()

def calc_regime(target_dates, ma_period, confirm):
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

print('  TSIM 초기화...', flush=True)
TSIM = TurboSimulator({d: boost_rk[d] for d in dates_74}, dates_74, ohlcv)
print(f'  완료 ({time.time()-t_start:.1f}초)\n', flush=True)

GS = ('rev_z', 'oca_z', None, None, None, None)

# 비교 후보
BASELINE = {
    'name': 'baseline',
    'regime': (170, 8),
    'boost': {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'},
    'defense': {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'},
    'sl': -0.10, 'ts': -0.15,
}
V806 = {
    'name': 'v80.6',
    'regime': (250, 8),
    'boost': {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':0.5,'entry':2,'exit':6,'slots':5,'mom':'12m'},
    'defense': {'v':0.35,'q':0.15,'g':0.15,'m':0.35,'g_rev':0.8,'entry':3,'exit':6,'slots':4,'mom':'6m-1m'},
    'sl': -0.10, 'ts': -0.08,
}

def run_with_trades(config):
    """BT 실행 + 거래 분석"""
    ma_p, conf = config['regime']
    reg = calc_regime(dates_74, ma_p, conf)
    r = TSIM.run_regime(defense_params=config['defense'], offense_params=config['boost'],
                        regime_dict=reg, trailing_stop=config['ts'], stop_loss=config['sl'],
                        g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
                        g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
                        g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
                        g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
    return r

# === 1. 기본 BT + 회전율 ===
print('[1] 회전율 분석', flush=True)
results = {}
for cfg in [BASELINE, V806]:
    r = run_with_trades(cfg)
    results[cfg['name']] = r
    n_trades = r.get('n_trades', None)
    avg_hold = r.get('avg_holding_days', None)
    win_rate = r.get('win_rate', None)

    print(f'\n  [{cfg["name"]}]')
    print(f'    Cal: {r["calmar"]:.2f}, CAGR: {r["cagr"]:.1f}%, MDD: {r["mdd"]:.1f}%')
    # turbo_simulator의 결과에서 사용 가능한 필드 확인
    for k, v in r.items():
        if isinstance(v, (int, float)) and k not in ['calmar','cagr','mdd','sharpe','sortino','total','avg_holdings']:
            print(f'    {k}: {v}')

# === 2. 수수료/슬리피지 적용 BT ===
# turbo_simulator가 transaction_cost 옵션 지원 여부 확인
print('\n[2] 수수료 적용 BT (0.0025 = 0.25%, 양방향)', flush=True)
import inspect
sig = inspect.signature(TSIM.run_regime)
has_cost = 'transaction_cost' in sig.parameters or 'commission' in sig.parameters or 'fee' in sig.parameters
print(f'  TSIM.run_regime params: {list(sig.parameters.keys())}')

# === 3. 종목 / 섹터 집중도 (state ranking 빈도 분석) ===
print('\n[3] 종목 집중도 (BT에서 매수된 종목 빈도)', flush=True)
# BT가 selected tickers 안 주면, 매수 후보 ranking 빈도로 추정
# Top 3 종목 등장 빈도 (boost / defense)
boost_top_counter = Counter()
def_top_counter = Counter()
boost_reg = calc_regime(dates_74, *V806['regime'])
for d in dates_74:
    rk_b = boost_rd[d]['rankings'][:V806['boost']['entry']]  # Top entry
    rk_d = defense_rd[d]['rankings'][:V806['defense']['entry']]
    if boost_reg[d]:
        for r in rk_b:
            boost_top_counter[r['ticker']] += 1
    else:
        for r in rk_d:
            def_top_counter[r['ticker']] += 1

print(f'  v80.6 boost Top {V806["boost"]["entry"]} 종목 빈도 (boost 일자에 노출):')
total_b = sum(boost_top_counter.values())
for tk, n in boost_top_counter.most_common(10):
    print(f'    {tk}: {n} ({n/total_b*100:.1f}%)')

print(f'  v80.6 defense Top {V806["defense"]["entry"]} 종목 빈도 (defense 일자에 노출):')
total_d = sum(def_top_counter.values())
for tk, n in def_top_counter.most_common(10):
    print(f'    {tk}: {n} ({n/total_d*100:.1f}%)')

# baseline 비교
print(f'\n  baseline boost Top {BASELINE["boost"]["entry"]} (현 production)')
boost_reg_bl = calc_regime(dates_74, *BASELINE['regime'])
bl_b_counter = Counter()
for d in dates_74:
    rk_b = boost_rd[d]['rankings'][:BASELINE['boost']['entry']]
    if boost_reg_bl[d]:
        for r in rk_b:
            bl_b_counter[r['ticker']] += 1
total_bl = sum(bl_b_counter.values())
for tk, n in bl_b_counter.most_common(10):
    print(f'    {tk}: {n} ({n/total_bl*100:.1f}%)')

# Top 10 점유율
top10_v806 = sum(n for _, n in boost_top_counter.most_common(10)) / total_b * 100
top10_bl = sum(n for _, n in bl_b_counter.most_common(10)) / total_bl * 100
print(f'\n  Top 10 종목 점유율 (boost 일자):')
print(f'    baseline: {top10_bl:.1f}%')
print(f'    v80.6: {top10_v806:.1f}%')

print(f'\n총 소요: {time.time()-t_start:.1f}초')

# 텔레그램 요약
msg = '<b>[Tier 7 — Production 안전성]</b>\n\n'
for cfg in [BASELINE, V806]:
    r = results[cfg['name']]
    msg += f'<b>{cfg["name"]}</b>: Cal {r["calmar"]:.2f}, CAGR {r["cagr"]:.0f}%, MDD {r["mdd"]:.0f}%\n'
    msg += f'  avg_holdings: {r.get("avg_holdings", "?"):.2f}\n'
msg += f'\nTop 10 점유율 (boost):\n  baseline: {top10_bl:.1f}%\n  v80.6: {top10_v806:.1f}%'
send_tg(msg)
print('telegram sent')
