"""잠정실적 극단 서프라이즈 전용 테스트

핵심 인사이트: 브이엠은 rank 4인데 진입은 rank 3.
잠정 +1500% 같은 극단 서프라이즈만 부스트하면
소수 종목만 영향 → 노이즈 최소화 + 핵심 종목 진입 가능.

방법 N: 극단 서프라이즈만 부스트 (영업이익 적자→흑자, 또는 >100%)
방법 O: 극단 + 나쁜 종목 페널티 (L+N 결합)
방법 P: 서프라이즈 크기에 비례 (선형 부스트)
방법 Q: Top 20 내 종목만 부스트 (핵심 종목 포커스)
방법 R: 모멘텀 팩터에만 극단 부스트
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

# 잠정실적 (영업이익 크기 포함)
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

def get_active(date_str, dur=45):
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
V80_O = {'v':0.15,'q':0.00,'g':0.55,'m':0.30,'g_rev':0.6,'entry':3,'exit':6,'slots':3,'mom':'12m'}
V80_D = {'v':0.30,'q':0.15,'g':0.15,'m':0.40,'g_rev':0.7,'entry':3,'exit':6,'slots':5,'mom':'6m-1m'}
GS = ('rev_z','oca_z',None,None,None,None)

def run_score(rk_data):
    res = {}
    for pn in ['7.8y','5.25y']:
        ps, pe = PERIODS[pn]
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

def modify_rk(method_fn, dur=45):
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
    marker = ' ★★★' if delta > 0.1 else (' ★' if delta > 0 else '')
    print(f'  {name:>50}: 7.8y={c78:.2f} 5.25y={c525:.2f} score={sc:.3f} (Δ{delta:+.3f}){marker}', flush=True)
    results.append({'method':name,'cal_78':c78,'cal_525':c525,'score':sc,'delta':delta})
    return sc

bl_res = run_score(base_rk)
bl_sc = calc_sc(bl_res)
print(f'baseline: score={bl_sc:.3f}\n', flush=True)
results = []


# ════════════════════════════════════════
# 방법 N: 극단 서프라이즈만 부스트
# ════════════════════════════════════════
print('='*60)
print('방법 N: 극단 서프라이즈만 부스트 (상위 극소수)')
print('='*60, flush=True)

for threshold_ratio in [2.0, 5.0, 10.0]:  # 영업이익이 매출의 X% 이상
    for bs in [0.5, 1.0, 1.5]:
        def method_n(items, active, d, tr=threshold_ratio, boost=bs):
            for item in items:
                tk = item.get('ticker')
                if tk in active:
                    op = active[tk].get('op_income')
                    rev = active[tk].get('revenue')
                    if op is not None and rev is not None and rev > 0:
                        opm = op / rev  # 영업이익률
                        if opm > tr / 100:  # 극단 고마진
                            item['rev_z'] = item.get('rev_z', 0) + boost
                            item['momentum_s'] = item.get('momentum_s', 0) + boost * 0.5
            return items
        rk = modify_rk(method_n)
        test(f'N_extreme_opm>{threshold_ratio}%_bs{bs}', rk)


# ════════════════════════════════════════
# 방법 O: 극단 부스트 + L(나쁜 페널티) 결합
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 O: 극단 부스트 + 나쁜 페널티 결합')
print('='*60, flush=True)

for good_bs in [0.3, 0.5, 1.0]:
    def method_o(items, active, d, gbs=good_bs):
        for item in items:
            tk = item.get('ticker')
            if tk in active:
                op = active[tk].get('op_income')
                rev = active[tk].get('revenue')
                if op is not None and op < 0:
                    # 나쁜 종목 페널티 (L 방식)
                    item['rev_z'] = item.get('rev_z', 0) - 0.5
                    item['oca_z'] = item.get('oca_z', 0) - 0.5
                    item['momentum_s'] = item.get('momentum_s', 0) - 0.5
                    item['value_s'] = item.get('value_s', 0) - 0.5
                elif op is not None and rev is not None and rev > 0:
                    opm = op / rev
                    if opm > 0.15:  # 영업이익률 15% 이상 = 극단 양호
                        item['rev_z'] = item.get('rev_z', 0) + gbs
                        item['momentum_s'] = item.get('momentum_s', 0) + gbs * 0.3
        return items
    rk = modify_rk(method_o)
    test(f'O_extreme+Lpen_gbs{good_bs}', rk)


# ════════════════════════════════════════
# 방법 P: 서프라이즈 크기에 비례 부스트
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 P: 서프라이즈 크기 비례 (연속 스케일링)')
print('='*60, flush=True)

for scale in [0.01, 0.02, 0.05]:
    def method_p(items, active, d, sc=scale):
        for item in items:
            tk = item.get('ticker')
            if tk in active:
                op = active[tk].get('op_income')
                rev = active[tk].get('revenue')
                if op is not None and rev is not None and rev > 0:
                    opm = op / rev
                    # 영업이익률에 비례 (클수록 큰 부스트, 음수면 페널티)
                    boost = opm * sc * 100  # OPM 10% → 0.1 * sc * 100
                    boost = max(-2.0, min(2.0, boost))  # 클램프
                    item['rev_z'] = item.get('rev_z', 0) + boost
                    item['oca_z'] = item.get('oca_z', 0) + boost * 0.5
        return items
    rk = modify_rk(method_p)
    test(f'P_proportional_sc{scale}', rk)


# ════════════════════════════════════════
# 방법 Q: Top 20 내 종목만 부스트
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 Q: Top 20 내 잠정 양호 종목만 부스트')
print('='*60, flush=True)

for bs in [0.3, 0.5, 1.0, 1.5]:
    def method_q(items, active, d, boost=bs):
        # Top 20 종목만 (rank 기준)
        for item in items[:20]:
            tk = item.get('ticker')
            if tk in active:
                op = active[tk].get('op_income')
                if op is not None and op > 0:
                    item['rev_z'] = item.get('rev_z', 0) + boost
                    item['momentum_s'] = item.get('momentum_s', 0) + boost * 0.3
        return items
    rk = modify_rk(method_q)
    test(f'Q_top20only_bs{bs}', rk)


# ════════════════════════════════════════
# 방법 R: 모멘텀에만 극단 부스트 + L 페널티
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('방법 R: 모멘텀만 극단 부스트 + L 페널티')
print('='*60, flush=True)

for mom_bs in [0.5, 1.0, 1.5, 2.0]:
    def method_r(items, active, d, mbs=mom_bs):
        for item in items:
            tk = item.get('ticker')
            if tk in active:
                op = active[tk].get('op_income')
                rev = active[tk].get('revenue')
                if op is not None and op < 0:
                    # 나쁜 종목 페널티
                    for key in ['rev_z','oca_z','momentum_s','value_s']:
                        item[key] = item.get(key, 0) - 0.5
                elif op is not None and rev is not None and rev > 0:
                    opm = op / rev
                    if opm > 0.10:  # OPM 10%+
                        item['momentum_s'] = item.get('momentum_s', 0) + mbs
        return items
    rk = modify_rk(method_r)
    test(f'R_momboost{mom_bs}+Lpen', rk)


# ════════════════════════════════════════
# 종합
# ════════════════════════════════════════
print(f'\n{"="*60}')
print('종합 결과')
print('='*60, flush=True)

df = pd.DataFrame(results).sort_values('score', ascending=False)
print(f'\nbaseline: score={bl_sc:.3f}')
print(f'\nTop 10:')
for i, (_, r) in enumerate(df.head(10).iterrows()):
    marker = ' ★' if r['delta'] > 0 else ''
    print(f'  {i+1:>2}. {r["method"]:>50}: score={r["score"]:.3f} (Δ{r["delta"]:+.3f}){marker}')

improved = df[df['delta'] > 0]
print(f'\nbaseline 초과: {len(improved)}/{len(df)}')

df.to_csv(str(PROJECT/'backtest'/'step11_extreme_surprise.csv'), index=False, encoding='utf-8-sig')

# 텔레그램
best = df.iloc[0]
send_tg(f'<b>[잠정실적 극단 서프라이즈 5가지 추가 테스트]</b>\n\n'
        f'baseline: {bl_sc:.3f}\n'
        f'최고: {best["method"]}\n'
        f'score={best["score"]:.3f} (Δ{best["delta"]:+.3f})\n'
        f'baseline 초과: {len(improved)}/{len(df)}')
