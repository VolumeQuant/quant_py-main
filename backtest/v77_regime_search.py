"""v77 국면서치 — 공격Top × 방어Top × 46+규칙

Phase 2a 인사이트 기반:
- 공격: 3팩터 위주 + 2팩터 대표 (패턴 다양성)
- 방어: M60형 + V40G40형 + raccel형 (다른 철학 혼합)
- 46+ 국면 규칙 넓게 서치
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
t0 = time.time()

ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:,0].dropna()

dates = sorted([f.stem.replace('ranking_','') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)
print(f'init: {time.time()-t0:.0f}s', flush=True)

# ── 공격 후보 (Phase 2a Top + 패턴 다양성) ──
attack_configs = [
    # (label, v,q,g,m, g_rev, gs1,gs2,gs3,gw1,gw2,gw3, e,x,s, mom)
    ('A1_3f_rgp_G60M40', 0,0,60,40, 0.0, 'rev_z','gp_growth_z','op_margin_z',0.5,0.3,0.2, 7,10,3, '12m-1m'),
    ('A2_3f_rog_G65M30', 5,0,65,30, 0.0, 'rev_z','oca_z','gp_growth_z',0.5,0.3,0.2, 7,8,3, '12m-1m'),
    ('A3_3f_rog_G60M25', 15,0,60,25, 0.0, 'rev_z','oca_z','gp_growth_z',0.5,0.3,0.2, 5,10,3, '12m-1m'),
    ('A4_3f_roo_G60M30', 10,0,60,30, 0.0, 'rev_z','oca_z','op_margin_z',0.5,0.3,0.2, 7,8,3, '12m-1m'),
    ('A5_3f_rog_G70M25', 0,5,70,25, 0.0, 'rev_z','oca_z','gp_growth_z',0.5,0.3,0.2, 5,6,3, '12m-1m'),
    ('A6_2f_oca_G60M25', 15,0,60,25, 1.0, 'oca_z','oca_z',None,None,None,None, 7,10,3, '12m-1m'),
    ('A7_2f_roc_G55M25', 15,5,55,25, 0.6, 'rev_z','oca_z',None,None,None,None, 5,6,3, '12m-1m'),
]

# ── 방어 후보 (Phase 2a Top + 패턴 다양성) ──
defense_configs = [
    ('D1_3f_rog_M60S7', 10,0,30,60, 0.0, 'rev_z','oca_z','gp_growth_z',0.5,0.3,0.2, 5,6,7, '6m-1m'),
    ('D2_2f_oar_V40G40', 40,5,40,15, 0.5, 'oca_z','rev_accel_z',None,None,None,None, 7,10,5, '6m-1m'),
    ('D3_3f_roo_M60S7', 10,5,25,60, 0.0, 'rev_z','oca_z','op_margin_z',0.5,0.3,0.2, 5,8,7, '6m-1m'),
    ('D4_3f_rog_M60S5', 10,0,30,60, 0.0, 'rev_z','oca_z','gp_growth_z',0.5,0.3,0.2, 5,6,5, '6m-1m'),
    ('D5_2f_rao_M55', 30,5,10,55, 0.5, 'rev_accel_z','op_margin_z',None,None,None,None, 3,6,7, '6m-1m'),
    ('D6_2f_rvo_M60', 5,5,30,60, 0.7, 'rev_z','op_margin_z',None,None,None,None, 5,6,7, '6m-1m'),
    ('D7_3f_rog_E7S7', 10,5,25,60, 0.0, 'rev_z','oca_z','gp_growth_z',0.5,0.3,0.2, 7,8,7, '6m-1m'),
]

# ── 국면 규칙 빌드 ──
kospi_ma = {n: kospi.rolling(n).mean() for n in [60, 120, 150, 200, 250]}

mc = pd.read_parquet(sorted(DATA_DIR.glob('market_cap_ALL_*.parquet'))[-1])
big = set(mc[mc['시가총액'] >= 1e11].index)
cols = [c for c in ohlcv.columns if c in big]
br = (ohlcv[cols] > ohlcv[cols].rolling(120).mean()).sum(axis=1) / ohlcv[cols].notna().sum(axis=1)

kosdaq_f = DATA_DIR / 'kosdaq_yf.parquet'
kosdaq = pd.read_parquet(kosdaq_f).iloc[:,0].dropna() if kosdaq_f.exists() else None
kosdaq_ma = {}
if kosdaq is not None:
    for n in [60, 120]: kosdaq_ma[n] = kosdaq.rolling(n).mean()

def build_regime(rule_fn, confirm):
    md=False;stk=0;prev_s=False;result={}
    for d in dates:
        ts=pd.Timestamp(d)
        try: s=rule_fn(ts)
        except: s=md
        if s==prev_s:stk+=1
        else:stk=1;prev_s=s
        if stk>=confirm and md!=s:md=s
        result[d]=md
    return result

regime_rules = {}
for thresh in [0.30, 0.35, 0.40, 0.45, 0.50]:
    for confirm in [2, 3, 4, 5]:
        regime_rules[f'B126_{int(thresh*100)}_{confirm}d'] = build_regime(
            lambda ts, t=thresh: br.get(ts, 0.5) >= t, confirm)

for ma_n in [60, 120, 150, 200, 250]:
    ma = kospi_ma[ma_n]
    for confirm in [2, 3, 4, 5]:
        regime_rules[f'KP_MA{ma_n}_{confirm}d'] = build_regime(
            lambda ts, m=ma: kospi.get(ts,0) > m.get(ts,0) if ts in kospi.index else True, confirm)

if kosdaq is not None:
    for ma_n in [60, 120]:
        kp_ma, kd_ma = kospi_ma[ma_n], kosdaq_ma[ma_n]
        for confirm in [3, 4, 5]:
            regime_rules[f'KK_MA{ma_n}_{confirm}d'] = build_regime(
                lambda ts, km=kp_ma, dm=kd_ma: (kospi.get(ts,0)>km.get(ts,0) and kosdaq.get(ts,0)>dm.get(ts,0)) if ts in kospi.index else True, confirm)

total = len(attack_configs) * len(defense_configs) * len(regime_rules)
print(f'{len(attack_configs)}공격 × {len(defense_configs)}방어 × {len(regime_rules)}규칙 = {total}건', flush=True)

# ── 서치 ──
results = []
count = 0
t1 = time.time()

# 캐시: 공격/방어 flat 미리 빌드 (49쌍만 빌드, 규칙은 재사용)
from turbo_simulator import _run_regime_inner

atk_flats = {}  # al → flat array
for al, av,aq,ag,am, a_grev, a_gs1,a_gs2,a_gs3,a_gw1,a_gw2,a_gw3, ae,ax,a_s, a_mom in attack_configs:
    tsim._ensure_cache(av/100,aq/100,ag/100,am/100, a_grev, 20, a_mom, a_gs1, a_gs2, a_gs3, a_gw1, a_gw2, a_gw3)
    atk_flats[al] = (list(tsim._cached_flat), ae, ax, a_s)
print(f'공격 {len(atk_flats)}개 캐시 빌드 완료', flush=True)

def_flats = {}  # dl → flat array
for dl, dv,dq,dg,dm, d_grev, d_gs1,d_gs2,d_gs3,d_gw1,d_gw2,d_gw3, de,dx,d_s, d_mom in defense_configs:
    tsim._ensure_cache(dv/100,dq/100,dg/100,dm/100, d_grev, 20, d_mom, d_gs1, d_gs2, d_gs3, d_gw1, d_gw2, d_gw3)
    def_flats[dl] = (list(tsim._cached_flat), de, dx, d_s)
print(f'방어 {len(def_flats)}개 캐시 빌드 완료 ({time.time()-t0:.0f}s)', flush=True)

# 국면 규칙별 전환/공격 비율 사전계산
rule_stats = {}
for rule_name, rd in regime_rules.items():
    sw = sum(1 for i in range(1,len(dates)) if rd[dates[i]] != rd[dates[i-1]])
    boost_pct = sum(1 for v in rd.values() if v) / len(rd) * 100
    rule_stats[rule_name] = (sw, boost_pct)

# 서치: flat 재사용, _run_regime_inner 직접 호출
for al in atk_flats:
    o_flat, oe, ox, o_s = atk_flats[al]
    for dl in def_flats:
        d_flat, de, dx, d_s = def_flats[dl]
        for rule_name, rd in regime_rules.items():
            r = _run_regime_inner(
                d_flat, o_flat, de, dx, d_s, oe, ox, o_s,
                rd, dates,
                tsim._price_arr, tsim._bench_arr, tsim._has_bench,
                tsim._date_row_indices, len(dates),
                -0.10, None, None, -0.15)
            sw, boost_pct = rule_stats[rule_name]
            results.append({
                'atk': al, 'def': dl, 'rule': rule_name,
                'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                'sw': sw, 'boost': boost_pct,
            })
            count += 1
    print(f'  {al} 완료 ({count}/{total}, {time.time()-t1:.0f}s)', flush=True)

df = pd.DataFrame(results).sort_values('cal', ascending=False)
df.to_csv(RESULT_DIR / 'v77_regime_search.csv', index=False)

print(f'\n{"="*80}', flush=True)
print(f'국면서치 결과 ({len(results)}건, {(time.time()-t0)/60:.0f}분)', flush=True)
print(f'{"="*80}', flush=True)

print(f'\nTop 15:', flush=True)
print(f'{"atk":<22} {"def":<22} {"rule":<18} {"Cal":>5} {"CAGR":>7} {"MDD":>5} {"Sh":>5} {"So":>5} {"sw":>3} {"B%":>4}', flush=True)
print('-'*100, flush=True)
for _, r in df.head(15).iterrows():
    print(f'{r["atk"]:<22} {r["def"]:<22} {r["rule"]:<18} {r["cal"]:>5.2f} {r["cagr"]:>+6.1f}% {r["mdd"]:>4.1f}% {r["sh"]:>5.2f} {r["sort"]:>5.2f} {r["sw"]:>3} {r["boost"]:>3.0f}%', flush=True)

print(f'\n규칙별 Top1:', flush=True)
for rule in df.groupby('rule')['cal'].max().sort_values(ascending=False).head(10).index:
    row = df[df['rule']==rule].sort_values('cal', ascending=False).iloc[0]
    print(f'  {rule:<18} Cal={row["cal"]:.2f} CAGR={row["cagr"]:+.1f}% sw={row["sw"]}', flush=True)

print(f'\n소요: {(time.time()-t0)/60:.1f}분', flush=True)

# 텔레그램
try:
    import requests
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
    top = df.iloc[0]
    msg = f'[v77 국면서치 완료]\n{total}건, {(time.time()-t0)/60:.0f}분\n\n'
    msg += f'1위: {top["rule"]}\n  공격: {top["atk"]}\n  방어: {top["def"]}\n'
    msg += f'  Cal={top["cal"]:.2f} CAGR={top["cagr"]:+.1f}% MDD={top["mdd"]:.1f}%\n\n'
    msg += '규칙별 Top3:\n'
    for rule in df.groupby('rule')['cal'].max().sort_values(ascending=False).head(3).index:
        row = df[df['rule']==rule].sort_values('cal', ascending=False).iloc[0]
        msg += f'  {rule}: Cal={row["cal"]:.2f}\n'
    requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                  data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=30)
except: pass
