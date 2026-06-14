# -*- coding: utf-8 -*-
"""국면 전환 기준 full-config 전면 재탐색 (2026-06-14) — 최고 레버리지.
production wr(과열캡·신팩터·페널티 다 포함) replay + E3X6S3.
단기MA × 장기MA × 확인일(대칭) 그리드 → 최적 WF + 인접CV + 비대칭.
현행: MA20>MA80, 5일 대칭.
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
print(f'[데이터] {dates[0]}~{dates[-1]} {len(dates)}일 (production wr full-config replay)')

kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
MA = {n: kc.rolling(n).mean() for n in [5, 10, 15, 20, 25, 30, 60, 80, 100, 120, 150, 200]}

def calc_reg(short_n, long_n, exit_confirm, entry_confirm, dsub=None):
    sma, lma = MA[short_n], MA[long_n]
    ds = dsub or dates
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
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

def replay(reg, dsub=None):
    ds = dsub or dates
    hold = set(); rets = []
    for i in range(len(ds)-1):
        d, dn = ds[i], ds[i+1]
        if not reg[d]:
            hold = set(); rets.append(0.0); continue
        rank = rk[d]
        hold = {t for t in hold if rank.get(t, 9999) <= 6}
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

# ===== 1) 대칭 그리드: 단기MA × 장기MA × 확인일 =====
print('\n========== 국면 전환 그리드 (단기MA × 장기MA × 확인일, 대칭) ==========')
shorts = [10, 15, 20, 25, 30]
longs = [60, 80, 100, 120, 150]
confirms = [3, 5, 8]
results = []
for sn in shorts:
    for ln in longs:
        if sn >= ln: continue
        for cf in confirms:
            reg = calc_reg(sn, ln, cf, cf)
            cg, md, cal = metrics(replay(reg))
            results.append((sn, ln, cf, cal, cg, md, switches(reg)))
results.sort(key=lambda x: -x[3])
print(f"{'순위':>3}{'단기':>5}{'장기':>5}{'확인':>5}{'Calmar':>9}{'CAGR':>8}{'MDD':>8}{'전환':>6}")
for i, (sn, ln, cf, cal, cg, md, sw) in enumerate(results[:12], 1):
    cur = ' ← 현행' if (sn, ln, cf) == (20, 80, 5) else ''
    print(f"{i:>3}{sn:>5}{ln:>5}{cf:>5}{cal:>9.3f}{cg:>8.1f}{md:>8.1f}{sw:>5}회{cur}")
# 현행 위치
for i, r in enumerate(results, 1):
    if (r[0], r[1], r[2]) == (20, 80, 5):
        print(f"\n  현행(20/80/5) 전체 {len(results)}개 중 {i}위: Cal {r[3]:.3f} CAGR {r[4]:.1f} MDD {r[5]:.1f}")

# ===== 2) 상위 후보 WF 검증 =====
print('\n========== 상위 후보 WF 기간분할 (과적합 체크) ==========')
splits = [('2019-21', '20190102', '20211231'), ('2022-23', '20220101', '20231231'),
          ('2024-26', '20240101', '20261231')]
cand = [(20, 80, 5)] + [(r[0], r[1], r[2]) for r in results[:4] if (r[0], r[1], r[2]) != (20, 80, 5)]
cand = cand[:5]
print(f"{'설정':>14}" + ''.join(f"{nm:>12}" for nm, _, _ in splits) + f"{'최소':>8}")
for sn, ln, cf in cand:
    row = []; mn = 99
    for nm, lo, hi in splits:
        dsub = [d for d in dates if lo <= d <= hi]
        cal = metrics(replay(calc_reg(sn, ln, cf, cf, dsub), dsub))[2]
        row.append(cal); mn = min(mn, cal)
    cur = ' ←현행' if (sn, ln, cf) == (20, 80, 5) else ''
    print(f"{f'{sn}/{ln}/{cf}':>14}" + ''.join(f"{c:>12.2f}" for c in row) + f"{mn:>8.2f}{cur}")

# ===== 3) 최적 후보 인접안정성 (확인일 주변) =====
best = results[0]
print(f'\n========== 인접안정성: 최적 {best[0]}/{best[1]}/{best[2]} 주변 ==========')
sn, ln = best[0], best[1]
print('  [확인일 스윕]')
cals = []
for cf in [3, 4, 5, 6, 8, 10]:
    cal = metrics(replay(calc_reg(sn, ln, cf, cf)))[2]
    cals.append(cal); print(f"   확인 {cf}일: Cal {cal:.3f}")
print(f"   → CV {np.std(cals)/np.mean(cals):.3f}")
print('  [장기MA 스윕]')
cals2 = []
for ln2 in [60, 70, 80, 90, 100, 120]:
    if ln2 in MA or True:
        if ln2 not in MA: MA[ln2] = kc.rolling(ln2).mean()
    cal = metrics(replay(calc_reg(sn, ln2, best[2], best[2])))[2]
    cals2.append(cal); print(f"   장기 {ln2}: Cal {cal:.3f}")
print(f"   → CV {np.std(cals2)/np.mean(cals2):.3f}")

# ===== 4) 최적 후보 비대칭 (exit/entry 확인일 분리) =====
print(f'\n========== 비대칭: {sn}/{ln} 최적, exit×entry 확인일 ==========')
print(f"{'exit↓entry→':>12}" + ''.join(f"{e:>8}일" for e in [2, 3, 5, 8]))
for ex in [3, 5, 8, 10]:
    row = []
    for en in [2, 3, 5, 8]:
        cal = metrics(replay(calc_reg(sn, ln, ex, en)))[2]
        row.append(cal)
    print(f"{ex:>11}일" + ''.join(f"{c:>9.2f}" for c in row))
