"""점수 기반 가중순위 BT — v77 순위 기반 vs 점수 기반 비교

순위 기반 (현재 v77):
    wr = cr_t0 × 0.5 + cr_t1 × 0.3 + cr_t2 × 0.2
    → 낮을수록 좋음 (1등, 2등, ...)

점수 기반 (제안):
    wr_score = score_t0 × 0.5 + score_t1 × 0.3 + score_t2 × 0.2
    → 높을수록 좋음, rank는 내림차순 정렬로 부여

기간: 7.8년 (2018-07~2026-04) + 5.25년 (2021-01~2026-04)
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
print(f'공통 날짜: {len(dates)} ({dates[0]} ~ {dates[-1]})', flush=True)

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


def sim(bdata, ddata, reg, bp_, dp_, date_range=None, score_based=False):
    """score_based=True이면 wr 계산을 score 기반으로"""
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
        a0 = {r['ticker']: r for r in r0}
        a1 = {r['ticker']: r for r in r1}
        a2 = {r['ticker']: r for r in r2}

        if score_based:
            # wr_score 계산: score × 가중치 합 (높을수록 좋음)
            score_miss = -3.0  # missing penalty (충분히 낮게)
            wr_scores = {}
            # 전체 t0 종목에 대해 계산
            for tk in a0:
                s0 = a0[tk].get('score', score_miss)
                s1 = a1[tk].get('score', score_miss) if tk in a1 else score_miss
                s2 = a2[tk].get('score', score_miss) if tk in a2 else score_miss
                wr_scores[tk] = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
            # 내림차순 rank 매김
            sorted_by_ws = sorted(wr_scores.items(), key=lambda x: -x[1])
            rank_map = {tk: i + 1 for i, (tk, _) in enumerate(sorted_by_ws)}
            # Top 20 필터: 각 날짜 composite_rank <= 20으로 3일 공통
            # 점수 기반에서는 cr 대신 각 날짜 score 내림차순 rank 기준으로 필터 가능
            def day_rank_map(rlist):
                scores = [(r['ticker'], r.get('score', score_miss)) for r in rlist]
                scores.sort(key=lambda x: -x[1])
                return {tk: i + 1 for i, (tk, _) in enumerate(scores)}
            d_rank_t0 = day_rank_map(r0)
            d_rank_t1 = day_rank_map(r1)
            d_rank_t2 = day_rank_map(r2)
            t0_set = {tk for tk, r in d_rank_t0.items() if r <= 20}
            t1_set = {tk for tk, r in d_rank_t1.items() if r <= 20}
            t2_set = {tk for tk, r in d_rank_t2.items() if r <= 20}
            com = t0_set & t1_set & t2_set
            rank_fn = lambda tk: rank_map.get(tk, 9999)
        else:
            # 순위 기반 (v77 기본)
            t0 = {r['ticker']: r for r in r0 if r.get('composite_rank', r['rank']) <= 20}
            t1 = {r['ticker']: r for r in r1 if r.get('composite_rank', r['rank']) <= 20}
            t2 = {r['ticker']: r for r in r2 if r.get('composite_rank', r['rank']) <= 20}
            com = set(t0) & set(t1) & set(t2)
            def wr(tk):
                if tk not in a0: return 999
                c0 = a0[tk].get('composite_rank', 999)
                c1 = a1[tk].get('composite_rank', 999) if tk in a1 else 999
                c2 = a2[tk].get('composite_rank', 999) if tk in a2 else 999
                return c0*0.5 + c1*0.3 + c2*0.2
            # 전체 wr 내림차순... 아니 오름차순 (낮을수록 좋음)
            # entry/exit 기준을 rank로 변환: 전체 종목 wr 정렬 후 순위
            all_tks = list(a0.keys())
            sorted_tks = sorted(all_tks, key=lambda x: wr(x))
            rank_map = {tk: i + 1 for i, tk in enumerate(sorted_tks)}
            rank_fn = lambda tk: rank_map.get(tk, 9999)

        # 퇴출
        for tk in list(pf):
            if rank_fn(tk) > xr: del pf[tk]

        # 진입
        vf = sorted([{'ticker': tk, 'r': rank_fn(tk)} for tk in com], key=lambda x: x['r'])
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


reg = calc_regime(5)

for label_range, drange in [('7.8년 (2018-07~2026-04)', ('20180702', '20260413')),
                              ('5.25년 (2021-01~2026-04)', ('20210104', '20260413'))]:
    print(f'\n═══ {label_range} ═══', flush=True)
    print(f'{"방식":<25} {"CAGR":>7} {"MDD":>7} {"Cal":>6} | 연도별', flush=True)
    print('-' * 130, flush=True)

    for label, sb in [('v77 순위 기반 (현재)', False), ('v77 점수 기반 (테스트)', True)]:
        r = sim(boost, defense, reg, bp, dp, date_range=drange, score_based=sb)
        y = ' '.join(f'{yr}:{r["yearly"].get(yr, 0):>+6.1f}%' for yr in sorted(r['yearly']))
        print(f'{label:<25} {r["cagr"]:>6.1f}% {r["mdd"]:>6.1f}% {r["cal"]:>5.2f} | {y}', flush=True)

print('\n완료', flush=True)
