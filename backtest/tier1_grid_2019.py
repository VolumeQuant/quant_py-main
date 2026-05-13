"""Tier 1 — Coarse grid search (2019-01 시작 7.4년 baseline)

WF stability 인사이트 기반 변수만 흔듦. VQGM/MOM/G_SUB은 baseline 고정.
TurboSimulator 캐시 1회 로드 후 _ensure_cache 패턴으로 모든 조합 재사용.

변수:
  entry (boost): 1, 2, 3
  slots_boost: 3, 5, 7
  slots_defense: 3, 5, 7
  SL: -5, -7, -10, -13 (boost+defense 동일)
  TS: -10, -15, -20
  G_REV (boost): 0.4, 0.6, 0.8

총 3×3×3×4×3×3 = 972 조합 ≈ 10분 (633ms/combo)

baseline 고정:
  공격: V15Q0G55M30, MOM 12m
  방어: V30Q15G15M40, MOM 6m-1m, G_REV 0.7, entry 3, exit 6
  G_SUB: 2f rev_z + oca_z (둘 다)
"""
import sys, os, json, glob, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from pathlib import Path
from itertools import product
from turbo_simulator import TurboSimulator

PROJECT = Path(__file__).parent.parent

# 텔레그램
from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
def send_tg(msg):
    if len(msg) > 4096: msg = msg[:4090] + '...'
    try:
        requests.post(f'https://api.telegram.org/bot{BOT}/sendMessage',
                      data={'chat_id': PID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
    except: pass

# === 데이터 로드 (1회) ===
print('=== Tier 1 — 데이터 로드 ===', flush=True)
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

# 7.4년 구간 필터
START, END = '20190102', '20260512'
dates_74 = [d for d in all_dates if START <= d <= END]
print(f'  거래일: {len(dates_74)} ({dates_74[0]} ~ {dates_74[-1]})', flush=True)

ohlcv = pd.read_parquet(PROJECT / 'data_cache' / 'all_ohlcv_20170601_20260512.parquet').replace(0, np.nan)
print(f'  OHLCV: {ohlcv.shape}', flush=True)

kdf = pd.read_parquet(PROJECT / 'data_cache' / 'kospi_yf.parquet')
kospi = kdf.iloc[:, 0].copy()
for c in kdf.columns[1:]:
    kospi = kospi.fillna(kdf[c])
kospi = kospi.dropna()
ma170 = kospi.rolling(170).mean()

# Regime 사전계산 (모든 일자, MA170 8d)
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
REGIME = calc_regime(dates_74)
boost_days = sum(1 for d in dates_74 if REGIME[d])
print(f'  국면: boost {boost_days}일, defense {len(dates_74)-boost_days}일', flush=True)

# TurboSimulator 1회 생성 (캐시 재사용용)
print('  TurboSimulator 초기화...', flush=True)
TSIM = TurboSimulator({d: boost_rk[d] for d in dates_74}, dates_74, ohlcv)
print(f'  데이터 로드 완료: {time.time()-t_start:.1f}초\n', flush=True)

# === Defense baseline (고정) ===
DEFENSE_BASE = {
    'v': 0.30, 'q': 0.15, 'g': 0.15, 'm': 0.40,
    'g_rev': 0.7, 'entry': 3, 'exit': 6, 'mom': '6m-1m',
}
GS_FIXED = ('rev_z', 'oca_z', None, None, None, None)  # 2f, boost+defense 동일

# === Tier 1 격자 ===
ENTRY_BOOST = [1, 2, 3]
SLOTS_BOOST = [3, 5, 7]
SLOTS_DEF = [3, 5, 7]
SL_VALS = [-0.05, -0.07, -0.10, -0.13]
TS_VALS = [-0.10, -0.15, -0.20]
G_REV_BOOST = [0.4, 0.6, 0.8]

total = len(ENTRY_BOOST) * len(SLOTS_BOOST) * len(SLOTS_DEF) * len(SL_VALS) * len(TS_VALS) * len(G_REV_BOOST)
print(f'=== Tier 1 격자 ===')
print(f'  entry × slots_b × slots_d × SL × TS × G_REV = '
      f'{len(ENTRY_BOOST)}×{len(SLOTS_BOOST)}×{len(SLOTS_DEF)}×{len(SL_VALS)}×{len(TS_VALS)}×{len(G_REV_BOOST)} = {total}조합')
print(f'  예상 시간: {total*0.7/60:.1f}분 (633ms/combo 가정)\n', flush=True)

# === 표본 5건 ===
print('  [표본 5건]', flush=True)
t_sample = time.time()
sample_count = 0
for entry, sb, sd, sl, ts, gr in product(ENTRY_BOOST, SLOTS_BOOST, SLOTS_DEF, SL_VALS, TS_VALS, G_REV_BOOST):
    boost_p = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':gr,
               'entry':entry,'exit':6,'slots':sb,'mom':'12m'}
    defense_p = {**DEFENSE_BASE, 'slots':sd}
    t0 = time.time()
    r = TSIM.run_regime(defense_params=defense_p, offense_params=boost_p,
                        regime_dict=REGIME, trailing_stop=ts, stop_loss=sl,
                        g_sub1_o=GS_FIXED[0], g_sub2_o=GS_FIXED[1], g_sub3_o=GS_FIXED[2],
                        g_w1_o=GS_FIXED[3], g_w2_o=GS_FIXED[4], g_w3_o=GS_FIXED[5],
                        g_sub1_d=GS_FIXED[0], g_sub2_d=GS_FIXED[1], g_sub3_d=GS_FIXED[2],
                        g_w1_d=GS_FIXED[3], g_w2_d=GS_FIXED[4], g_w3_d=GS_FIXED[5])
    elapsed = time.time() - t0
    print(f'    e{entry} sb{sb} sd{sd} SL{sl:.0%} TS{ts:.0%} gr{gr}: '
          f'Cal={r["calmar"]:.2f} CAGR={r["cagr"]:.0f}% MDD={r["mdd"]:.0f}% ({elapsed*1000:.0f}ms)', flush=True)
    sample_count += 1
    if sample_count >= 5: break
sample_avg = (time.time() - t_sample) / 5
print(f'  표본 평균: {sample_avg*1000:.0f}ms/combo')
print(f'  예상 잔여: {(total-5)*sample_avg/60:.1f}분\n', flush=True)

# === 전체 실행 ===
print('=== 전체 격자 실행 ===', flush=True)
results = []
t0 = time.time()
count = 0
for entry, sb, sd, sl, ts, gr in product(ENTRY_BOOST, SLOTS_BOOST, SLOTS_DEF, SL_VALS, TS_VALS, G_REV_BOOST):
    boost_p = {'v':0.15,'q':0.0,'g':0.55,'m':0.30,'g_rev':gr,
               'entry':entry,'exit':6,'slots':sb,'mom':'12m'}
    defense_p = {**DEFENSE_BASE, 'slots':sd}
    try:
        r = TSIM.run_regime(defense_params=defense_p, offense_params=boost_p,
                            regime_dict=REGIME, trailing_stop=ts, stop_loss=sl,
                            g_sub1_o=GS_FIXED[0], g_sub2_o=GS_FIXED[1], g_sub3_o=GS_FIXED[2],
                            g_w1_o=GS_FIXED[3], g_w2_o=GS_FIXED[4], g_w3_o=GS_FIXED[5],
                            g_sub1_d=GS_FIXED[0], g_sub2_d=GS_FIXED[1], g_sub3_d=GS_FIXED[2],
                            g_w1_d=GS_FIXED[3], g_w2_d=GS_FIXED[4], g_w3_d=GS_FIXED[5])
        results.append({
            'entry': entry, 'sb': sb, 'sd': sd, 'sl': sl, 'ts': ts, 'gr': gr,
            'cal': r['calmar'], 'cagr': r['cagr'], 'mdd': r['mdd'],
            'sharpe': r['sharpe'], 'sortino': r['sortino'],
        })
    except Exception as e:
        results.append({'entry':entry,'sb':sb,'sd':sd,'sl':sl,'ts':ts,'gr':gr,
                        'cal':0,'cagr':0,'mdd':99,'sharpe':0,'sortino':0,'err':str(e)[:50]})
    count += 1
    if count % 50 == 0 or count == total:
        elapsed = time.time() - t0
        avg = elapsed / count
        remain = avg * (total - count) / 60
        print(f'  {count}/{total} ({elapsed/60:.1f}분 경과, {remain:.1f}분 남음)', flush=True)

wall = time.time() - t0
print(f'\n=== 완료: {wall/60:.1f}분, 평균 {wall/total*1000:.0f}ms/combo ===\n', flush=True)

# === 결과 분석 ===
df = pd.DataFrame(results)
df_sorted = df.sort_values('cal', ascending=False)

# baseline (현재 production) 비교
baseline_match = df[(df.entry==3) & (df.sb==3) & (df.sd==5) & (df.sl==-0.10) & (df.ts==-0.15) & (df.gr==0.6)]
if not baseline_match.empty:
    bl = baseline_match.iloc[0]
    print(f'baseline (e3 sb3 sd5 SL-10 TS-15 gr0.6): Cal={bl["cal"]:.2f} CAGR={bl["cagr"]:.0f}% MDD={bl["mdd"]:.0f}%\n')

# Top 30
print('=' * 90)
print(f'{"순위":>4} {"entry":>5} {"sb":>3} {"sd":>3} {"SL":>5} {"TS":>5} {"gr":>4} {"Cal":>6} {"CAGR":>6} {"MDD":>6} {"Sharpe":>7}')
print('-' * 90)
for i, (_, r) in enumerate(df_sorted.head(30).iterrows(), 1):
    print(f'{i:>4} {r.entry:>5.0f} {r.sb:>3.0f} {r.sd:>3.0f} {r.sl:>5.0%} {r.ts:>5.0%} {r.gr:>4.1f} '
          f'{r.cal:>6.2f} {r.cagr:>6.1f} {r.mdd:>6.1f} {r.sharpe:>7.2f}')

# 결과 저장
df.to_csv(PROJECT / '_tier1_results_20260513.csv', index=False)
print(f'\n저장: {PROJECT}/_tier1_results_20260513.csv')

# 텔레그램
top10 = df_sorted.head(10)
msg = '<b>[Tier 1 grid 결과 — 7.4년 2019 baseline]</b>\n\n'
msg += f'총 {total}조합, {wall/60:.1f}분\n\n'
msg += '<b>Top 10:</b>\n'
for i, (_, r) in enumerate(top10.iterrows(), 1):
    msg += f'{i}. e{int(r.entry)} sb{int(r.sb)} sd{int(r.sd)} SL{int(r.sl*100)}% TS{int(r.ts*100)}% gr{r.gr}: '
    msg += f'Cal={r.cal:.2f} CAGR={r.cagr:.0f}% MDD={r.mdd:.0f}%\n'
send_tg(msg)
print('telegram sent')
