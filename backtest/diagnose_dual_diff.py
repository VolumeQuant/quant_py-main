"""1차 5.00 vs 2차 4.22 차이 원인 진단

가설 A: T-1/T-2 데이터 유무 (첫 2일 수익 반영 차이)
가설 B: 국면 regime 누적 상태 (2018-07부터 누적 vs fresh start)

3가지 모드로 비교:
  1. state only, fresh regime (1차 테스트 = Cal 5.00 재현)
  2. bt_ext+state, regime from 2021-01-04 only (T-1/T-2 있지만 regime fresh)
  3. bt_ext+state, regime from 2018-07-02 (2차 테스트 = Cal 4.22 재현)

차이로 원인 분리:
  1→2: T-1/T-2 효과
  2→3: regime 누적 상태 효과
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
boost_state = load_all([STATE])
defense_state = load_all([STATE_D])
boost_full = load_all([BT_EXT, STATE])
defense_full = load_all([BT_EXT_D, STATE_D])

ohlcv_files = sorted(CACHE.glob('all_ohlcv_*.parquet'))
ohlcv = pd.concat([pd.read_parquet(f).replace(0, np.nan) for f in ohlcv_files]).groupby(level=0).first()

kospi_df = pd.read_parquet(CACHE / 'kospi_yf.parquet')
kospi = kospi_df.iloc[:, 0].fillna(kospi_df['kospi']).sort_index()
kp_ma200 = kospi.rolling(200).mean()

kosdaq_df = pd.read_parquet(CACHE / 'kosdaq_yf.parquet')
kosdaq = kosdaq_df.iloc[:, 0].fillna(kosdaq_df['kosdaq']).sort_index()
kd_ma200 = kosdaq.rolling(200).mean()


def calc_regime(dates_input, mode='dual_and', confirm_days=5):
    reg = {}
    md = False; stk = 0; ss = None
    for d in dates_input:
        ts = pd.Timestamp(d)
        kp_v = kospi.get(ts); kp_m = kp_ma200.get(ts)
        kd_v = kosdaq.get(ts); kd_m = kd_ma200.get(ts)
        kp_above = (kp_v > kp_m) if (kp_v is not None and kp_m is not None and not pd.isna(kp_m)) else None
        kd_above = (kd_v > kd_m) if (kd_v is not None and kd_m is not None and not pd.isna(kd_m)) else None

        if kp_above is None:
            reg[d] = md; continue

        if mode == 'kospi':
            s = kp_above
        elif mode == 'dual_and':
            if kd_above is None:
                s = kp_above
            elif kp_above == kd_above:
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
    return reg


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
    for yr in range(2021, 2027):
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

dates_state_only = sorted(set(boost_state) & set(defense_state))
dates_full = sorted(set(boost_full) & set(defense_full))

print(f'state only: {dates_state_only[0]} ~ {dates_state_only[-1]} ({len(dates_state_only)}일)')
print(f'full: {dates_full[0]} ~ {dates_full[-1]} ({len(dates_full)}일)')

drange_525 = ('20210104', '20260413')

# 모드 1: state only, regime from 2021-01-04 (1차 테스트 재현)
print('\n=== 모드 1: state only, regime fresh from 2021-01-04 (1차 테스트 = 5.00 재현) ===')
for mode_name in ['kospi', 'dual_and']:
    reg = calc_regime(dates_state_only, mode=mode_name, confirm_days=5)
    r = sim(boost_state, defense_state, reg, bp, dp, date_range=drange_525)
    y = ' '.join(f'{yr}:{r["yearly"].get(yr, 0):>+6.1f}%' for yr in sorted(r['yearly']))
    print(f'  {mode_name:12s}: CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}% Cal={r["cal"]:.2f} | {y}')

# 모드 2: bt_full 있지만 regime은 2021-01-04부터만 계산 (fresh regime, T-1/T-2 있음)
print('\n=== 모드 2: bt_full + regime fresh from 2021-01-04 (T-1/T-2 있음, regime fresh) ===')
dates_from_2021 = [d for d in dates_full if d >= '20210104']
for mode_name in ['kospi', 'dual_and']:
    reg = calc_regime(dates_from_2021, mode=mode_name, confirm_days=5)
    r = sim(boost_full, defense_full, reg, bp, dp, date_range=drange_525)
    y = ' '.join(f'{yr}:{r["yearly"].get(yr, 0):>+6.1f}%' for yr in sorted(r['yearly']))
    print(f'  {mode_name:12s}: CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}% Cal={r["cal"]:.2f} | {y}')

# 모드 3: bt_full, regime from 2018-07 (2차 테스트 재현)
print('\n=== 모드 3: bt_full + regime accumulated from 2018-07 (2차 테스트 = 4.22 재현) ===')
for mode_name in ['kospi', 'dual_and']:
    reg = calc_regime(dates_full, mode=mode_name, confirm_days=5)
    r = sim(boost_full, defense_full, reg, bp, dp, date_range=drange_525)
    y = ' '.join(f'{yr}:{r["yearly"].get(yr, 0):>+6.1f}%' for yr in sorted(r['yearly']))
    print(f'  {mode_name:12s}: CAGR={r["cagr"]:.1f}% MDD={r["mdd"]:.1f}% Cal={r["cal"]:.2f} | {y}')

print('\n완료')
