# -*- coding: utf-8 -*-
"""복귀(defense->boost) 확인일 비대칭 재검증 (2026-07-31, 사용자 질문).
질문: "해제가 5일 연속 벗어나야 성과가 좋았나? 하루만에 벗어나는 게 낫지 않나?"
기존 _regime_transition_search.py는 entry_confirm 2,3,5,8만 봤고 1을 안 봄.
MA20/80 고정, exit(방어전환)×entry(공격복귀) 확인일 그리드 + 기간분할.
"""
import sys, io, os, glob, json
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

rk = {}
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_2019*.json'))
              + glob.glob(os.path.join(PROJ, 'state', 'ranking_202[0-6]*.json'))):
    dt = os.path.basename(f).replace('ranking_', '').replace('.json', '')
    if dt < '20190102':
        continue
    try:
        d = json.load(open(f, encoding='utf-8'))
        rk[dt] = {x['ticker']: x['weighted_rank'] for x in d['rankings']}
    except Exception:
        pass
dates = sorted(rk)
px = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*.parquet')),
        key=lambda f: f.split('_')[-1])[-1]).replace(0, np.nan).sort_index()
pxidx = {d: pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]) for d in dates}
print(f'[데이터] {dates[0]}~{dates[-1]} {len(dates)}일')

kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
MA = {n: kc.rolling(n).mean() for n in [20, 80]}


def calc_reg(exit_confirm, entry_confirm, short_n=20, long_n=80):
    """exit_confirm = 방어전환(boost->defense) 확인일
       entry_confirm = 공격복귀(defense->boost) 확인일"""
    sma, lma = MA[short_n], MA[long_n]
    reg = {}; md = True; stk = 0; ss = None
    for d in dates:
        ts = pxidx[d]
        if ts not in kc.index or pd.isna(lma.get(ts, np.nan)):
            reg[d] = md; continue
        s = bool(sma[ts] > lma[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        need = entry_confirm if s else exit_confirm
        if stk >= need and md != s: md = s
        reg[d] = md
    return reg


def ret1(tk, d, dn):
    if tk not in px.columns: return None
    s = px[tk]; a, b = s.get(pxidx[d]), s.get(pxidx[dn])
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a <= 0: return None
    r = b/a - 1
    return None if abs(r) > 0.35 else r


def replay(reg, exit_rank=6, dsub=None):
    ds = dsub or dates
    hold = set(); rets = []
    for i in range(len(ds)-1):
        d, dn = ds[i], ds[i+1]
        if not reg[d]:
            hold = set(); rets.append(0.0); continue
        rank = rk[d]
        hold = {t for t in hold if rank.get(t, 9999) <= exit_rank}
        if len(hold) < 3:
            for t in sorted([t for t in rank if rank[t] <= 3 and t not in hold], key=lambda t: rank[t]):
                if len(hold) >= 3: break
                hold.add(t)
        pairs = [(t, ret1(t, d, dn)) for t in hold]
        pairs = [r for _, r in pairs if r is not None]
        rets.append(float(np.mean(pairs)) if pairs else 0.0)
    return np.array(rets)


def metrics(rets):
    eq = np.cumprod(1+rets); n = len(rets)
    cagr = (eq[-1]**(252/max(n, 1))-1)*100
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))
    mdd = abs(((np.concatenate([[1.0], eq])-peak)/peak).min())*100
    return cagr, mdd, (cagr/mdd if mdd > 0 else 0)


def switches(reg, ds=None):
    ds = ds or dates
    v = [reg[d] for d in ds]
    return sum(1 for i in range(1, len(v)) if v[i] != v[i-1])


BLOCKS = [('2019-21', '20190102', '20211231'),
          ('2022-23약세', '20220101', '20231231'),
          ('2024-26', '20240101', '20261231')]

for XR in (6, 5):
    print(f'\n{"="*78}')
    print(f'========== 이탈룰 X{XR} : exit(방어전환)일 × entry(공격복귀)일 → Calmar ==========')
    print(f'{"exit↓ / entry→":>16}' + ''.join(f'{e:>9}일' for e in [1, 2, 3, 5, 8]))
    best = []
    for ex in [3, 5, 8]:
        row = []
        for en in [1, 2, 3, 5, 8]:
            reg = calc_reg(ex, en)
            cal = metrics(replay(reg, XR))[2]
            row.append(cal); best.append((cal, ex, en))
        print(f'{ex:>15}일' + ''.join(f'{c:>10.2f}' for c in row))
    b = sorted(best, reverse=True)[:3]
    print(f'  최고: ' + ' | '.join(f'exit{e}/entry{n} = {c:.2f}' for c, e, n in b))

print(f'\n{"="*78}')
print('========== 현행(5/5) vs 복귀 빠르게(5/1, 5/2, 5/3) 상세 ==========')
for ex, en in [(5, 5), (5, 3), (5, 2), (5, 1)]:
    reg = calc_reg(ex, en)
    r = replay(reg, 6)
    cagr, mdd, cal = metrics(r)
    tag = ' ← 현행' if (ex, en) == (5, 5) else ''
    print(f'\n[방어{ex}일 / 복귀{en}일] Calmar {cal:.3f}  CAGR {cagr:.1f}%  MDD -{mdd:.1f}%  전환 {switches(reg)}회{tag}')
    for nm, s, e in BLOCKS:
        ds = [d for d in dates if s <= d <= e]
        if len(ds) < 30: continue
        c2, m2, cl2 = metrics(replay(reg, 6, ds))
        print(f'    {nm:12s} Calmar {cl2:5.2f}  CAGR {c2:7.1f}%  MDD -{m2:5.1f}%')
