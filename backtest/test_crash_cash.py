"""3-tier 시스템 BT: 공격 / 방어(종목 보유) / 현금(크래시 때만)

로직:
  공격 (KOSPI > MA200 5일 확인)
  방어 (KOSPI < MA200 5일 확인)
    └ 하지만 극단 조건 발동 시 현금 전환
  극단 조건 (OR):
    - 20일 변동성 > threshold_vol
    - 20일 수익률 < threshold_mom
  조건 해제되면 방어 모드 재진입

시나리오:
  1. v77 기본 (공격+방어, 현금 없음) — 기준선
  2. 방어=현금 (비교용)
  3. 극단 조건(3% vol)에서만 현금
  4. 극단 조건(2.5% vol)에서만 현금
  5. 20일 수익률 -20%에서만 현금
  6. vol 3% OR mom -20%
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
vol20 = kospi.pct_change().rolling(20).std()  # 일일 std의 20일
ret20 = kospi.pct_change(20)  # 20일 수익률

dates = sorted(set(boost.keys()) & set(defense.keys()))
bp = get_regime_params('boost')
dp = get_regime_params('defense')


def calc_regime_3tier(vol_thresh=None, mom_thresh=None, confirm_days=5):
    """
    반환: regime dict {date: 'attack'/'defense'/'cash'}
    """
    reg = {}
    md = 'defense'  # 공격/방어 (크래시 체크는 별도)
    stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = kp_ma200.get(ts)
        v20 = vol20.get(ts)
        r20 = ret20.get(ts)
        if kv is None or mv is None or pd.isna(mv):
            reg[d] = md; continue
        # 1. 기본 공격/방어 결정
        s = 'attack' if kv > mv else 'defense'
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm_days and md != s:
            md = s

        # 2. 방어 상태에서 크래시 조건 체크 → 현금
        final = md
        if md == 'defense':
            crash = False
            if vol_thresh is not None and v20 is not None and not pd.isna(v20):
                if v20 * 100 > vol_thresh:
                    crash = True
            if mom_thresh is not None and r20 is not None and not pd.isna(r20):
                if r20 * 100 < mom_thresh:
                    crash = True
            if crash:
                final = 'cash'
        reg[d] = final
    return reg


def sim(bdata, ddata, reg, bp_, dp_, date_range=None):
    """regime: {date: 'attack'/'defense'/'cash'}"""
    ad = {}; ds = []
    for d in sorted(set(bdata) & set(ddata)):
        if date_range and (d < date_range[0] or d > date_range[1]): continue
        mode = reg.get(d, 'attack')
        if mode == 'attack':
            if d in bdata: ad[d] = bdata[d]; ds.append(d)
        elif mode == 'defense':
            if d in ddata: ad[d] = ddata[d]; ds.append(d)
        else:  # cash
            ad[d] = {'rankings': []}
            ds.append(d)

    def gp(tk, ds_):
        ts = pd.Timestamp(ds_)
        if ts in ohlcv.index and tk in ohlcv.columns:
            v = ohlcv.loc[ts, tk]
            if pd.notna(v) and v > 0: return v
        return 0

    pf = {}; pk = {}; eq = 1.0; yeq = {}
    prev_mode = None
    for i in range(len(ds)):
        d0 = ds[i]
        if i >= 1 and pf:
            rets = []
            for tk in pf:
                pp = gp(tk, ds[i-1]); cp = gp(tk, d0)
                if pp > 0 and cp > 0: rets.append(cp/pp - 1)
            if rets: eq *= (1 + sum(rets)/len(rets))
        yeq[d0] = eq
        if i < 2:
            prev_mode = reg.get(d0)
            continue

        cur_mode = reg.get(d0, 'attack')
        # 모드 전환 시 전량 청산
        if prev_mode and cur_mode != prev_mode:
            pf.clear(); pk.clear()
        prev_mode = cur_mode

        if cur_mode == 'cash':
            # 현금 기간 — 매매 안 함
            continue

        d1 = ds[i-1]; d2 = ds[i-2]
        rp = bp_ if cur_mode == 'attack' else dp_
        er = rp['ENTRY_RANK']; xr = rp['EXIT_RANK']; ms = rp['MAX_SLOTS']
        sl = rp.get('STOP_LOSS', -0.10); tr = rp.get('TRAILING_STOP', -0.15)

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

        rks = ad.get(d0, {}).get('rankings', [])
        rks1 = ad.get(d1, {}).get('rankings', [])
        rks2 = ad.get(d2, {}).get('rankings', [])
        t0 = {r['ticker']: r for r in rks if r.get('composite_rank', r['rank']) <= 20}
        t1 = {r['ticker']: r for r in rks1 if r.get('composite_rank', r['rank']) <= 20}
        t2 = {r['ticker']: r for r in rks2 if r.get('composite_rank', r['rank']) <= 20}
        com = set(t0) & set(t1) & set(t2)
        a0 = {r['ticker']: r for r in rks}; a1 = {r['ticker']: r for r in rks1}; a2 = {r['ticker']: r for r in rks2}

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
        return {'yearly': yearly, 'cagr': 0, 'mdd': 0, 'cal': 0, 'total': 0, 'cash_days': 0}
    pk_arr = np.maximum.accumulate(ea)
    dd = (ea - pk_arr)/pk_arr
    mdd = round(abs(dd.min())*100, 1)
    days = len(ds)-2; yrs = days/252
    cagr = round((eq**(1/yrs)-1)*100, 1) if yrs > 0 else 0
    # 현금 기간 일수
    cash_days = sum(1 for d in ds if reg.get(d) == 'cash')
    return {'yearly': yearly, 'total': round((eq-1)*100, 1), 'cagr': cagr, 'mdd': mdd,
            'cal': round(cagr/mdd, 2) if mdd > 0 else 0, 'cash_days': cash_days}


scenarios = [
    ('v77 기본 (공격+방어)', None, None),
    ('방어 전부 현금(비교)', 0.0, None),  # 방어 전체 현금
    ('vol 3.5%', 3.5, None),
    ('vol 3.0%', 3.0, None),
    ('vol 2.5%', 2.5, None),
    ('vol 2.0%', 2.0, None),
    ('mom -25%', None, -25.0),
    ('mom -20%', None, -20.0),
    ('mom -15%', None, -15.0),
    ('vol 3.0% OR mom -20%', 3.0, -20.0),
    ('vol 2.5% OR mom -15%', 2.5, -15.0),
]

# "방어 전부 현금" = defense 자체를 cash 처리. 이는 이전 test_cash_defense와 유사하지만 vol=0.0이면 모든 defense 구간 크래시 → 전부 현금
# 실제로는 vol_thresh=-999 같이 하면 됨. 0.0은 작동 안 할수도. 별도 처리.

for label_range, drange in [('7.8년 (2018-07~2026-04)', ('20180702', '20260413')),
                              ('5.25년 (2021-01~2026-04)', ('20210104', '20260413'))]:
    print(f'\n═══ {label_range} ═══', flush=True)
    print(f'{"시나리오":<30} {"CAGR":>7} {"MDD":>7} {"Cal":>6} {"현금일":>6} | 연도별', flush=True)
    print('-' * 140, flush=True)
    for label, vt, mt in scenarios:
        if label == '방어 전부 현금(비교)':
            # 특수: 방어 전 구간 cash
            reg = {}
            md = 'defense'; stk = 0; ss = None
            for d in dates:
                ts = pd.Timestamp(d)
                kv = kospi.get(ts); mv = kp_ma200.get(ts)
                if kv is None or mv is None or pd.isna(mv):
                    reg[d] = md; continue
                s = 'attack' if kv > mv else 'defense'
                if s == ss: stk += 1
                else: stk = 1; ss = s
                if stk >= 5 and md != s:
                    md = s
                reg[d] = 'cash' if md == 'defense' else 'attack'
        else:
            reg = calc_regime_3tier(vol_thresh=vt, mom_thresh=mt)
        r = sim(boost, defense, reg, bp, dp, date_range=drange)
        y = ' '.join(f'{yr}:{r["yearly"].get(yr, 0):>+6.1f}%' for yr in sorted(r['yearly']))
        print(f'{label:<30} {r["cagr"]:>6.1f}% {r["mdd"]:>6.1f}% {r["cal"]:>5.2f} {r["cash_days"]:>5}일 | {y}', flush=True)

print('\n완료', flush=True)
