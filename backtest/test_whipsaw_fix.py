"""2018 whipsaw 보완 테스트 — 7.8년 + 5.25년 BT
시나리오: v77기본, C=7, C=10, B=2%, C=10+B=2%
"""
import sys, json, numpy as np, pandas as pd
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
from regime_indicator import get_regime_params

BT_EXT_H1 = Path(__file__).parent / 'bt_extended_h1'
BT_EXT_H1_D = Path(__file__).parent / 'bt_extended_h1_defense'
BT_EXT = Path(__file__).parent / 'bt_extended'
BT_EXT_D = Path(__file__).parent / 'bt_extended_defense'
STATE = Path(__file__).parent.parent / 'state'
STATE_D = STATE / 'defense'
CACHE = Path(__file__).parent.parent / 'data_cache'
PENALTY = 50


def load_all(dirs):
    data = {}
    for d in dirs:
        if not d.exists():
            continue
        for fp in sorted(d.glob('ranking_*.json')):
            if len(fp.stem.replace('ranking_', '')) != 8:
                continue
            k = fp.stem.replace('ranking_', '')
            if k not in data:  # 먼저 로드된 것 우선
                data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


print('데이터 로딩...', flush=True)
# boost: bt_extended_h1 + bt_extended + state
boost = load_all([BT_EXT_H1, BT_EXT, STATE])
# defense: bt_extended_h1_defense + bt_extended_defense + state/defense
defense = load_all([BT_EXT_H1_D, BT_EXT_D, STATE_D])

ohlcv_files = sorted(CACHE.glob('all_ohlcv_*.parquet'))
full = [f for f in ohlcv_files if '_full' in f.stem]
if full:
    ohlcv_list = [pd.read_parquet(f).replace(0, np.nan) for f in full]
else:
    # 최장 파일 우선
    ohlcv_list = [pd.read_parquet(f).replace(0, np.nan) for f in ohlcv_files]
ohlcv = pd.concat(ohlcv_list).groupby(level=0).first()

kospi_df = pd.read_parquet(CACHE / 'kospi_yf.parquet')
kospi = kospi_df.iloc[:, 0].fillna(kospi_df['kospi']).sort_index()
km200 = kospi.rolling(200).mean()

dates = sorted(set(boost.keys()) & set(defense.keys()))
print(f'Boost: {len(boost)}, Defense: {len(defense)}, 공통: {len(dates)}', flush=True)
print(f'날짜 범위: {dates[0]} ~ {dates[-1]}', flush=True)
print(f'OHLCV: {ohlcv.shape}, 범위: {ohlcv.index.min()} ~ {ohlcv.index.max()}', flush=True)

bp = get_regime_params('boost')
dp = get_regime_params('defense')


def calc_regime(confirm_days=5, buffer_pct=0.0, cooldown_days=0, start_mode=False):
    """확인일수/버퍼/쿨다운 적용 국면 판정"""
    reg = {}
    md = start_mode
    stk = 0
    ss = None
    last_switch = -99999
    for i, d in enumerate(dates):
        ts = pd.Timestamp(d)
        kv = kospi.get(ts)
        mv = km200.get(ts)
        if kv is None or mv is None or pd.isna(kv) or pd.isna(mv):
            reg[d] = md
            continue
        gap = (kv - mv) / mv * 100
        if gap > buffer_pct:
            s = True
        elif gap < -buffer_pct:
            s = False
        else:
            # 데드존: streak 리셋, mode 유지
            reg[d] = md
            ss = None
            stk = 0
            continue
        if s == ss:
            stk += 1
        else:
            stk = 1
            ss = s
        if stk >= confirm_days and md != s:
            if (i - last_switch) >= cooldown_days:
                md = s
                last_switch = i
        reg[d] = md
    sw = sum(1 for i in range(1, len(dates)) if reg[dates[i]] != reg[dates[i-1]])
    return reg, sw


def sim(bdata, ddata, reg, bp_, dp_, date_range=None):
    """date_range = (start, end) YYYYMMDD or None for full"""
    ad = {}
    ds_all = []
    common = sorted(set(bdata) & set(ddata))
    for d in common:
        if date_range and (d < date_range[0] or d > date_range[1]):
            continue
        ib = reg.get(d, True)
        if ib and d in bdata:
            ad[d] = bdata[d]; ds_all.append(d)
        elif not ib and d in ddata:
            ad[d] = ddata[d]; ds_all.append(d)
        elif d in bdata:
            ad[d] = bdata[d]; ds_all.append(d)
    ds = ds_all

    def gp(tk, ds_):
        ts = pd.Timestamp(ds_)
        if ts in ohlcv.index and tk in ohlcv.columns:
            v = ohlcv.loc[ts, tk]
            if pd.notna(v) and v > 0:
                return v
        return 0

    pf = {}; pk = {}; eq = 1.0; yeq = {}
    for i in range(len(ds)):
        d0 = ds[i]
        if i >= 1 and pf:
            rets = []
            for tk in pf:
                pp = gp(tk, ds[i-1]); cp = gp(tk, d0)
                if pp > 0 and cp > 0:
                    rets.append(cp/pp - 1)
            if rets:
                eq *= (1 + sum(rets)/len(rets))
        yeq[d0] = eq
        if i < 2:
            continue
        d1 = ds[i-1]; d2 = ds[i-2]
        ib = reg.get(d0, True)
        rp = bp_ if ib else dp_
        er = rp['ENTRY_RANK']; xr = rp['EXIT_RANK']; ms = rp['MAX_SLOTS']
        sl = rp.get('STOP_LOSS', -0.10); tr = rp.get('TRAILING_STOP', -0.15)

        if reg.get(d0, True) != reg.get(ds[i-1], True):
            pf.clear(); pk.clear()

        for tk in list(pf):
            c = gp(tk, d0); e = pf[tk]
            if tk in pk:
                if c > pk[tk]:
                    pk[tk] = c
            else:
                pk[tk] = max(c, e) if c > 0 else e
            if c > 0 and e > 0 and (c/e-1) <= sl:
                del pf[tk]; pk.pop(tk, None)
            elif c > 0 and pk.get(tk, 0) > 0 and (c/pk[tk]-1) <= tr:
                del pf[tk]; pk.pop(tk, None)

        r0 = ad[d0].get('rankings', [])
        r1 = ad[d1].get('rankings', [])
        r2 = ad[d2].get('rankings', [])
        t0 = {r['ticker']: r for r in r0 if r.get('composite_rank', r['rank']) <= 20}
        t1 = {r['ticker']: r for r in r1 if r.get('composite_rank', r['rank']) <= 20}
        t2 = {r['ticker']: r for r in r2 if r.get('composite_rank', r['rank']) <= 20}
        com = set(t0) & set(t1) & set(t2)
        a0 = {r['ticker']: r for r in r0}
        a1 = {r['ticker']: r for r in r1}
        a2 = {r['ticker']: r for r in r2}

        def wr(tk):
            if tk not in a0:
                return 999
            c0 = a0[tk].get('composite_rank', 999)
            c1 = a1[tk].get('composite_rank', 999) if tk in a1 else 999
            c2 = a2[tk].get('composite_rank', 999) if tk in a2 else 999
            return c0*0.5 + c1*0.3 + c2*0.2

        for tk in list(pf):
            if wr(tk) > xr:
                del pf[tk]

        vf = sorted([{'ticker': tk, 'wr': wr(tk)} for tk in com], key=lambda x: x['wr'])
        for v in vf[:er]:
            if v['ticker'] in pf:
                continue
            if len(pf) >= ms:
                break
            e = gp(v['ticker'], d0)
            if e > 0:
                pf[v['ticker']] = e
                pk[v['ticker']] = e

    yearly = {}
    es = sorted(yeq.items())
    for yr in range(2018, 2027):
        yd = [(d, e) for d, e in es if f'{yr}0101' <= d <= f'{yr}1231']
        if len(yd) >= 2:
            yearly[yr] = round((yd[-1][1]/yd[0][1] - 1)*100, 1)
    t = round((eq-1)*100, 1)
    ea = np.array([e for _, e in es])
    if len(ea) < 2:
        return {'yearly': yearly, 'total': 0, 'mdd': 0, 'cagr': 0, 'calmar': 0}
    pk_arr = np.maximum.accumulate(ea)
    dd = (ea - pk_arr)/pk_arr
    mdd = round(abs(dd.min())*100, 1)
    days = len(ds)-2
    yrs = days/252
    cagr = round((eq**(1/yrs)-1)*100, 1) if yrs > 0 else 0
    return {'yearly': yearly, 'total': t, 'mdd': mdd, 'cagr': cagr,
            'calmar': round(cagr/mdd, 2) if mdd > 0 else 0}


# ═══════════════════════════════════════════
scenarios = [
    ('v77 기본 (C5 B0 CD0)', 5, 0.0, 0),
    ('C=7', 7, 0.0, 0),
    ('C=10', 10, 0.0, 0),
    ('C=15', 15, 0.0, 0),
    ('B=1%', 5, 1.0, 0),
    ('B=2%', 5, 2.0, 0),
    ('B=3%', 5, 3.0, 0),
    ('CD=20', 5, 0.0, 20),
    ('CD=30', 5, 0.0, 30),
    ('C=7 + B=1%', 7, 1.0, 0),
    ('C=7 + CD=20', 7, 0.0, 20),
    ('C=10 + B=2%', 10, 2.0, 0),
    ('C=10 + CD=30', 10, 0.0, 30),
]

for label_range, drange in [('8.3년 (2018-01 ~ 2026-04)', ('20180102', '20260413')),
                              ('7.8년 (2018-07 ~ 2026-04)', ('20180702', '20260413')),
                              ('5.25년 (2021-01 ~ 2026-04)', ('20210104', '20260413'))]:
    print(f'\n═══ {label_range} ═══', flush=True)
    print(f'{"시나리오":<25} {"전환":>4} {"CAGR":>7} {"MDD":>7} {"Cal":>6} | 연도별', flush=True)
    print('-' * 120, flush=True)
    for label, cd, buf, cdd in scenarios:
        reg, sw = calc_regime(cd, buf, cdd)
        r = sim(boost, defense, reg, bp, dp, date_range=drange)
        y_keys = sorted(r['yearly'].keys())
        yrs_str = ' '.join(f'{yr}:{r["yearly"][yr]:>+6.1f}%' for yr in y_keys)
        print(f'{label:<25} {sw:>4} {r["cagr"]:>6.1f}% {r["mdd"]:>6.1f}% {r["calmar"]:>5.2f} | {yrs_str}', flush=True)

print('\n완료', flush=True)
