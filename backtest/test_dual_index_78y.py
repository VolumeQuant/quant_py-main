"""이중지표 7.8년 BT — KOSDAQ 없는 구간은 KOSPI fallback
2018-07-02 ~ 2020-05-31: KOSPI만 (KOSDAQ 데이터 없음)
2020-06-01 ~ 2026-04-13: KOSPI + KOSDAQ AND

비교 시나리오:
  1. v77 기본 (7.8년 전체 KOSPI만)
  2. 이중 AND fallback (KOSDAQ 없으면 KOSPI만)
  3. 이중 AND C=5 완전판 (KOSDAQ 있을 때만 AND)
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


print('데이터 로딩...', flush=True)
boost = load_all([BT_EXT, STATE])
defense = load_all([BT_EXT_D, STATE_D])

ohlcv_files = sorted(CACHE.glob('all_ohlcv_*.parquet'))
ohlcv = pd.concat([pd.read_parquet(f).replace(0, np.nan) for f in ohlcv_files]).groupby(level=0).first()

kospi_df = pd.read_parquet(CACHE / 'kospi_yf.parquet')
kospi = kospi_df.iloc[:, 0].fillna(kospi_df['kospi']).sort_index()
kp_ma200 = kospi.rolling(200).mean()

kosdaq_df = pd.read_parquet(CACHE / 'kosdaq_yf.parquet')
kosdaq = kosdaq_df.iloc[:, 0].fillna(kosdaq_df['kosdaq']).sort_index()
kd_ma200 = kosdaq.rolling(200).mean()

dates = sorted(set(boost.keys()) & set(defense.keys()))
print(f'Boost/Defense/공통: {len(boost)}/{len(defense)}/{len(dates)}', flush=True)
print(f'날짜: {dates[0]} ~ {dates[-1]}', flush=True)

bp = get_regime_params('boost')
dp = get_regime_params('defense')


def calc_regime(mode='kospi', confirm_days=5):
    reg = {}
    md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d)
        kp_v = kospi.get(ts); kp_m = kp_ma200.get(ts)
        kd_v = kosdaq.get(ts); kd_m = kd_ma200.get(ts)
        kp_above = (kp_v > kp_m) if (kp_v is not None and kp_m is not None and not pd.isna(kp_m)) else None
        kd_above = (kd_v > kd_m) if (kd_v is not None and kd_m is not None and not pd.isna(kd_m)) else None

        if kp_above is None:
            reg[d] = md; continue

        if mode == 'kospi':
            s = kp_above
        elif mode == 'dual_and_fallback':
            # KOSDAQ 없으면 KOSPI만
            if kd_above is None:
                s = kp_above
            elif kp_above == kd_above:
                s = kp_above
            else:
                # 상충 → 유지 (streak 끊지 않음)
                reg[d] = md; continue
        elif mode == 'dual_and_strict':
            # KOSDAQ 있을 때만 AND 평가, 없으면 전환 안 함
            if kd_above is None:
                reg[d] = md; continue
            if kp_above == kd_above:
                s = kp_above
            else:
                reg[d] = md; continue
        else:
            s = kp_above

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
        elif d in bdata:
            ad[d] = bdata[d]; ds.append(d)

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
        a0 = {r['ticker']: r for r in r0}
        a1 = {r['ticker']: r for r in r1}
        a2 = {r['ticker']: r for r in r2}

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
        return {'yearly': yearly, 'total': 0, 'mdd': 0, 'cagr': 0, 'calmar': 0}
    pk_arr = np.maximum.accumulate(ea)
    dd = (ea - pk_arr)/pk_arr
    mdd = round(abs(dd.min())*100, 1)
    days = len(ds)-2; yrs = days/252
    cagr = round((eq**(1/yrs)-1)*100, 1) if yrs > 0 else 0
    return {'yearly': yearly, 'total': round((eq-1)*100, 1), 'mdd': mdd, 'cagr': cagr,
            'calmar': round(cagr/mdd, 2) if mdd > 0 else 0}


scenarios = [
    ('v77 기본 (KOSPI C=5)', 'kospi', 5),
    ('이중 AND fallback C=5', 'dual_and_fallback', 5),
    ('이중 AND fallback C=7', 'dual_and_fallback', 7),
]

for label_range, drange in [('7.8년 (2018-07 ~ 2026-04)', ('20180702', '20260413')),
                              ('5.25년 (2021-01 ~ 2026-04)', ('20210104', '20260413')),
                              ('KOSDAQ구간 (2020-06 ~ 2026-04)', ('20200601', '20260413'))]:
    print(f'\n═══ {label_range} ═══', flush=True)
    print(f'{"시나리오":<30} {"전환":>4} {"CAGR":>7} {"MDD":>7} {"Cal":>6} | 연도별', flush=True)
    print('-' * 120, flush=True)
    for label, mode, cd in scenarios:
        reg, sw = calc_regime(mode=mode, confirm_days=cd)
        r = sim(boost, defense, reg, bp, dp, date_range=drange)
        y_keys = sorted(r['yearly'].keys())
        yrs_str = ' '.join(f'{yr}:{r["yearly"][yr]:>+6.1f}%' for yr in y_keys)
        print(f'{label:<30} {sw:>4} {r["cagr"]:>6.1f}% {r["mdd"]:>6.1f}% {r["calmar"]:>5.2f} | {yrs_str}', flush=True)

print('\n완료', flush=True)
