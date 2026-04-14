"""방어 모드 = 현금(0%) 비교 BT
시나리오:
  1. v77 기본 (공격 + 방어 모드)
  2. v77 공격 + 방어=현금 (방어 기간 포트폴리오 전량 청산, eq 유지)

KOSPI 벤치마크도 비교 (buy & hold)
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

dates = sorted(set(boost.keys()) & set(defense.keys()))
bp = get_regime_params('boost')
dp = get_regime_params('defense')


def calc_regime(confirm_days=5):
    reg = {}
    md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = kp_ma200.get(ts)
        if kv is None or mv is None or pd.isna(mv):
            reg[d] = md; continue
        s = bool(kv > mv)
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm_days and md != s:
            md = s
        reg[d] = md
    return reg


def sim(bdata, ddata, reg, bp_, dp_, date_range=None, defense_mode='normal'):
    """
    defense_mode:
      'normal' — 방어 모드 포트폴리오 운영 (v77 기본)
      'cash' — 방어 모드 기간 현금 0% 고정 (매매 안 함)
    """
    ad = {}; ds = []
    for d in sorted(set(bdata) & set(ddata)):
        if date_range and (d < date_range[0] or d > date_range[1]): continue
        ib = reg.get(d, True)
        if ib:
            if d in bdata: ad[d] = bdata[d]; ds.append(d)
        else:
            # 방어 기간
            if defense_mode == 'normal':
                if d in ddata: ad[d] = ddata[d]; ds.append(d)
            else:
                # cash 모드: 방어 기간은 날짜만 추가 (포트는 비움)
                ad[d] = {'rankings': []}
                ds.append(d)

    def gp(tk, ds_):
        ts = pd.Timestamp(ds_)
        if ts in ohlcv.index and tk in ohlcv.columns:
            v = ohlcv.loc[ts, tk]
            if pd.notna(v) and v > 0: return v
        return 0

    pf = {}; pk = {}; eq = 1.0; yeq = {}
    days_traded = 0  # 실제 매매한 날 (공격 기간)
    days_cash = 0    # 현금 보유한 날 (방어 기간, cash 모드)
    for i in range(len(ds)):
        d0 = ds[i]
        # 수익 반영
        if i >= 1 and pf:
            rets = []
            for tk in pf:
                pp = gp(tk, ds[i-1]); cp = gp(tk, d0)
                if pp > 0 and cp > 0: rets.append(cp/pp - 1)
            if rets: eq *= (1 + sum(rets)/len(rets))
        yeq[d0] = eq
        if i < 2: continue

        ib = reg.get(d0, True)

        # 방어 기간 + cash 모드 = 포트폴리오 비우고 넘김
        if not ib and defense_mode == 'cash':
            if pf:
                pf.clear(); pk.clear()
            days_cash += 1
            continue

        d1 = ds[i-1]; d2 = ds[i-2]
        rp = bp_ if ib else dp_
        er = rp['ENTRY_RANK']; xr = rp['EXIT_RANK']; ms = rp['MAX_SLOTS']
        sl = rp.get('STOP_LOSS', -0.10); tr = rp.get('TRAILING_STOP', -0.15)

        # 국면 전환 시 전량 청산
        prev_ib = reg.get(ds[i-1], True)
        if ib != prev_ib:
            pf.clear(); pk.clear()

        # cash 모드에서 이전이 cash였으면 포트 비어있음 → 재진입
        if not ib or defense_mode == 'normal':
            days_traded += 1

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
        return {'yearly': yearly, 'cagr': 0, 'mdd': 0, 'cal': 0, 'total': 0}
    pk_arr = np.maximum.accumulate(ea)
    dd = (ea - pk_arr)/pk_arr
    mdd = round(abs(dd.min())*100, 1)
    days = len(ds)-2; yrs = days/252
    cagr = round((eq**(1/yrs)-1)*100, 1) if yrs > 0 else 0
    return {'yearly': yearly, 'total': round((eq-1)*100, 1), 'cagr': cagr, 'mdd': mdd,
            'cal': round(cagr/mdd, 2) if mdd > 0 else 0,
            'days_traded': days_traded, 'days_cash': days_cash}


reg = calc_regime(5)

for label_range, drange in [('7.8년 (2018-07~2026-04)', ('20180702', '20260413')),
                              ('5.25년 (2021-01~2026-04)', ('20210104', '20260413'))]:
    print(f'\n═══ {label_range} ═══', flush=True)
    print(f'{"시나리오":<35} {"CAGR":>7} {"MDD":>7} {"Cal":>6} | 연도별', flush=True)
    print('-' * 130, flush=True)

    # 1. v77 기본 (공격 + 방어 포트폴리오)
    r1 = sim(boost, defense, reg, bp, dp, date_range=drange, defense_mode='normal')
    y1 = ' '.join(f'{yr}:{r1["yearly"].get(yr, 0):>+6.1f}%' for yr in sorted(r1['yearly']))
    print(f'{"v77 기본 (공격+방어포트)":<35} {r1["cagr"]:>6.1f}% {r1["mdd"]:>6.1f}% {r1["cal"]:>5.2f} | {y1}', flush=True)

    # 2. 공격만 + 방어=현금
    r2 = sim(boost, defense, reg, bp, dp, date_range=drange, defense_mode='cash')
    y2 = ' '.join(f'{yr}:{r2["yearly"].get(yr, 0):>+6.1f}%' for yr in sorted(r2['yearly']))
    print(f'{"공격만 + 방어=현금(0%)":<35} {r2["cagr"]:>6.1f}% {r2["mdd"]:>6.1f}% {r2["cal"]:>5.2f} | {y2}', flush=True)

    # 방어 기간 기여도 분해
    print(f'\n  v77 기본 총수익 {r1["total"]:.1f}%, MDD {r1["mdd"]:.1f}%', flush=True)
    print(f'  현금 방어 총수익 {r2["total"]:.1f}%, MDD {r2["mdd"]:.1f}%', flush=True)
    print(f'  차이: {r1["total"] - r2["total"]:+.1f}%p (방어 모드가 현금 대비 추가 획득)', flush=True)

print('\n완료', flush=True)
