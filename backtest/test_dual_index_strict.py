"""이중 AND 엄격 해석 7.8년 BT — KOSDAQ 완전 데이터 (2014-01~) 사용

엄격 해석: KOSPI MA200 또는 KOSDAQ MA200 값이 없거나 둘이 상충이면 현 mode 유지
"""
import sys, json, numpy as np, pandas as pd
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
from regime_indicator import get_regime_params

BT_EXT = Path(__file__).parent / 'bt_extended'
BT_EXT_D = Path(__file__).parent / 'bt_extended_defense'
STATE = Path(__file__).parent.parent / 'state'
STATE_D = STATE / 'defense'
CACHE = Path(__file__).parent.parent / 'data_cache'


def load_all(dirs):
    data = {}
    for d in dirs:
        if not d.exists(): continue
        for fp in sorted(d.glob('ranking_*.json')):
            if len(fp.stem.replace('ranking_', '')) != 8: continue
            k = fp.stem.replace('ranking_', '')
            if k not in data:
                data[k] = json.load(open(fp, 'r', encoding='utf-8'))
    return data


print('로딩...', flush=True)
boost = load_all([BT_EXT, STATE])
defense = load_all([BT_EXT_D, STATE_D])
ohlcv = pd.concat([pd.read_parquet(f).replace(0, np.nan) for f in sorted(CACHE.glob('all_ohlcv_*.parquet'))]).groupby(level=0).first()

kospi_df = pd.read_parquet(CACHE / 'kospi_yf.parquet')
kospi = kospi_df.iloc[:, 0].fillna(kospi_df['kospi']).sort_index()
kp_ma200 = kospi.rolling(200).mean()

# 완전 KOSDAQ 시리즈
kosdaq = pd.read_parquet(CACHE / 'kosdaq_full_20140102_20260413.parquet')['종가'].sort_index()
kd_ma200 = kosdaq.rolling(200).mean()

dates = sorted(set(boost.keys()) & set(defense.keys()))
print(f'공통: {len(dates)} ({dates[0]} ~ {dates[-1]})', flush=True)
print(f'KOSPI MA200 첫값: {kp_ma200.first_valid_index()}', flush=True)
print(f'KOSDAQ MA200 첫값: {kd_ma200.first_valid_index()}', flush=True)
print(f'2018-07-02 KOSDAQ MA200: {kd_ma200.get(pd.Timestamp("20180702"))}', flush=True)


def calc_regime(mode='dual_and_strict', confirm_days=5):
    reg = {}
    md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d)
        kp_v = kospi.get(ts); kp_m = kp_ma200.get(ts)
        kd_v = kosdaq.get(ts); kd_m = kd_ma200.get(ts)
        kp_above = (kp_v > kp_m) if (kp_v is not None and kp_m is not None and not pd.isna(kp_m)) else None
        kd_above = (kd_v > kd_m) if (kd_v is not None and kd_m is not None and not pd.isna(kd_m)) else None

        if mode == 'kospi':
            if kp_above is None:
                reg[d] = md; continue
            s = kp_above
        elif mode == 'dual_and_strict':
            # 둘 다 값 있어야. 없으면 유지. 상충도 유지.
            if kp_above is None or kd_above is None:
                reg[d] = md; continue
            if kp_above == kd_above:
                s = kp_above
            else:
                reg[d] = md; continue
        else:
            raise ValueError(mode)

        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm_days and md != s:
            md = s
        reg[d] = md

    sw = sum(1 for i in range(1, len(dates)) if reg[dates[i]] != reg[dates[i-1]])
    return reg, sw


def sim(bdata, ddata, reg, bp_, dp_, date_range=None):
    ad = {}; ds = []
    for d in sorted(set(bdata) & set(ddata)):
        if date_range and (d < date_range[0] or d > date_range[1]): continue
        ib = reg.get(d, True)
        if ib and d in bdata:
            ad[d] = bdata[d]; ds.append(d)
        elif not ib and d in ddata:
            ad[d] = ddata[d]; ds.append(d)

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
        a0 = {r['ticker']: r for r in r0}; a1 = {r['ticker']: r for r in r1}; a2 = {r['ticker']: r for r in r2}
        def wr(tk):
            if tk not in a0: return 999
            c0 = a0[tk].get('composite_rank', 999)
            c1 = a1[tk].get('composite_rank', 999) if tk in a1 else 999
            c2 = a2[tk].get('composite_rank', 999) if tk in a2 else 999
            return c0*0.5 + c1*0.3 + c2*0.2
        for tk in list(pf):
            if wr(tk) > xr: del pf[tk]
        vf = sorted([{'ticker': tk, 'wr': wr(tk)} for tk in com], key=lambda x: x['wr'])
        for v in vf[:er]:
            if v['ticker'] in pf: continue
            if len(pf) >= ms: break
            e = gp(v['ticker'], d0)
            if e > 0:
                pf[v['ticker']] = e; pk[v['ticker']] = e

    yearly = {}
    es = sorted(yeq.items())
    for yr in range(2018, 2027):
        yd = [(d, e) for d, e in es if f'{yr}0101' <= d <= f'{yr}1231']
        if len(yd) >= 2:
            yearly[yr] = round((yd[-1][1]/yd[0][1] - 1)*100, 1)
    ea = np.array([e for _, e in es])
    if len(ea) < 2:
        return {'yearly': yearly, 'cagr': 0, 'mdd': 0, 'cal': 0}
    pk_arr = np.maximum.accumulate(ea)
    dd = (ea - pk_arr)/pk_arr
    mdd = round(abs(dd.min())*100, 1)
    days = len(ds)-2; yrs = days/252
    cagr = round((eq**(1/yrs)-1)*100, 1) if yrs > 0 else 0
    return {'yearly': yearly, 'cagr': cagr, 'mdd': mdd,
            'cal': round(cagr/mdd, 2) if mdd > 0 else 0}


bp = get_regime_params('boost')
dp = get_regime_params('defense')

scenarios = [
    ('v77 기본 (KOSPI C=5)', 'kospi', 5),
    ('이중 AND 엄격 C=5', 'dual_and_strict', 5),
    ('이중 AND 엄격 C=7', 'dual_and_strict', 7),
    ('이중 AND 엄격 C=10', 'dual_and_strict', 10),
]

for label_range, drange in [('7.8년 (2018-07 ~ 2026-04)', ('20180702', '20260413')),
                              ('5.25년 (2021-01 ~ 2026-04)', ('20210104', '20260413'))]:
    print(f'\n═══ {label_range} ═══', flush=True)
    print(f'{"시나리오":<28} {"전환":>4} {"CAGR":>7} {"MDD":>7} {"Cal":>6} | 연도별', flush=True)
    print('-' * 130, flush=True)
    for label, mode_name, cd in scenarios:
        reg, sw = calc_regime(mode=mode_name, confirm_days=cd)
        r = sim(boost, defense, reg, bp, dp, date_range=drange)
        y = ' '.join(f'{yr}:{r["yearly"].get(yr, 0):>+6.1f}%' for yr in sorted(r['yearly']))
        print(f'{label:<28} {sw:>4} {r["cagr"]:>6.1f}% {r["mdd"]:>6.1f}% {r["cal"]:>5.2f} | {y}', flush=True)

print('\n완료', flush=True)
