"""잠정실적 활용 — 10가지 방법 체계적 테스트

TurboSimulator는 z-score(rev_z, oca_z, momentum_s 등)에서 점수를 재계산.
→ weighted_rank 수정은 무시됨
→ z-score를 직접 수정하거나, 팩터 점수를 조정해야 함.

방법 목록:
  B: 모멘텀 z-score 보너스 (잠정 좋으면 momentum_s 부스트)
  D: 별도 서프라이즈 팩터 (growth_s에 서프라이즈 블렌드)
  F: 지연 일괄 반영 (60%+ 공시 후 rcept_dt 수정)
  G: 방어 전용 (잠정 나쁜 종목 value_s 페널티)
  H: 모멘텀 확인 (잠정 좋은 종목만 momentum_s 유지, 나쁘면 감소)
  I: Growth 직접 부스트 (잠정 좋으면 rev_z 직접 증가)
  J: 엔트리 필터 (잠정 나쁜 종목 entry_rank 축소)
  K: 섹터 내 상대 서프라이즈
  L: 모멘텀 타입 전환 (잠정 시즌에만 6m→12m)
  M: 복합 (B+G 조합)
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
from config import TELEGRAM_BOT_TOKEN as BOT_TOKEN, TELEGRAM_PRIVATE_ID as PRIVATE_ID
def send_tg(msg):
    try: requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                       data={'chat_id': PRIVATE_ID, 'text': msg, 'parse_mode': 'HTML'}, timeout=30)
    except: pass

# ── 데이터 로드 ──
print('데이터 로드...', flush=True)
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

boost = load_rankings([PROJECT/'backtest'/'bt_extended', PROJECT/'state'])
defense = load_rankings([PROJECT/'backtest'/'bt_extended_defense', PROJECT/'state'/'defense'])
dates = sorted(set(boost) & set(defense))
base_rk = {d: boost[d]['rankings'] for d in dates}

ohlcv = pd.read_parquet(sorted((PROJECT/'data_cache').glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kospi = kospi_df.iloc[:, 0].fillna(kospi_df['kospi']).sort_index()
ma170 = kospi.rolling(170).mean()

# 잠정실적
prov_df = pd.read_parquet(PROJECT/'data_cache'/'provisional_earnings.parquet')
prov_df['rcept_dt'] = pd.to_datetime(prov_df['rcept_dt'])

# 잠정 이벤트: date_str → {ticker: {revenue, op_income}}
prov_by_date = {}
for _, row in prov_df.iterrows():
    d = row['rcept_dt'].strftime('%Y%m%d')
    if d not in prov_by_date:
        prov_by_date[d] = {}
    prov_by_date[d][row['ticker']] = {
        'revenue': row.get('revenue'),
        'op_income': row.get('operating_income'),
    }

# 활성 잠정 추적 함수
def get_active_provisional(date_str, duration_days=45):
    """date_str 시점에서 최근 duration_days 내 잠정 공시된 종목 반환"""
    ts = pd.Timestamp(date_str)
    active = {}
    for d, tickers in prov_by_date.items():
        d_ts = pd.Timestamp(d)
        if d_ts <= ts and (ts - d_ts).days <= duration_days:
            for tk, data in tickers.items():
                active[tk] = data
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
    for pname in periods:
        ps, pe = {**PERIODS, **WF}[pname]
        pd_ = [d for d in dates if ps <= d <= pe and d in rk_data]
        if len(pd_) < 20: continue
        tsim = TurboSimulator({d: rk_data[d] for d in pd_}, pd_, ohlcv)
        reg = calc_regime(pd_)
        r = tsim.run_regime(defense_params=V80_D, offense_params=V80_O,
            regime_dict=reg, trailing_stop=-0.15,
            g_sub1_o=GS[0],g_sub2_o=GS[1],g_sub3_o=GS[2],
            g_w1_o=GS[3],g_w2_o=GS[4],g_w3_o=GS[5],
            g_sub1_d=GS[0],g_sub2_d=GS[1],g_sub3_d=GS[2],
            g_w1_d=GS[3],g_w2_d=GS[4],g_w3_d=GS[5])
        res[pname] = r
    return res

def calc_geo_score(res):
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    return (c78*c525)**0.5 if c78>0 and c525>0 else 0

# ── Baseline ──
print('baseline 계산...', flush=True)
bl_res = run_score(base_rk, list(PERIODS.keys()) + list(WF.keys()))
bl_sc = calc_geo_score(bl_res)
print(f'baseline: 7.8y={bl_res["7.8y"]["calmar"]:.2f} 5.25y={bl_res["5.25y"]["calmar"]:.2f} score={bl_sc:.3f}\n', flush=True)

results_all = []

def modify_rankings(method_fn, duration=45):
    """method_fn(items, active_prov) → modified items"""
    new_rk = {}
    for d in dates:
        active = get_active_provisional(d, duration)
        items = deepcopy(base_rk[d])
        items = method_fn(items, active, d)
        new_rk[d] = items
    return new_rk

def test_method(name, rk_data):
    """테스트 실행 + 결과 기록"""
    res = run_score(rk_data)
    sc = calc_geo_score(res)
    delta = sc - bl_sc
    c78 = res.get('7.8y',{}).get('calmar',0)
    c525 = res.get('5.25y',{}).get('calmar',0)
    marker = ' ★★★' if delta > 0.2 else (' ★' if delta > 0 else '')
    print(f'  {name:>40}: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f}){marker}', flush=True)
    results_all.append({'method': name, 'cal_78': c78, 'cal_525': c525, 'score': sc, 'delta': delta})
    return sc, delta


# ════════════════════════════════════════
# 방법 B: 모멘텀 z-score 부스트
# ════════════════════════════════════════
print('='*60)
print('방법 B: 모멘텀 z-score 부스트')
print('='*60, flush=True)

for boost_size in [0.3, 0.5, 0.7, 1.0]:
    for dur in [30, 45]:
        def method_b(items, active, d, bs=boost_size):
            for item in items:
                if item.get('ticker') in active:
                    op = active[item['ticker']].get('op_income')
                    if op is not None and op > 0:
                        item['momentum_s'] = item.get('momentum_s', 0) + bs
                    elif op is not None and op < 0:
                        item['momentum_s'] = item.get('momentum_s', 0) - bs * 0.5
            return items
        rk = modify_rankings(method_b, dur)
        test_method(f'B_mom+{boost_size}_dur{dur}', rk)


# ════════════════════════════════════════
# 방법 D: Growth에 서프라이즈 블렌드
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 D: Growth에 서프라이즈 블렌드')
print('='*60, flush=True)

for boost_size in [0.3, 0.5, 1.0]:
    for dur in [30, 45]:
        def method_d(items, active, d, bs=boost_size):
            for item in items:
                if item.get('ticker') in active:
                    op = active[item['ticker']].get('op_income')
                    if op is not None and op > 0:
                        item['rev_z'] = item.get('rev_z', 0) + bs
                        item['oca_z'] = item.get('oca_z', 0) + bs * 0.5
                    elif op is not None and op < 0:
                        item['rev_z'] = item.get('rev_z', 0) - bs
                        item['oca_z'] = item.get('oca_z', 0) - bs * 0.5
            return items
        rk = modify_rankings(method_d, dur)
        test_method(f'D_growth+{boost_size}_dur{dur}', rk)


# ════════════════════════════════════════
# 방법 G: 방어 전용 (나쁜 종목만 페널티)
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 G: 방어 전용 (나쁜 종목만 페널티)')
print('='*60, flush=True)

for penalty in [0.5, 1.0, 1.5, 2.0]:
    for dur in [30, 45]:
        def method_g(items, active, d, pen=penalty):
            for item in items:
                if item.get('ticker') in active:
                    op = active[item['ticker']].get('op_income')
                    if op is not None and op < 0:
                        item['rev_z'] = item.get('rev_z', 0) - pen
                        item['oca_z'] = item.get('oca_z', 0) - pen
                        item['momentum_s'] = item.get('momentum_s', 0) - pen * 0.5
            return items
        rk = modify_rankings(method_g, dur)
        test_method(f'G_defonly_pen{penalty}_dur{dur}', rk)


# ════════════════════════════════════════
# 방법 H: 잠정 좋은 종목만 모멘텀 유지, 나쁘면 감소
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 H: 잠정 확인 (나쁘면 모멘텀 감소)')
print('='*60, flush=True)

for reduce in [0.3, 0.5, 0.7, 1.0]:
    def method_h(items, active, d, red=reduce):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op < 0:
                    item['momentum_s'] = item.get('momentum_s', 0) * (1.0 - red)
            return items
    rk = modify_rankings(method_h, 45)
    test_method(f'H_momreduce_{reduce}', rk)


# ════════════════════════════════════════
# 방법 I: rev_z 직접 부스트 (비대칭: 좋은 종목만)
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 I: rev_z 비대칭 부스트 (좋은 종목만)')
print('='*60, flush=True)

for boost_size in [0.3, 0.5, 0.7, 1.0, 1.5]:
    def method_i(items, active, d, bs=boost_size):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op > 0:
                    item['rev_z'] = item.get('rev_z', 0) + bs
        return items
    rk = modify_rankings(method_i, 45)
    test_method(f'I_rev_boost_{boost_size}', rk)


# ════════════════════════════════════════
# 방법 J: value_s 부스트 (잠정 좋으면 밸류 매력도 상승)
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 J: value_s 부스트')
print('='*60, flush=True)

for boost_size in [0.5, 1.0, 1.5]:
    def method_j(items, active, d, bs=boost_size):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op > 0:
                    item['value_s'] = item.get('value_s', 0) + bs
                elif op is not None and op < 0:
                    item['value_s'] = item.get('value_s', 0) - bs
        return items
    rk = modify_rankings(method_j, 45)
    test_method(f'J_value_{boost_size}', rk)


# ════════════════════════════════════════
# 방법 K: 전팩터 동시 부스트 (소량씩)
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 K: 전팩터 소량 동시 부스트')
print('='*60, flush=True)

for boost_size in [0.2, 0.3, 0.5]:
    def method_k(items, active, d, bs=boost_size):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op > 0:
                    item['rev_z'] = item.get('rev_z', 0) + bs
                    item['oca_z'] = item.get('oca_z', 0) + bs
                    item['momentum_s'] = item.get('momentum_s', 0) + bs
                    item['value_s'] = item.get('value_s', 0) + bs
        return items
    rk = modify_rankings(method_k, 45)
    test_method(f'K_allfactor_{boost_size}', rk)


# ════════════════════════════════════════
# 방법 L: 잠정 나쁜 종목 전팩터 페널티 (리스크 관리)
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 L: 나쁜 종목 전팩터 페널티')
print('='*60, flush=True)

for penalty in [0.3, 0.5, 1.0, 1.5]:
    def method_l(items, active, d, pen=penalty):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op < 0:
                    item['rev_z'] = item.get('rev_z', 0) - pen
                    item['oca_z'] = item.get('oca_z', 0) - pen
                    item['momentum_s'] = item.get('momentum_s', 0) - pen
                    item['value_s'] = item.get('value_s', 0) - pen
        return items
    rk = modify_rankings(method_l, 45)
    test_method(f'L_badpenalty_{penalty}', rk)


# ════════════════════════════════════════
# 방법 M: 복합 (좋은 종목 소량 부스트 + 나쁜 종목 큰 페널티)
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 M: 비대칭 복합 (좋은=소량, 나쁜=큰 페널티)')
print('='*60, flush=True)

for good_bs, bad_pen in [(0.2, 1.0), (0.3, 1.5), (0.5, 2.0), (0.3, 1.0), (0.5, 1.0)]:
    def method_m(items, active, d, gbs=good_bs, bp=bad_pen):
        for item in items:
            if item.get('ticker') in active:
                op = active[item['ticker']].get('op_income')
                if op is not None and op > 0:
                    item['rev_z'] = item.get('rev_z', 0) + gbs
                    item['momentum_s'] = item.get('momentum_s', 0) + gbs
                elif op is not None and op < 0:
                    item['rev_z'] = item.get('rev_z', 0) - bp
                    item['oca_z'] = item.get('oca_z', 0) - bp
                    item['momentum_s'] = item.get('momentum_s', 0) - bp
        return items
    rk = modify_rankings(method_m, 45)
    test_method(f'M_asym_g{good_bs}_b{bad_pen}', rk)


# ════════════════════════════════════════
# 종합 결과
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('종합 결과')
print('='*60, flush=True)

df = pd.DataFrame(results_all).sort_values('score', ascending=False)
print(f'\nbaseline: score={bl_sc:.3f}')
print(f'\nTop 10:')
for i, (_, r) in enumerate(df.head(10).iterrows()):
    marker = ' ★' if r['delta'] > 0 else ''
    print(f'  {i+1:>2}. {r["method"]:>40}: score={r["score"]:.3f} (Δ{r["delta"]:+.3f}){marker}')

improved = df[df['delta'] > 0]
print(f'\nbaseline 초과: {len(improved)}/{len(df)}')

if len(improved) > 0:
    best = improved.iloc[0]
    print(f'\n★ 최고: {best["method"]} score={best["score"]:.3f} (Δ{best["delta"]:+.3f})')
    # WF 검증은 최고 방법에서만
else:
    print(f'\n모든 방법이 baseline 이하.')

df.to_csv(str(PROJECT/'backtest'/'step11_all_methods.csv'), index=False, encoding='utf-8-sig')
print(f'\n저장: backtest/step11_all_methods.csv')

# 텔레그램
top3 = df.head(3)
top_str = '\n'.join([f'{r["method"]}: score={r["score"]:.3f} (Δ{r["delta"]:+.3f})'
                     for _, r in top3.iterrows()])
send_tg(f'<b>[잠정실적 10가지 방법 테스트 완료]</b>\n\n'
        f'baseline: score={bl_sc:.3f}\n\n'
        f'<b>Top 3:</b>\n<pre>{top_str}</pre>\n\n'
        f'baseline 초과: {len(improved)}/{len(df)}')
