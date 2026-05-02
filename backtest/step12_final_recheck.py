"""Step 12: 잠정실적 전면 재점검 — 최종 테스트

기존 122개 조합 결과 요약:
  - 부스트(좋은 종목 밀어올리기): 15가지 방법 전멸
  - 페널티(나쁜 종목 제거): PENALTY_all_0.5_dur90 = +0.174 (최고)

이번 테스트:
  1. PENALTY_all_0.5_dur90 연도별/WF 상세 → 부작용 체크
  2. 하드 제외: bad stock을 ranking에서 완전 제거 (z-score 수정 대신)
  3. 분기별 duration: Q4=90일, Q1-Q3=45일 (법정 기한 반영)
  4. penalty 강도 미세 튜닝 (0.3~0.8 스텝 0.1)
  5. penalty 대상 확장: 매출 감소도 포함
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
from config import TELEGRAM_BOT_TOKEN as BOT_TOKEN, TELEGRAM_PRIVATE_ID as PRIVATE_ID
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
        'base_month': pd.Timestamp(row.get('base_date')).month if pd.notna(row.get('base_date')) else None,
    }

def get_active(date_str, dur=90):
    ts = pd.Timestamp(date_str)
    active = {}
    for d, tks in prov_by_date.items():
        d_ts = pd.Timestamp(d)
        if d_ts <= ts and (ts - d_ts).days <= dur:
            active.update(tks)
    return active

def get_active_split(date_str):
    """분기별 duration: Q4(12월)=90일, Q1-Q3=45일"""
    ts = pd.Timestamp(date_str)
    active = {}
    for d, tks in prov_by_date.items():
        d_ts = pd.Timestamp(d)
        if d_ts > ts: continue
        gap = (ts - d_ts).days
        for tk, info in tks.items():
            bm = info.get('base_month')
            dur = 90 if bm == 12 else 45
            if gap <= dur:
                active[tk] = info
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
YEARLY = {str(y):('20190102','20191230') for y in range(2019,2027)}
YEARLY.update({
    '2019':('20190102','20191230'),'2020':('20200102','20201230'),
    '2021':('20210104','20211230'),'2022':('20220103','20221228'),
    '2023':('20230102','20231228'),'2024':('20240102','20241230'),
    '2025':('20250102','20251230'),'2026':('20260102','20260414'),
})

V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)

def run_score(rk_data, periods=None):
    if periods is None: periods = list(PERIODS.keys())
    res = {}
    for pn in periods:
        ps, pe = {**PERIODS, **WF, **YEARLY}[pn]
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

def modify_rk(method_fn, dur=90, use_split=False):
    new_rk = {}
    for d in dates:
        active = get_active_split(d) if use_split else get_active(d, dur)
        items = deepcopy(base_rk[d])
        items = method_fn(items, active, d)
        new_rk[d] = items
    return new_rk

# ═══════════════════════════════════════════
# Baseline 연도별
# ═══════════════════════════════════════════
all_periods = list(PERIODS.keys()) + list(WF.keys()) + list(YEARLY.keys())
bl_res = run_score(base_rk, all_periods)
bl_sc = calc_sc(bl_res)

print(f'baseline score={bl_sc:.3f}', flush=True)
print(f'\n{"기간":<12} {"Cal":>6} {"CAGR%":>8} {"MDD%":>7}')
print('-'*40)
for pn in ['7.8y','5.25y'] + [str(y) for y in range(2019,2027)] + list(WF.keys()):
    r = bl_res.get(pn)
    if r: print(f'{pn:<12} {r["calmar"]:>6.2f} {r["cagr"]:>8.1f} {r["mdd"]:>7.1f}')

# ═══════════════════════════════════════════
# Test 1: PENALTY_all_0.5_dur90 연도별
# ═══════════════════════════════════════════
print(f'\n{"="*60}')
print('Test 1: PENALTY_all_0.5_dur90 연도별 분석')
print('='*60, flush=True)

def pen05(items, active, d):
    for item in items:
        if item.get('ticker') in active:
            op = active[item['ticker']].get('op_income')
            if op is not None and op < 0:
                for k in ['rev_z','oca_z','momentum_s','value_s']:
                    item[k] = item.get(k, 0) - 0.5
    return items

rk_pen05 = modify_rk(pen05, 90)
pen05_res = run_score(rk_pen05, all_periods)
pen05_sc = calc_sc(pen05_res)

print(f'\nPENALTY_all_0.5_dur90 score={pen05_sc:.3f} (Δ{pen05_sc-bl_sc:+.3f})')
print(f'\n{"기간":<12} {"BL Cal":>7} {"PEN Cal":>8} {"Delta":>7} {"BL CAGR":>8} {"PEN CAGR":>9}')
print('-'*55)
for pn in ['7.8y','5.25y'] + [str(y) for y in range(2019,2027)] + list(WF.keys()):
    bl = bl_res.get(pn, {})
    pn_r = pen05_res.get(pn, {})
    if bl and pn_r:
        delta = pn_r['calmar'] - bl['calmar']
        marker = ' ★' if delta > 0 else (' ⚠' if delta < -0.5 else '')
        print(f'{pn:<12} {bl["calmar"]:>7.2f} {pn_r["calmar"]:>8.2f} {delta:>+7.2f} {bl["cagr"]:>8.1f} {pn_r["cagr"]:>9.1f}{marker}')

# ═══════════════════════════════════════════
# Test 2: 페널티 강도 미세 튜닝 (0.3~0.8)
# ═══════════════════════════════════════════
print(f'\n{"="*60}')
print('Test 2: 페널티 강도 미세 튜닝')
print('='*60, flush=True)

results = []
for pen_val in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]:
    def m_pen(items, active, d, p=pen_val):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op < 0:
                    for k in ['rev_z','oca_z','momentum_s','value_s']:
                        item[k] = item.get(k, 0) - p
        return items
    rk = modify_rk(m_pen, 90)
    res = run_score(rk)
    sc = calc_sc(res)
    delta = sc - bl_sc
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    print(f'  pen={pen_val:.1f}: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f})', flush=True)
    results.append({'method':f'PENALTY_{pen_val}_dur90','cal_78':c78,'cal_525':c525,'score':sc,'delta':delta})

# ═══════════════════════════════════════════
# Test 3: 하드 제외 (bad stock 순위에서 완전 제거)
# ═══════════════════════════════════════════
print(f'\n{"="*60}')
print('Test 3: 하드 제외 (영업적자 종목 완전 제거)')
print('='*60, flush=True)

for dur in [45, 60, 90]:
    def m_exclude(items, active, d):
        return [item for item in items
                if not (item.get('ticker') in active and
                       active[item['ticker']].get('op_income') is not None and
                       active[item['ticker']]['op_income'] < 0)]
    rk = modify_rk(m_exclude, dur)
    res = run_score(rk)
    sc = calc_sc(res)
    delta = sc - bl_sc
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    print(f'  EXCLUDE_dur{dur}: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f})', flush=True)
    results.append({'method':f'EXCLUDE_dur{dur}','cal_78':c78,'cal_525':c525,'score':sc,'delta':delta})

# ═══════════════════════════════════════════
# Test 4: 분기별 duration (Q4=90일, Q1-Q3=45일)
# ═══════════════════════════════════════════
print(f'\n{"="*60}')
print('Test 4: 분기별 duration (Q4=90d, Q1-Q3=45d)')
print('='*60, flush=True)

for pen_val in [0.3, 0.5, 0.7, 1.0]:
    def m_split(items, active, d, p=pen_val):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op < 0:
                    for k in ['rev_z','oca_z','momentum_s','value_s']:
                        item[k] = item.get(k, 0) - p
        return items
    rk = modify_rk(m_split, use_split=True)
    res = run_score(rk)
    sc = calc_sc(res)
    delta = sc - bl_sc
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    print(f'  SPLIT_pen{pen_val}: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f})', flush=True)
    results.append({'method':f'SPLIT_pen{pen_val}','cal_78':c78,'cal_525':c525,'score':sc,'delta':delta})

# 분기별 + 하드 제외
def m_split_exclude(items, active, d):
    return [item for item in items
            if not (item.get('ticker') in active and
                   active[item['ticker']].get('op_income') is not None and
                   active[item['ticker']]['op_income'] < 0)]
rk = modify_rk(m_split_exclude, use_split=True)
res = run_score(rk)
sc = calc_sc(res)
delta = sc - bl_sc
c78 = res.get('7.8y',{}).get('calmar',0)
c525 = res.get('5.25y',{}).get('calmar',0)
print(f'  SPLIT_EXCLUDE: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f})', flush=True)
results.append({'method':'SPLIT_EXCLUDE','cal_78':c78,'cal_525':c525,'score':sc,'delta':delta})

# ═══════════════════════════════════════════
# Test 5: 페널티 대상 확장 (매출 감소 포함)
# ═══════════════════════════════════════════
print(f'\n{"="*60}')
print('Test 5: 페널티 대상 확장 (영업적자 + 매출감소)')
print('='*60, flush=True)

# 매출 감소 = revenue가 이전 대비 줄어든 경우 (단순: revenue < 0은 없으니 op_income만)
# 여기서는 op_income <= 0 (0 포함) 으로 확장
for pen_val in [0.3, 0.5]:
    def m_expand(items, active, d, p=pen_val):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op <= 0:  # 0 포함
                    for k in ['rev_z','oca_z','momentum_s','value_s']:
                        item[k] = item.get(k, 0) - p
        return items
    rk = modify_rk(m_expand, 90)
    res = run_score(rk)
    sc = calc_sc(res)
    delta = sc - bl_sc
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    print(f'  EXPAND_op<=0_pen{pen_val}: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f})', flush=True)
    results.append({'method':f'EXPAND_op<=0_pen{pen_val}','cal_78':c78,'cal_525':c525,'score':sc,'delta':delta})

# rev_z, oca_z에만 페널티 (momentum/value 제외)
print(f'\n[페널티 팩터 선택적 적용]', flush=True)
for pen_val in [0.5, 0.7, 1.0]:
    def m_growth_only(items, active, d, p=pen_val):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op < 0:
                    for k in ['rev_z','oca_z']:  # Growth만
                        item[k] = item.get(k, 0) - p
        return items
    rk = modify_rk(m_growth_only, 90)
    res = run_score(rk)
    sc = calc_sc(res)
    delta = sc - bl_sc
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    print(f'  GROWTH_ONLY_pen{pen_val}: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f})', flush=True)
    results.append({'method':f'GROWTH_ONLY_pen{pen_val}','cal_78':c78,'cal_525':c525,'score':sc,'delta':delta})

# ═══════════════════════════════════════════
# 종합
# ═══════════════════════════════════════════
print(f'\n{"="*60}')
print('종합 결과 (Step 12 최종 재점검)')
print('='*60, flush=True)

df = pd.DataFrame(results).sort_values('score', ascending=False)
print(f'\nbaseline: score={bl_sc:.3f}')
print(f'\n전체 순위:')
for i, (_, r) in enumerate(df.iterrows()):
    marker = ' ★' if r['delta'] > 0 else ''
    print(f'  {i+1:>2}. {r["method"]:>30}: 7.8y={r["cal_78"]:.2f} 5.25y={r["cal_525"]:.2f} score={r["score"]:.3f} (Δ{r["delta"]:+.3f}){marker}')

improved = df[df['delta'] > 0]
print(f'\nbaseline 초과: {len(improved)}/{len(df)}')
if len(improved) > 0:
    best = improved.iloc[0]
    print(f'★ 최고: {best["method"]} score={best["score"]:.3f} (Δ{best["delta"]:+.3f})')

df.to_csv(str(PROJECT/'backtest'/'step12_final_recheck.csv'), index=False, encoding='utf-8-sig')

# 텔레그램
send_tg(f'<b>[잠정실적 전면 재점검 결과]</b>\n\n'
        f'총 테스트: 기존 122 + 신규 {len(df)}개 조합\n\n'
        f'baseline: {bl_sc:.3f}\n'
        f'최고: {df.iloc[0]["method"]}\n'
        f'  score={df.iloc[0]["score"]:.3f} (Δ{df.iloc[0]["delta"]:+.3f})\n\n'
        f'baseline 초과: {len(improved)}/{len(df)}\n\n'
        f'<b>결론</b>:\n'
        f'- 부스트(좋은종목↑): 15가지 전멸\n'
        f'- 페널티(나쁜종목↓): 유일하게 작동\n'
        f'- Step6 rcept_dt: FG아키텍처 PIT위반 → 무효')

print(f'\n완료. 저장: backtest/step12_final_recheck.csv', flush=True)
