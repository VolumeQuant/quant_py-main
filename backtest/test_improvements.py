"""Phase 3: v77 개선안 테스트 — 확인일수 + 방어모드 강화"""
import sys, json, numpy as np, pandas as pd, copy
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
from regime_indicator import get_regime_params

STATE_DIR = Path(__file__).parent.parent / 'state'
CACHE_DIR = Path(__file__).parent.parent / 'data_cache'
PENALTY = 50

# ─── 데이터 로딩 ───
def load_all(d):
    data = {}
    for fp in sorted(d.glob('ranking_*.json')):
        if len(fp.stem.replace('ranking_', '')) != 8: continue
        data[fp.stem.replace('ranking_', '')] = json.load(open(fp, 'r', encoding='utf-8'))
    return data

print('데이터 로딩...')
boost = load_all(STATE_DIR)
defense = load_all(STATE_DIR / 'defense')
ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
full = [f for f in ohlcv_files if '_full' in f.stem]
ohlcv = pd.concat([pd.read_parquet(f).replace(0, np.nan) for f in (full or ohlcv_files)]).groupby(level=0).first()
kospi = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet').iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()
dates = sorted(boost.keys())
print(f'Boost: {len(boost)}, Defense: {len(defense)}, OHLCV: {ohlcv.shape}')

bp = get_regime_params('boost')
dp = get_regime_params('defense')


def calc_regime(confirm_days):
    reg = {}
    md = False; stk = 0; ss = False
    for d in dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = km200.get(ts)
        s = (kv > mv) if kv is not None and mv is not None else md
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm_days and md != s: md = s
        reg[d] = md
    sw = sum(1 for i in range(1, len(dates)) if reg[dates[i]] != reg[dates[i-1]])
    return reg, sw


def sim(bdata, ddata, reg, bp_, dp_):
    ad = {}; ds = []
    for d in sorted(set(bdata) & set(ddata)):
        ib = reg.get(d, True)
        if ib and d in bdata: ad[d] = bdata[d]; ds.append(d)
        elif not ib and d in ddata: ad[d] = ddata[d]; ds.append(d)
        elif d in bdata: ad[d] = bdata[d]; ds.append(d)

    def gp(tk, ds_):
        ts = pd.Timestamp(ds_)
        if ts in ohlcv.index and tk in ohlcv.columns:
            v = ohlcv.loc[ts, tk]
            if pd.notna(v) and v > 0: return v
        return 0

    pf = {}; pk = {}; eq = 1.0; yeq = {}
    for i in range(len(ds)):
        d0 = ds[i]
        if i >= 1 and pf:
            rets = []
            for tk in pf:
                pp = gp(tk, ds[i-1]); cp = gp(tk, d0)
                if pp > 0 and cp > 0: rets.append(cp/pp - 1)
            if rets: eq *= (1 + sum(rets)/len(rets))
        yeq[d0] = eq
        if i < 2: continue
        d1 = ds[i-1]; d2 = ds[i-2]
        ib = reg.get(d0, True); rp = bp_ if ib else dp_
        er = rp['ENTRY_RANK']; xr = rp['EXIT_RANK']; ms = rp['MAX_SLOTS']
        sl = rp.get('STOP_LOSS', -0.10); tr = rp.get('TRAILING_STOP', -0.15)

        if reg.get(d0, True) != reg.get(ds[i-1], True):
            pf.clear(); pk.clear()

        for tk in list(pf):
            c = gp(tk, d0); e = pf[tk]
            if tk in pk:
                if c > pk[tk]: pk[tk] = c
            else: pk[tk] = max(c, e) if c > 0 else e
            if c > 0 and e > 0 and (c/e-1) <= sl: del pf[tk]; pk.pop(tk, None)
            elif c > 0 and pk.get(tk, 0) > 0 and (c/pk[tk]-1) <= tr: del pf[tk]; pk.pop(tk, None)

        r0 = ad[d0].get('rankings', []); r1 = ad[d1].get('rankings', []); r2 = ad[d2].get('rankings', [])
        t0 = {r['ticker']:r for r in r0 if r.get('composite_rank', r['rank']) <= 20}
        t1 = {r['ticker']:r for r in r1 if r.get('composite_rank', r['rank']) <= 20}
        t2 = {r['ticker']:r for r in r2 if r.get('composite_rank', r['rank']) <= 20}
        com = set(t0) & set(t1) & set(t2)
        a0 = {r['ticker']:r for r in r0}; a1 = {r['ticker']:r for r in r1}; a2 = {r['ticker']:r for r in r2}

        def wr(tk):
            if tk not in a0: return 999
            c0 = a0[tk].get('composite_rank', 999)
            c1 = a1[tk].get('composite_rank', 999) if tk in a1 else 999
            c2 = a2[tk].get('composite_rank', 999) if tk in a2 else 999
            return c0*0.5 + c1*0.3 + c2*0.2

        for tk in list(pf):
            if wr(tk) > xr: del pf[tk]

        vf = sorted([{'ticker':tk, 'wr':wr(tk)} for tk in com], key=lambda x: x['wr'])
        for v in vf[:er]:
            if v['ticker'] in pf: continue
            if len(pf) >= ms: break
            e = gp(v['ticker'], d0)
            if e > 0: pf[v['ticker']] = e; pk[v['ticker']] = e

    yearly = {}
    es = sorted(yeq.items())
    for yr in range(2020, 2027):
        yd = [(d, e) for d, e in es if f'{yr}0101' <= d <= f'{yr}1231']
        if len(yd) >= 2: yearly[yr] = round((yd[-1][1]/yd[0][1] - 1)*100, 1)
    t = round((eq-1)*100, 1)
    ea = np.array([e for _, e in es])
    pk_arr = np.maximum.accumulate(ea)
    dd = (ea - pk_arr)/pk_arr
    mdd = round(abs(dd.min())*100, 1)
    days = len(ds)-2; yrs = days/252
    cagr = round((eq**(1/yrs)-1)*100, 1) if yrs > 0 else 0
    return {'yearly': yearly, 'total': t, 'mdd': mdd, 'cagr': cagr,
            'calmar': round(cagr/mdd, 2) if mdd > 0 else 0}


def rerank_defense(defense_data, dp_test):
    """방어 ranking을 다른 파라미터로 재계산"""
    def_reranked = {}
    g_sub1 = dp_test.get('G_SUB1', 'rev_accel_z')
    g_sub2 = dp_test.get('G_SUB2', 'op_margin_z')
    g_rev = dp_test.get('G_REV', 0.5)
    mom_map = {'12m': 'mom_12m_s', '12m-1m': 'mom_12m1m_s', '6m': 'mom_6m_s', '6m-1m': 'mom_6m1m_s'}
    mom_key = mom_map.get(dp_test.get('MOM_PERIOD', '6m-1m'), 'mom_6m1m_s')

    for d, rd in defense_data.items():
        rd_c = copy.deepcopy(rd)
        rankings = rd_c.get('rankings', [])
        if not rankings: continue

        for ri in rankings:
            s1 = (ri.get(g_sub1, 0) or 0) * g_rev
            s2 = (ri.get(g_sub2, 0) or 0) * (1 - g_rev)
            ri['_g'] = s1 + s2
        gv = [ri['_g'] for ri in rankings]
        gm = sum(gv)/len(gv)
        gs = (sum((v-gm)**2 for v in gv)/len(gv))**0.5

        for ri in rankings:
            g = (ri['_g'] - gm)/gs if gs > 0 else 0
            ri['score'] = round(
                dp_test['V_W'] * (ri.get('value_s', 0) or 0) +
                dp_test['Q_W'] * (ri.get('quality_s', 0) or 0) +
                dp_test['G_W'] * g +
                dp_test['M_W'] * (ri.get(mom_key, 0) or 0), 4)
            ri.pop('_g', None)

        rankings.sort(key=lambda x: x['score'], reverse=True)
        for i, ri in enumerate(rankings): ri['composite_rank'] = i + 1
        rd_c['rankings'] = rankings
        def_reranked[d] = rd_c

    # weighted_rank 재계산
    ds = sorted(def_reranked.keys())
    crm = {d: {ri['ticker']: ri['composite_rank'] for ri in def_reranked[d].get('rankings', [])} for d in ds}
    for i, d in enumerate(ds):
        rks = def_reranked[d].get('rankings', [])
        c0 = crm[d]
        c1 = crm[ds[i-1]] if i >= 1 else {}
        c2 = crm[ds[i-2]] if i >= 2 else {}
        for ri in rks:
            ri['weighted_rank'] = round(
                c0.get(ri['ticker'], PENALTY)*0.5 +
                c1.get(ri['ticker'], PENALTY)*0.3 +
                c2.get(ri['ticker'], PENALTY)*0.2, 1)
        rks.sort(key=lambda x: x['weighted_rank'])
        for j, ri in enumerate(rks): ri['rank'] = j + 1

    return def_reranked


# ═══════════════════════════════════════════
# 테스트 C: 확인일수 변경
# ═══════════════════════════════════════════
print('\n=== 테스트 C: 확인일수별 성과 (2021~2026) ===')
print(f'{"확인일":>6} {"전환":>4} {"CAGR":>8} {"MDD":>7} {"Cal":>6} | 2021  2022  2023  2024  2025  2026')
print('-' * 90)
for cd in [3, 5, 7, 10, 15, 20, 30]:
    reg, sw = calc_regime(cd)
    r = sim(boost, defense, reg, bp, dp)
    yrs = '  '.join(f'{r["yearly"].get(yr, "-"):>5}' for yr in range(2021, 2027))
    print(f'{cd:>4}일 {sw:>4}회 {r["cagr"]:>7.1f}% {r["mdd"]:>6.1f}% {r["calmar"]:>5.2f} | {yrs}')


# ═══════════════════════════════════════════
# 테스트 A: 방어모드 강화
# ═══════════════════════════════════════════
print('\n=== 테스트 A: 방어모드 변형 (2021~2026, 확인5일) ===')

reg5, _ = calc_regime(5)

variants = [
    ('v77 기본 (V30Q5G10M55 E3X6S7)', dp),
    ('M70 (V10Q0G20M70)', {**dp, 'V_W': 0.10, 'Q_W': 0.00, 'G_W': 0.20, 'M_W': 0.70}),
    ('M80 (V10Q0G10M80)', {**dp, 'V_W': 0.10, 'Q_W': 0.00, 'G_W': 0.10, 'M_W': 0.80}),
    ('타이트 E3X4S5', {**dp, 'EXIT_RANK': 4, 'MAX_SLOTS': 5}),
    ('타이트 E3X4S3', {**dp, 'EXIT_RANK': 4, 'MAX_SLOTS': 3}),
    ('12m-1m 방어', {**dp, 'MOM_PERIOD': '12m-1m'}),
    ('12m-1m+타이트 E3X4S5', {**dp, 'MOM_PERIOD': '12m-1m', 'EXIT_RANK': 4, 'MAX_SLOTS': 5}),
    ('rev+oca 방어', {**dp, 'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_REV': 0.7}),
    ('rev+oca+12m-1m E3X4S5', {**dp, 'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_REV': 0.7,
                                 'MOM_PERIOD': '12m-1m', 'EXIT_RANK': 4, 'MAX_SLOTS': 5}),
]

print(f'{"방어모드":>35} {"CAGR":>8} {"MDD":>7} {"Cal":>6} | 2021  2022  2023  2024  2025  2026')
print('-' * 100)
for label, dp_test in variants:
    def_rr = rerank_defense(defense, dp_test)
    r = sim(boost, def_rr, reg5, bp, dp_test)
    yrs = '  '.join(f'{r["yearly"].get(yr, "-"):>5}' for yr in range(2021, 2027))
    print(f'{label:>35} {r["cagr"]:>7.1f}% {r["mdd"]:>6.1f}% {r["calmar"]:>5.2f} | {yrs}')

print('\n=== 테스트 완료 ===')
