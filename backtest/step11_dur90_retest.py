"""잠정실적 재테스트 — duration 90일 (이전 45일 → Top20 커버리지 0% 버그 수정)

핵심 발견: dur=45에서 Top 20 커버리지 = 0% → 모든 테스트가 무효
dur=90이면 Top 20 커버리지 ~22% → 실질적 테스트 가능
"""
import sys, os, json, glob, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, numpy as np
import requests
from turbo_simulator import TurboSimulator
from pathlib import Path
from copy import deepcopy

PROJECT = Path(__file__).parent.parent
BOT_TOKEN = '8504167814:AAHC_fSmYslVAnKHIneZZOvb_8zRgUpOA9g'
PRIVATE_ID = '7580571403'
def send_tg(msg):
    try: requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                       data={'chat_id': PRIVATE_ID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
    except: pass

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
base_rk = {d: boost[d]['rankings'] for d in dates}
ohlcv = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kospi = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet').iloc[:,0].dropna()
ma170 = kospi.rolling(170).mean()

prov_df = pd.read_parquet(PROJECT/'data_cache'/'provisional_earnings.parquet')
prov_df['rcept_dt'] = pd.to_datetime(prov_df['rcept_dt'])
prov_by_date = {}
for _, row in prov_df.iterrows():
    d = row['rcept_dt'].strftime('%Y%m%d')
    if d not in prov_by_date: prov_by_date[d] = {}
    prov_by_date[d][row['ticker']] = {
        'revenue': row.get('revenue'),
        'op_income': row.get('operating_income'),
    }

def get_active(date_str, dur=90):  # 90일!
    ts = pd.Timestamp(date_str)
    active = {}
    for d, tks in prov_by_date.items():
        d_ts = pd.Timestamp(d)
        if d_ts <= ts and (ts - d_ts).days <= dur:
            active.update(tks)
    return active

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

PERIODS = {'7.8y':('20180702','20260414'), '5.25y':('20210104','20260414')}
WF = {'2018H2-19':('20180702','20191231'),'2020-21':('20200102','20211230'),
      '2022-23':('20220103','20231228'),'2024-26':('20240102','20260414')}
V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)

def run_score(rk_data, periods=None):
    if periods is None: periods = list(PERIODS.keys())
    res = {}
    for pn in periods:
        ps, pe = {**PERIODS, **WF}[pn]
        pd_ = [d for d in dates if ps <= d <= pe and d in rk_data]
        if len(pd_) < 20: continue
        tsim = TurboSimulator({d: rk_data[d] for d in pd_}, pd_, ohlcv)
        reg = calc_regime(pd_)
        r = tsim.run_regime(defense_params=V80_D, offense_params=V80_O,
            regime_dict=reg, trailing_stop=-0.15,
            g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
            g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
        res[pn] = r
    return res

def calc_sc(res):
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    return (c78*c525)**0.5 if c78>0 and c525>0 else 0

def modify_rk(method_fn, dur=90):
    new_rk = {}
    for d in dates:
        active = get_active(d, dur)
        items = deepcopy(base_rk[d])
        items = method_fn(items, active, d)
        new_rk[d] = items
    return new_rk

def test(name, rk):
    res = run_score(rk)
    sc = calc_sc(res)
    delta = sc - bl_sc
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    marker = ' ★★★' if delta > 0.2 else (' ★' if delta > 0 else '')
    print(f'  {name:>45}: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f}){marker}', flush=True)
    results.append({'method':name,'cal_78':c78,'cal_525':c525,'score':sc,'delta':delta})

bl_res = run_score(base_rk, list(PERIODS.keys()) + list(WF.keys()))
bl_sc = calc_sc(bl_res)
print(f'baseline: score={bl_sc:.3f}\n', flush=True)
results = []

# ════════════════════════════════════════
# dur=90으로 핵심 방법 재테스트
# ════════════════════════════════════════

print('='*60)
print('dur=90 핵심 방법 재테스트')
print('='*60, flush=True)

# 1. 좋은 종목 부스트 (이전에 전멸 → 이번엔?)
print('\n[좋은 종목 부스트]', flush=True)
for bs in [0.3, 0.5, 1.0]:
    def m_boost(items, active, d, boost=bs):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op > 0:
                    item['rev_z'] = item.get('rev_z', 0) + boost
                    item['momentum_s'] = item.get('momentum_s', 0) + boost * 0.3
        return items
    rk = modify_rk(m_boost, 90)
    test(f'BOOST_rev+mom_{bs}_dur90', rk)

# 2. 나쁜 종목 페널티 (L 재테스트)
print('\n[나쁜 종목 페널티]', flush=True)
for pen in [0.3, 0.5, 1.0]:
    def m_pen(items, active, d, p=pen):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op < 0:
                    for k in ['rev_z','oca_z','momentum_s','value_s']:
                        item[k] = item.get(k, 0) - p
        return items
    rk = modify_rk(m_pen, 90)
    test(f'PENALTY_all_{pen}_dur90', rk)

# 3. 비대칭 (좋은 소량 + 나쁜 큰 페널티)
print('\n[비대칭]', flush=True)
for good_bs, bad_pen in [(0.3, 0.5), (0.5, 0.5), (0.5, 1.0), (1.0, 0.5), (0.3, 1.0)]:
    def m_asym(items, active, d, gbs=good_bs, bp=bad_pen):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op > 0:
                    item['rev_z'] = item.get('rev_z', 0) + gbs
                    item['momentum_s'] = item.get('momentum_s', 0) + gbs * 0.3
                elif op is not None and op < 0:
                    for k in ['rev_z','oca_z','momentum_s','value_s']:
                        item[k] = item.get(k, 0) - bp
        return items
    rk = modify_rk(m_asym, 90)
    test(f'ASYM_g{good_bs}_b{bad_pen}_dur90', rk)

# 4. 극단 서프라이즈만 (OPM 15%+)
print('\n[극단 서프라이즈]', flush=True)
for bs in [0.5, 1.0, 1.5]:
    def m_extreme(items, active, d, boost=bs):
        for item in items:
            tk = item.get('ticker')
            if tk in active:
                op = active[tk].get('op_income')
                rev = active[tk].get('revenue')
                if op is not None and rev is not None and rev > 0 and op/rev > 0.15:
                    item['rev_z'] = item.get('rev_z', 0) + boost
                    item['momentum_s'] = item.get('momentum_s', 0) + boost * 0.5
        return items
    rk = modify_rk(m_extreme, 90)
    test(f'EXTREME_opm15+_{bs}_dur90', rk)

# 5. Top 20 내만 부스트
print('\n[Top 20 포커스]', flush=True)
for bs in [0.5, 1.0, 1.5]:
    def m_top20(items, active, d, boost=bs):
        for item in items[:20]:
            tk = item.get('ticker')
            if tk in active:
                op = active[tk].get('op_income')
                if op is not None and op > 0:
                    item['rev_z'] = item.get('rev_z', 0) + boost
                    item['momentum_s'] = item.get('momentum_s', 0) + boost * 0.3
        return items
    rk = modify_rk(m_top20, 90)
    test(f'TOP20_boost_{bs}_dur90', rk)

# 6. duration 비교 (60, 90, 120, 180)
print('\n[duration 비교 — 비대칭 g0.5 b0.5]', flush=True)
for dur in [60, 90, 120, 150, 180]:
    def m_dur(items, active, d):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op > 0:
                    item['rev_z'] = item.get('rev_z', 0) + 0.5
                    item['momentum_s'] = item.get('momentum_s', 0) + 0.15
                elif op is not None and op < 0:
                    for k in ['rev_z','oca_z','momentum_s','value_s']:
                        item[k] = item.get(k, 0) - 0.5
        return items
    rk = modify_rk(m_dur, dur)
    test(f'ASYM_g0.5_b0.5_dur{dur}', rk)

# ════════════════════════════════════════
# 종합
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('종합 결과 (dur=90 재테스트)')
print('='*60, flush=True)

df = pd.DataFrame(results).sort_values('score', ascending=False)
print(f'\nbaseline: score={bl_sc:.3f}')
print(f'\nTop 15:')
for i, (_, r) in enumerate(df.head(15).iterrows()):
    marker = ' ★' if r['delta'] > 0 else ''
    print(f'  {i+1:>2}. {r["method"]:>45}: score={r["score"]:.3f} (Δ{r["delta"]:+.3f}){marker}')

improved = df[df['delta'] > 0]
print(f'\nbaseline 초과: {len(improved)}/{len(df)}')

if len(improved) > 0:
    best = improved.iloc[0]
    print(f'\n★ 최고: {best["method"]} score={best["score"]:.3f} (Δ{best["delta"]:+.3f})')

df.to_csv(str(PROJECT/'backtest'/'step11_dur90_retest.csv'), index=False, encoding='utf-8-sig')

send_tg(f'<b>[잠정실적 dur=90 재테스트 결과]</b>\n\n'
        f'이전 dur=45: Top20 커버리지 0% (무효!)\n'
        f'이번 dur=90: Top20 커버리지 22%\n\n'
        f'baseline: {bl_sc:.3f}\n'
        f'최고: {df.iloc[0]["method"]}\n'
        f'score={df.iloc[0]["score"]:.3f} (Δ{df.iloc[0]["delta"]:+.3f})\n'
        f'baseline 초과: {len(improved)}/{len(df)}')
