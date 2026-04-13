"""Phase 2 EDA: v77 성과 분해 + 팩터 분석"""
import json, sys, os, glob, copy
import numpy as np
import pandas as pd
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

STATE_DIR = Path(__file__).parent.parent / 'state'
CACHE_DIR = Path(__file__).parent.parent / 'data_cache'
PENALTY = 50

print('=== Phase 2 EDA: v77 성과 분해 + 팩터 분석 ===\n')

# ─── 데이터 로딩 ───
def load_all_rankings(ranking_dir):
    files = sorted(f for f in ranking_dir.glob('ranking_*.json')
                   if len(f.stem.replace('ranking_',''))==8
                   and 'boost' not in f.stem.replace('ranking_','')
                   and 'core' not in f.stem and 'backup' not in f.stem)
    data = {}
    for fp in files:
        d = fp.stem.replace('ranking_', '')
        with open(fp, 'r', encoding='utf-8') as f:
            data[d] = json.load(f)
    return data

boost_data = load_all_rankings(STATE_DIR)
defense_data = load_all_rankings(STATE_DIR / 'defense')
print(f'Boost: {len(boost_data)}개, Defense: {len(defense_data)}개')

# OHLCV + KOSPI
ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
full_files = [f for f in ohlcv_files if '_full' in f.stem]
if full_files:
    ohlcv_files = full_files
ohlcv = pd.concat([pd.read_parquet(f).replace(0, np.nan) for f in ohlcv_files]).groupby(level=0).first()
kospi = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet').iloc[:,0].dropna()
km200 = kospi.rolling(200).mean()

# ─── 국면 판단 ───
all_dates = sorted(boost_data.keys())
regime_by_date = {}
md = False; stk = 0; ss = False
for d in all_dates:
    ts = pd.Timestamp(d)
    kv = kospi.get(ts); mv = km200.get(ts)
    s = (kv > mv) if kv is not None and mv is not None else md
    if s == ss: stk += 1
    else: stk = 1; ss = s
    if stk >= 5 and md != s: md = s
    regime_by_date[d] = md

boost_days = sum(1 for v in regime_by_date.values() if v)
defense_days = sum(1 for v in regime_by_date.values() if not v)
print(f'국면: 공격 {boost_days}일, 방어 {defense_days}일')

switches = 0; prev = None; switch_dates = []
for d in all_dates:
    if prev is not None and regime_by_date[d] != prev:
        switches += 1
        switch_dates.append((d, '공격' if regime_by_date[d] else '방어'))
    prev = regime_by_date[d]
print(f'전환: {switches}회')
for sd, sm in switch_dates:
    print(f'  {sd} -> {sm}')


# ─── 시뮬레이션 함수 ───
def simulate(boost_data, defense_data, regime_by_date, ohlcv, params_b, params_d):
    all_dates_sorted = sorted(set(boost_data.keys()) & set(defense_data.keys()))

    all_data = {}; dates = []
    for d in all_dates_sorted:
        ib = regime_by_date.get(d, True)
        if ib and d in boost_data:
            all_data[d] = boost_data[d]; dates.append(d)
        elif not ib and d in defense_data:
            all_data[d] = defense_data[d]; dates.append(d)
        elif d in boost_data:
            all_data[d] = boost_data[d]; dates.append(d)

    def gp(tk, ds):
        ts = pd.Timestamp(ds)
        if ts in ohlcv.index and tk in ohlcv.columns:
            v = ohlcv.loc[ts, tk]
            if pd.notna(v) and v > 0: return v
        return 0

    portfolio = {}; peak = {}; equity = 1.0; start = None
    yearly_eq = {}

    for i in range(len(dates)):
        d0 = dates[i]
        if i >= 1 and portfolio:
            dr = []
            for tk in portfolio:
                pp = gp(tk, dates[i-1]); cp = gp(tk, d0)
                if pp > 0 and cp > 0: dr.append(cp/pp - 1)
            if dr: equity *= (1 + sum(dr)/len(dr))
        yearly_eq[d0] = equity

        if i < 2: continue
        d1 = dates[i-1]; d2 = dates[i-2]

        ib = regime_by_date.get(d0, True)
        rp = params_b if ib else params_d
        er = rp['ENTRY_RANK']; xr = rp['EXIT_RANK']; ms = rp['MAX_SLOTS']
        sl = rp.get('STOP_LOSS', -0.10); tr = rp.get('TRAILING_STOP', -0.15)

        if i >= 1:
            pb = regime_by_date.get(dates[i-1], True)
            if ib != pb: portfolio.clear(); peak.clear()

        for tk in list(portfolio.keys()):
            cp = gp(tk, d0); ep = portfolio[tk]
            if tk in peak:
                if cp > peak[tk]: peak[tk] = cp
            else: peak[tk] = max(cp, ep) if cp > 0 else ep
            if cp > 0 and ep > 0 and (cp/ep-1) <= sl:
                del portfolio[tk]; peak.pop(tk, None)
            elif cp > 0 and peak.get(tk,0) > 0 and (cp/peak[tk]-1) <= tr:
                del portfolio[tk]; peak.pop(tk, None)

        r0 = all_data[d0].get('rankings',[]); r1 = all_data[d1].get('rankings',[]); r2 = all_data[d2].get('rankings',[])
        top20_0 = {r['ticker']:r for r in r0 if r.get('composite_rank', r['rank'])<=20}
        top20_1 = {r['ticker']:r for r in r1 if r.get('composite_rank', r['rank'])<=20}
        top20_2 = {r['ticker']:r for r in r2 if r.get('composite_rank', r['rank'])<=20}
        common = set(top20_0) & set(top20_1) & set(top20_2)

        all0 = {r['ticker']:r for r in r0}; all1 = {r['ticker']:r for r in r1}; all2 = {r['ticker']:r for r in r2}
        def wr(tk):
            if tk not in all0: return 999
            c0 = all0[tk].get('composite_rank',999)
            c1 = all1[tk].get('composite_rank',999) if tk in all1 else 999
            c2 = all2[tk].get('composite_rank',999) if tk in all2 else 999
            return c0*0.5+c1*0.3+c2*0.2

        for tk in list(portfolio.keys()):
            if wr(tk) > xr: del portfolio[tk]

        verified = sorted([{'ticker':tk, 'wr':wr(tk)} for tk in common], key=lambda x: x['wr'])

        for v in verified[:er]:
            if v['ticker'] in portfolio: continue
            if len(portfolio) >= ms: break
            ep = gp(v['ticker'], d0)
            if ep > 0:
                portfolio[v['ticker']] = ep; peak[v['ticker']] = ep
                if start is None: start = d0

    yearly = {}
    eq_sorted = sorted(yearly_eq.items())
    for yr in range(2020, 2027):
        yr_s = f'{yr}0101'; yr_e = f'{yr}1231'
        yr_dates = [(d,e) for d,e in eq_sorted if yr_s <= d <= yr_e]
        if len(yr_dates) >= 2:
            yearly[yr] = round((yr_dates[-1][1]/yr_dates[0][1] - 1)*100, 1)

    total = round((equity-1)*100, 1)
    eq_arr = np.array([e for _,e in eq_sorted])
    peaks_arr = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peaks_arr)/peaks_arr
    mdd = round(abs(dd.min())*100, 1)
    days = len(dates)-2
    years = days/252
    cagr = round(((equity)**(1/years)-1)*100, 1) if years > 0 else 0
    calmar = round(cagr/mdd, 2) if mdd > 0 else 0

    return {'yearly': yearly, 'total': total, 'mdd': mdd, 'cagr': cagr, 'calmar': calmar}


# ─── v77 기본 성과 ───
from regime_indicator import get_regime_params
v77_b = get_regime_params('boost')
v77_d = get_regime_params('defense')

print('\n=== v77 연도별 성과 ===')
r = simulate(boost_data, defense_data, regime_by_date, ohlcv, v77_b, v77_d)
print(f'누적: +{r["total"]}%, CAGR: {r["cagr"]}%, MDD: {r["mdd"]}%, Calmar: {r["calmar"]}')
for yr in sorted(r['yearly']):
    print(f'  {yr}: {r["yearly"][yr]:+.1f}%')


# ─── 공격only vs 방어only vs 국면전환 ───
print('\n=== 국면별 기여도 분리 ===')
r_atk = simulate(boost_data, boost_data, {d:True for d in all_dates}, ohlcv, v77_b, v77_b)
r_def = simulate(defense_data, defense_data, {d:False for d in all_dates}, ohlcv, v77_d, v77_d)

print(f'{"":>10} {"공격only":>10} {"방어only":>10} {"국면전환":>10}')
print(f'{"CAGR":>10} {str(r_atk["cagr"])+"%":>10} {str(r_def["cagr"])+"%":>10} {str(r["cagr"])+"%":>10}')
print(f'{"MDD":>10} {str(r_atk["mdd"])+"%":>10} {str(r_def["mdd"])+"%":>10} {str(r["mdd"])+"%":>10}')
print(f'{"Calmar":>10} {str(r_atk["calmar"]):>10} {str(r_def["calmar"]):>10} {str(r["calmar"]):>10}')
print()
for yr in sorted(set(list(r_atk['yearly'].keys()) + list(r_def['yearly'].keys()) + list(r['yearly'].keys()))):
    ya = r_atk['yearly'].get(yr, '-')
    yd = r_def['yearly'].get(yr, '-')
    yn = r['yearly'].get(yr, '-')
    print(f'  {yr}: 공격={ya}% 방어={yd}% 국면전환={yn}%')


# ─── G 서브팩터 비교 (공격모드만, state/ 데이터) ───
print('\n=== G 서브팩터 비교 (공격모드, v77 기본 vs op_margin 교체) ===')

# reranking으로 G_SUB3 변경 테스트
from send_telegram_auto import _rerank_for_regime

# v77 with op_margin (G_SUB3만 변경)
v77_b_opm = copy.deepcopy(v77_b)
v77_b_opm['G_SUB3'] = 'op_margin_z'  # gp_growth_z → op_margin_z

boost_opm = {}
for d, rd in boost_data.items():
    rd_copy = copy.deepcopy(rd)
    # 임시로 regime_indicator를 바꾸지 않고 직접 rerank
    rankings = rd_copy.get('rankings', [])
    if not rankings: continue
    for r_item in rankings:
        s1 = (r_item.get('rev_z', 0) or 0) * 0.5
        s2 = (r_item.get('oca_z', 0) or 0) * 0.3
        s3 = (r_item.get('op_margin_z', 0) or 0) * 0.2
        r_item['_g'] = s1 + s2 + s3
    g_vals = [r_item['_g'] for r_item in rankings]
    g_mean = sum(g_vals)/len(g_vals); g_std = (sum((v-g_mean)**2 for v in g_vals)/len(g_vals))**0.5
    mom_key = 'mom_12m1m_s'
    for r_item in rankings:
        gs = (r_item['_g'] - g_mean)/g_std if g_std > 0 else 0
        r_item['score'] = round(0.05*(r_item.get('value_s',0) or 0) + 0.65*gs + 0.30*(r_item.get(mom_key,0) or 0), 4)
        r_item['momentum_s'] = r_item.get(mom_key, 0) or 0
        r_item.pop('_g', None)
    rankings.sort(key=lambda x: x['score'], reverse=True)
    for i, r_item in enumerate(rankings):
        r_item['composite_rank'] = i + 1
    rd_copy['rankings'] = rankings
    boost_opm[d] = rd_copy

# weighted_rank 재계산
dates_sorted = sorted(boost_opm.keys())
cr_maps = {d: {r_item['ticker']: r_item['composite_rank'] for r_item in boost_opm[d].get('rankings',[])} for d in dates_sorted}
for i, d in enumerate(dates_sorted):
    rankings = boost_opm[d].get('rankings', [])
    cr0 = cr_maps[d]
    cr1 = cr_maps[dates_sorted[i-1]] if i>=1 else {}
    cr2 = cr_maps[dates_sorted[i-2]] if i>=2 else {}
    for r_item in rankings:
        c0 = cr0.get(r_item['ticker'], PENALTY)
        c1 = cr1.get(r_item['ticker'], PENALTY)
        c2 = cr2.get(r_item['ticker'], PENALTY)
        r_item['weighted_rank'] = round(c0*0.5+c1*0.3+c2*0.2, 1)
    rankings.sort(key=lambda x: x['weighted_rank'])
    for j, r_item in enumerate(rankings):
        r_item['rank'] = j + 1

# 테스트B: gp_growth → op_margin
r_opm = simulate(boost_opm, defense_data, regime_by_date, ohlcv, v77_b, v77_d)
print(f'v77 원본 (gp_growth): CAGR={r["cagr"]}%, MDD={r["mdd"]}%, Cal={r["calmar"]}')
print(f'v77+op_margin:         CAGR={r_opm["cagr"]}%, MDD={r_opm["mdd"]}%, Cal={r_opm["calmar"]}')
print()
for yr in sorted(r['yearly']):
    yo = r['yearly'].get(yr, '-')
    yn = r_opm['yearly'].get(yr, '-')
    diff = round(yn - yo, 1) if isinstance(yn, float) and isinstance(yo, float) else '-'
    print(f'  {yr}: 원본={yo}% op_margin={yn}% (차이={diff})')


# ─── 모멘텀 기간 비교 ───
print('\n=== 모멘텀 기간 비교 (공격모드) ===')

for mom_label, mom_key in [('12m-1m (v77)', 'mom_12m1m_s'), ('12m', 'mom_12m_s'), ('6m-1m', 'mom_6m1m_s'), ('6m', 'mom_6m_s')]:
    boost_mom = {}
    for d, rd in boost_data.items():
        rd_copy = copy.deepcopy(rd)
        rankings = rd_copy.get('rankings', [])
        if not rankings: continue
        for r_item in rankings:
            s1 = (r_item.get('rev_z', 0) or 0) * 0.5
            s2 = (r_item.get('oca_z', 0) or 0) * 0.3
            s3 = (r_item.get('gp_growth_z', 0) or 0) * 0.2
            r_item['_g'] = s1 + s2 + s3
        g_vals = [r_item['_g'] for r_item in rankings]
        g_mean = sum(g_vals)/len(g_vals); g_std = (sum((v-g_mean)**2 for v in g_vals)/len(g_vals))**0.5
        for r_item in rankings:
            gs = (r_item['_g'] - g_mean)/g_std if g_std > 0 else 0
            r_item['score'] = round(0.05*(r_item.get('value_s',0) or 0) + 0.65*gs + 0.30*(r_item.get(mom_key,0) or 0), 4)
            r_item.pop('_g', None)
        rankings.sort(key=lambda x: x['score'], reverse=True)
        for i, r_item in enumerate(rankings):
            r_item['composite_rank'] = i + 1
        rd_copy['rankings'] = rankings
        boost_mom[d] = rd_copy

    # wr 재계산
    ds = sorted(boost_mom.keys())
    crm = {d: {r_item['ticker']: r_item['composite_rank'] for r_item in boost_mom[d].get('rankings',[])} for d in ds}
    for i, d in enumerate(ds):
        rks = boost_mom[d].get('rankings', [])
        c0 = crm[d]; c1 = crm[ds[i-1]] if i>=1 else {}; c2 = crm[ds[i-2]] if i>=2 else {}
        for r_item in rks:
            r_item['weighted_rank'] = round(c0.get(r_item['ticker'],PENALTY)*0.5+c1.get(r_item['ticker'],PENALTY)*0.3+c2.get(r_item['ticker'],PENALTY)*0.2, 1)
        rks.sort(key=lambda x: x['weighted_rank'])
        for j, r_item in enumerate(rks):
            r_item['rank'] = j + 1

    result = simulate(boost_mom, defense_data, regime_by_date, ohlcv, v77_b, v77_d)
    yrs = ' | '.join(f'{yr}:{result["yearly"].get(yr, "-")}%' for yr in range(2021, 2027))
    print(f'  {mom_label:>12}: CAGR={result["cagr"]}% MDD={result["mdd"]}% Cal={result["calmar"]} | {yrs}')

print('\n=== EDA 완료 ===')
